"""Autonomous nurture follow-ups (Phase 10).

When a visit is booked we enqueue a 24h-before reminder and a post-visit
sequence (24h / 72h / 7d). A background worker sends the ones whose
`scheduled_for` has passed — skipping leads on human takeover, cancelled visits,
and the 72h nudge when the lead already replied after the visit. Messages are
bilingual and sent as the AI agent through the lead's active channel.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentSettings,
    Conversation,
    FollowUp,
    FollowUpKind,
    FollowUpStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
    Visit,
    VisitStatus,
)
from app.services.conversation import _dispatch_send, _latest_active_conversation
from app.services.i18n import detect_language, pick_supported_language

log = logging.getLogger(__name__)

# Offsets relative to the visit's scheduled_at.
_POST_VISIT_OFFSETS = {
    FollowUpKind.POST_VISIT_24H: timedelta(hours=24),
    FollowUpKind.POST_VISIT_72H: timedelta(hours=72),
    FollowUpKind.POST_VISIT_7D: timedelta(days=7),
}

# Bilingual templates. {name} is dropped cleanly when the lead has no name.
_TEMPLATES: dict[FollowUpKind, dict[str, str]] = {
    FollowUpKind.REMINDER_24H: {
        "en": "Hi{name}! Just a reminder of your visit tomorrow with {agency}. See you there — reply here if anything comes up.",
        "es": "¡Hola{name}! Te recuerdo tu visita de mañana con {agency}. ¡Nos vemos! Si surge algo, respondé por acá.",
    },
    FollowUpKind.POST_VISIT_24H: {
        "en": "Hi{name}, how did the visit go? Anything you liked, or something else you'd like to see?",
        "es": "Hola{name}, ¿qué te pareció la visita? ¿Te gustó algo, o querés ver otra opción?",
    },
    FollowUpKind.POST_VISIT_72H: {
        "en": "Hi{name}, just checking in on the property you saw. Happy to answer any questions or line up another viewing.",
        "es": "Hola{name}, ¿pudiste pensar en la propiedad que viste? Quedo para cualquier duda o para coordinar otra visita.",
    },
    FollowUpKind.POST_VISIT_7D: {
        "en": "Hi{name}, we have new listings similar to what you saw. Want me to send you a few?",
        "es": "Hola{name}, tenemos nuevas propiedades parecidas a la que viste. ¿Te paso algunas?",
    },
}


def _first_name(lead: Lead) -> str:
    if not lead.name:
        return ""
    return " " + lead.name.strip().split()[0]


async def _agency_name(db: AsyncSession) -> str:
    cfg = (await db.execute(select(AgentSettings).where(AgentSettings.id == 1))).scalar_one_or_none()
    return cfg.agency_name if cfg and cfg.agency_name else "the team"


async def _lead_language(lead: Lead, db: AsyncSession) -> str:
    """Best-effort language for nurture text: from the lead's last inbound, else
    the agency's primary supported language."""
    cfg = (await db.execute(select(AgentSettings).where(AgentSettings.id == 1))).scalar_one_or_none()
    supported = (cfg.languages if cfg else ["en"]) or ["en"]
    last_in = (
        await db.execute(
            select(Message.content)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id == lead.id, Message.direction == MessageDirection.INBOUND)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_in:
        return pick_supported_language(detect_language(last_in), supported)
    return supported[0]


# ── Enqueue ──────────────────────────────────────────────────────────────


async def enqueue_for_visit(visit: Visit, db: AsyncSession, *, now: datetime | None = None) -> int:
    """Idempotently schedule the reminder + post-visit follow-ups for a visit.

    Returns how many NEW follow-ups were created. Safe to call repeatedly
    (UNIQUE(visit_id, kind)).
    """
    now = now or datetime.now(UTC)
    if visit.status in (VisitStatus.CANCELLED, VisitStatus.NO_SHOW):
        return 0

    when = visit.scheduled_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    planned: list[tuple[FollowUpKind, datetime]] = []
    reminder_at = when - timedelta(hours=24)
    if reminder_at > now:  # only schedule a reminder if it's still in the future
        planned.append((FollowUpKind.REMINDER_24H, reminder_at))
    for kind, offset in _POST_VISIT_OFFSETS.items():
        planned.append((kind, when + offset))

    existing = set(
        (
            await db.execute(select(FollowUp.kind).where(FollowUp.visit_id == visit.id))
        ).scalars().all()
    )

    created = 0
    for kind, sched in planned:
        if kind in existing:
            continue
        db.add(
            FollowUp(
                lead_id=visit.lead_id,
                visit_id=visit.id,
                kind=kind,
                status=FollowUpStatus.PENDING,
                scheduled_for=sched,
            )
        )
        created += 1
    if created:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            created = 0
    return created


# ── Process due ────────────────────────────────────────────────────────────


async def _lead_replied_since(lead_id: int, since: datetime, db: AsyncSession) -> bool:
    n = (
        await db.execute(
            select(func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.lead_id == lead_id,
                Message.direction == MessageDirection.INBOUND,
                Message.created_at > since,
            )
        )
    ).scalar_one()
    return n > 0


async def process_due_followups(db: AsyncSession, *, now: datetime | None = None, limit: int = 50) -> dict[str, int]:
    """Send (or skip) all pending follow-ups whose time has come.

    Returns counts {sent, skipped, failed}.
    """
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(FollowUp)
            .where(FollowUp.status == FollowUpStatus.PENDING, FollowUp.scheduled_for <= now)
            .order_by(FollowUp.scheduled_for)
            .limit(limit)
        )
    ).scalars().all()

    sent = skipped = failed = 0
    agency = await _agency_name(db)

    for fu in rows:
        lead = (await db.execute(select(Lead).where(Lead.id == fu.lead_id))).scalar_one_or_none()
        if lead is None:
            fu.status = FollowUpStatus.CANCELLED
            skipped += 1
            continue

        # Skip rules.
        if lead.human_takeover:
            fu.status = FollowUpStatus.SKIPPED
            skipped += 1
            continue
        if fu.visit_id is not None:
            visit = (await db.execute(select(Visit).where(Visit.id == fu.visit_id))).scalar_one_or_none()
            if visit is None or visit.status in (VisitStatus.CANCELLED, VisitStatus.NO_SHOW):
                fu.status = FollowUpStatus.CANCELLED
                skipped += 1
                continue
            if fu.kind == FollowUpKind.POST_VISIT_72H:
                sched_at = visit.scheduled_at
                if sched_at.tzinfo is None:
                    sched_at = sched_at.replace(tzinfo=UTC)
                if await _lead_replied_since(lead.id, sched_at, db):
                    fu.status = FollowUpStatus.SKIPPED  # they already re-engaged
                    skipped += 1
                    continue

        conv = await _latest_active_conversation(lead.id, db)
        if conv is None:
            fu.status = FollowUpStatus.SKIPPED
            skipped += 1
            continue

        lang = await _lead_language(lead, db)
        template = _TEMPLATES[fu.kind].get(lang) or _TEMPLATES[fu.kind]["en"]
        text = template.format(name=_first_name(lead), agency=agency)

        outbound = Message(
            conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND,
            sender=MessageSender.AGENT,
            content=text,
            delivery_status=MessageStatus.PENDING,
        )
        db.add(outbound)
        fu.attempts += 1
        try:
            external_id, _ = await _dispatch_send(conv.channel, to=lead.phone, text=text)
            outbound.external_id = external_id
            outbound.delivery_status = MessageStatus.SENT
            fu.status = FollowUpStatus.SENT
            fu.sent_at = now
            lead.last_message_at = now
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log.error("Follow-up %d dispatch failed: %s", fu.id, exc)
            outbound.delivery_status = MessageStatus.FAILED
            fu.status = FollowUpStatus.FAILED
            failed += 1

    await db.commit()
    if sent or skipped or failed:
        log.info("Follow-ups processed: sent=%d skipped=%d failed=%d", sent, skipped, failed)
    return {"sent": sent, "skipped": skipped, "failed": failed}

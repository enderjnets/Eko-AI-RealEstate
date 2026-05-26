"""Lead scoring — a 0-100 priority score with an explainable breakdown.

Deterministic and cheap: it scores the signals the pipeline already produced
(LLM-classified intent + LLM-extracted entities + engagement + recency + visit),
so the leads list can rank without a per-lead LLM call. Recomputed after each
inbound turn and on demand.

Components (sum to 100 before the status gate):
  intent 20 · budget 15 · engagement 15 · urgency 12 · zone 10 · recency 10 ·
  visit 10 · property_type 8

Status gate: WON / LOST → 0 (closed, no action), PAUSED → halved. Active pipeline
statuses keep the full score.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    Lead,
    LeadIntent,
    LeadStatus,
    Message,
    MessageDirection,
    Visit,
    VisitStatus,
)

log = logging.getLogger(__name__)

HOT_THRESHOLD = 67
WARM_THRESHOLD = 34

_ACTIVE_VISIT_STATUSES = (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED)


def score_tier(score: int) -> str:
    if score >= HOT_THRESHOLD:
        return "hot"
    if score >= WARM_THRESHOLD:
        return "warm"
    return "cold"


def compute_lead_score(
    *,
    lead: Lead,
    inbound_count: int,
    has_active_visit: bool,
    now: datetime | None = None,
) -> tuple[int, dict]:
    """Return `(score, breakdown)` for a lead. Pure — no DB access."""
    now = now or datetime.now(UTC)
    b: dict[str, int] = {}

    # Intent clarity (LLM-classified).
    if lead.intent in (LeadIntent.RENT, LeadIntent.BUY, LeadIntent.VALUATION):
        b["intent"] = 20
    elif lead.intent == LeadIntent.OTHER:
        b["intent"] = 8
    else:
        b["intent"] = 0

    # Budget defined (LLM-extracted).
    if lead.budget_min is not None and lead.budget_max is not None:
        b["budget"] = 15
    elif lead.budget_min is not None or lead.budget_max is not None:
        b["budget"] = 10
    else:
        b["budget"] = 0

    # Engagement — how many inbound messages the lead has sent.
    if inbound_count >= 4:
        b["engagement"] = 15
    elif inbound_count >= 2:
        b["engagement"] = 10
    elif inbound_count == 1:
        b["engagement"] = 5
    else:
        b["engagement"] = 0

    # Urgency (LLM-extracted; free-text, matched loosely).
    urgency = (lead.urgency or "").lower()
    if any(k in urgency for k in ("high", "alta", "urgent", "asap", "inmediat")):
        b["urgency"] = 12
    elif any(k in urgency for k in ("medium", "media", "moderat")):
        b["urgency"] = 7
    elif urgency:
        b["urgency"] = 3
    else:
        b["urgency"] = 0

    b["zone"] = 10 if lead.zone else 0
    b["property_type"] = 8 if lead.property_type else 0

    # Recency of the last message.
    if lead.last_message_at is not None:
        last = lead.last_message_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age_h = (now - last).total_seconds() / 3600
        if age_h <= 24:
            b["recency"] = 10
        elif age_h <= 72:
            b["recency"] = 7
        elif age_h <= 168:
            b["recency"] = 4
        else:
            b["recency"] = 0
    else:
        b["recency"] = 0

    b["visit"] = 10 if has_active_visit else 0

    base = sum(b.values())

    # Status gate.
    if lead.status in (LeadStatus.WON, LeadStatus.LOST):
        gate = 0.0
    elif lead.status == LeadStatus.PAUSED:
        gate = 0.5
    else:
        gate = 1.0

    score = int(round(base * gate))
    score = max(0, min(100, score))

    breakdown = {
        "components": b,
        "base": base,
        "status_gate": gate,
        "status": lead.status.value,
        "tier": score_tier(score),
    }
    return score, breakdown


async def _inbound_count(lead_id: int, db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count(Message.id))
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.lead_id == lead_id,
                Message.direction == MessageDirection.INBOUND,
            )
        )
    ).scalar_one()


async def _has_active_visit(lead_id: int, db: AsyncSession) -> bool:
    row = (
        await db.execute(
            select(Visit.id).where(
                Visit.lead_id == lead_id, Visit.status.in_(_ACTIVE_VISIT_STATUSES)
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def rescore_lead(lead: Lead, db: AsyncSession, *, commit: bool = True) -> int:
    """Recompute + persist a single lead's score. Returns the new score."""
    inbound = await _inbound_count(lead.id, db)
    has_visit = await _has_active_visit(lead.id, db)
    score, breakdown = compute_lead_score(lead=lead, inbound_count=inbound, has_active_visit=has_visit)
    lead.score = score
    lead.score_breakdown = breakdown
    if commit:
        await db.commit()
    return score


async def rescore_all(db: AsyncSession) -> int:
    """Recompute every lead's score in a couple of grouped queries. Returns count."""
    leads = (await db.execute(select(Lead))).scalars().all()

    # Inbound counts grouped by lead.
    rows = (
        await db.execute(
            select(Conversation.lead_id, func.count(Message.id))
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Message.direction == MessageDirection.INBOUND)
            .group_by(Conversation.lead_id)
        )
    ).all()
    inbound_by_lead = {lead_id: count for lead_id, count in rows}

    visit_rows = (
        await db.execute(
            select(Visit.lead_id).where(Visit.status.in_(_ACTIVE_VISIT_STATUSES)).distinct()
        )
    ).scalars().all()
    leads_with_visit = set(visit_rows)

    for lead in leads:
        score, breakdown = compute_lead_score(
            lead=lead,
            inbound_count=inbound_by_lead.get(lead.id, 0),
            has_active_visit=lead.id in leads_with_visit,
        )
        lead.score = score
        lead.score_breakdown = breakdown

    await db.commit()
    log.info("Rescored %d leads", len(leads))
    return len(leads)

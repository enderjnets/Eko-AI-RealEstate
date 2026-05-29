"""Inbox — the realtor's communications triage buzón.

Derives, per lead that has at least one conversation, the state a realtor needs
to triage: which channels it has used, whether the last message is still waiting
for our reply (`needs_response`), whether a visit is booked, and whether the
realtor already marked it handled (stored in `Lead.meta["inbox"]["handled_at"]`,
so no schema migration is needed).

All state is read with a handful of grouped queries (no per-lead loops).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    Lead,
    Message,
    MessageDirection,
    Visit,
    VisitStatus,
)

PREVIEW_LEN = 140
_ACTIVE_VISIT_STATUSES = (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED)


@dataclass
class InboxItem:
    lead: Lead
    channels: list[str]
    last_message_at: datetime | None
    last_direction: str | None
    last_channel: str | None
    last_preview: str | None
    needs_response: bool
    has_visit: bool
    next_visit_at: datetime | None
    visit_status: str | None
    handled_at: datetime | None


def _handled_at(lead: Lead) -> datetime | None:
    raw = (lead.meta or {}).get("inbox", {}).get("handled_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def set_handled(lead: Lead, when: datetime | None) -> None:
    """Mark (or clear when `when` is None) the lead as handled in `Lead.meta`.

    Reassigns the whole JSON dict so SQLAlchemy tracks the change (in-place dict
    mutation on a plain JSON column is not auto-tracked)."""
    meta = dict(lead.meta or {})
    inbox = dict(meta.get("inbox", {}))
    if when is None:
        inbox.pop("handled_at", None)
    else:
        inbox["handled_at"] = when.isoformat()
    meta["inbox"] = inbox
    lead.meta = meta


async def _last_message_per_lead(db: AsyncSession) -> dict[int, object]:
    """The most recent message (any channel) per lead, with its channel."""
    rows = (
        await db.execute(
            select(
                Conversation.lead_id.label("lead_id"),
                Message.direction.label("direction"),
                Message.content.label("content"),
                Message.created_at.label("created_at"),
                Conversation.channel.label("channel"),
            )
            .join(Conversation, Message.conversation_id == Conversation.id)
            .order_by(Conversation.lead_id, Message.created_at.desc(), Message.id.desc())
            .distinct(Conversation.lead_id)
        )
    ).all()
    return {r.lead_id: r for r in rows}


async def _channels_per_lead(db: AsyncSession) -> dict[int, list[str]]:
    """Distinct channels per lead, most-recently-active first."""
    rows = (
        await db.execute(
            select(
                Conversation.lead_id,
                Conversation.channel,
                func.max(Conversation.last_at).label("last_at"),
            )
            .group_by(Conversation.lead_id, Conversation.channel)
            .order_by(Conversation.lead_id, func.max(Conversation.last_at).desc())
        )
    ).all()
    out: dict[int, list[str]] = {}
    for lead_id, channel, _ in rows:
        bucket = out.setdefault(lead_id, [])
        if channel not in bucket:
            bucket.append(channel)
    return out


async def _next_visit_per_lead(db: AsyncSession) -> dict[int, object]:
    """The earliest upcoming SCHEDULED/CONFIRMED visit per lead."""
    rows = (
        await db.execute(
            select(
                Visit.lead_id.label("lead_id"),
                Visit.scheduled_at.label("scheduled_at"),
                Visit.status.label("status"),
            )
            .where(Visit.status.in_(_ACTIVE_VISIT_STATUSES))
            .order_by(Visit.lead_id, Visit.scheduled_at.asc())
            .distinct(Visit.lead_id)
        )
    ).all()
    return {r.lead_id: r for r in rows}


async def gather_inbox(db: AsyncSession) -> list[InboxItem]:
    """Build inbox items for every lead that has at least one conversation."""
    last = await _last_message_per_lead(db)
    if not last:
        return []
    channels = await _channels_per_lead(db)
    visits = await _next_visit_per_lead(db)

    leads = (
        await db.execute(select(Lead).where(Lead.id.in_(list(last.keys()))))
    ).scalars().all()

    items: list[InboxItem] = []
    for lead in leads:
        lm = last[lead.id]
        handled_at = _handled_at(lead)
        last_inbound = lm.direction == MessageDirection.INBOUND
        # Pending if the lead spoke last AND we haven't handled it since then.
        needs_response = last_inbound and (
            handled_at is None or (lm.created_at is not None and handled_at < lm.created_at)
        )
        v = visits.get(lead.id)
        items.append(
            InboxItem(
                lead=lead,
                channels=channels.get(lead.id, []),
                last_message_at=lm.created_at,
                last_direction=lm.direction.value,
                last_channel=lm.channel,
                last_preview=(lm.content or "")[:PREVIEW_LEN] or None,
                needs_response=needs_response,
                has_visit=v is not None,
                next_visit_at=v.scheduled_at if v else None,
                visit_status=v.status.value if v else None,
                handled_at=handled_at,
            )
        )
    return items

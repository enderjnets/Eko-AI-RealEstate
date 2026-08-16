"""Inbox — the realtor's communications triage buzón.

Derives, per lead that has at least one conversation, the state a realtor needs
to triage: which channels it has used, whether the last message is still waiting
for our reply (`needs_response`), whether a visit is booked, and whether the
realtor already marked it handled (the `Lead.inbox_handled_at` column).

All state is read with a handful of grouped queries (no per-lead loops).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    Lead,
    Message,
    MessageDirection,
    MessageStatus,
    Visit,
    VisitStatus,
)

PREVIEW_LEN = 140
_ACTIVE_VISIT_STATUSES = (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED)

# A lead with recent activity it hasn't been triaged ("handled") for still counts
# as needing attention even when it's not awaiting our reply — e.g. a just-finished
# voice call where the agent spoke last. Bounded so old untriaged leads don't pile in.
NEW_ACTIVITY_WINDOW_HOURS = 24


@dataclass
class InboxItem:
    lead: Lead
    channels: list[str]
    last_message_at: datetime | None
    last_direction: str | None
    last_channel: str | None
    last_preview: str | None
    needs_response: bool
    needs_attention: bool
    has_visit: bool
    next_visit_at: datetime | None
    visit_status: str | None
    handled_at: datetime | None


def set_handled(lead: Lead, when: datetime | None) -> None:
    """Mark (or clear when `when` is None) the lead as handled.

    Writes the dedicated `inbox_handled_at` column — independent of `Lead.meta`,
    so it never clobbers (or is clobbered by) other writers to the meta blob."""
    lead.inbox_handled_at = when


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
            # An outbound that never reached anybody is not an answer. Composing
            # a reply wrote the row, the row became the newest message, and the
            # lead dropped out of Pending — so a client who is still waiting
            # looked answered, and the one place a realtor would notice is the
            # place that stopped showing them. PENDING still counts: it is a
            # send in flight, and if it exhausts its retries it becomes FAILED
            # and the lead comes back.
            .where(
                or_(
                    Message.direction == MessageDirection.INBOUND,
                    Message.delivery_status != MessageStatus.FAILED,
                )
            )
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
    """The earliest UPCOMING SCHEDULED/CONFIRMED visit per lead.

    Filters out visits whose time has already passed (still SCHEDULED/CONFIRMED
    only because the status was never advanced to completed/no_show) so the inbox
    never shows a stale past visit as booked, and DISTINCT ON picks the next
    future visit rather than the earliest-ever one.
    """
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(
                Visit.lead_id.label("lead_id"),
                Visit.scheduled_at.label("scheduled_at"),
                Visit.status.label("status"),
            )
            .where(
                Visit.status.in_(_ACTIVE_VISIT_STATUSES),
                Visit.scheduled_at >= now,
            )
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

    now = datetime.now(UTC)
    fresh_cutoff = now - timedelta(hours=NEW_ACTIVITY_WINDOW_HOURS)

    items: list[InboxItem] = []
    for lead in leads:
        lm = last[lead.id]
        handled_at = lead.inbox_handled_at
        last_inbound = lm.direction == MessageDirection.INBOUND
        # Pending if the lead spoke last AND we haven't handled it since then.
        needs_response = last_inbound and (
            handled_at is None or (lm.created_at is not None and handled_at < lm.created_at)
        )
        # Needs attention = awaiting our reply OR a fresh, not-yet-triaged conversation
        # (e.g. a just-finished voice call). The recency window keeps old untriaged
        # leads from inflating the badge.
        is_fresh_untriaged = handled_at is None and (
            lm.created_at is not None and lm.created_at >= fresh_cutoff
        )
        needs_attention = needs_response or is_fresh_untriaged
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
                needs_attention=needs_attention,
                has_visit=v is not None,
                next_visit_at=v.scheduled_at if v else None,
                visit_status=v.status.value if v else None,
                handled_at=handled_at,
            )
        )
    return items

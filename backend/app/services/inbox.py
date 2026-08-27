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
from typing import Any

from sqlalchemy import and_, func, or_, select
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


def reached_somebody():
    """True unless this row cannot count as the last word of the exchange.

    Two exclusions, one per clause:

    * an outbound whose delivery FAILED — a reply that never left does not
      answer anybody;
    * an INTERNAL note — it reached somebody (the agency), but not the lead,
      and the lead's unanswered question is still unanswered. Without this, the
      agency's copy of an appointment invitation became the "last word" and
      silently pulled a waiting lead out of the triage queue — worst for a
      phone-only lead, where that note is the ONLY row the booking writes.

    Ranking key, deliberately not a filter — see `_last_message_per_lead`.

    Exported because the leads list keeps its own copy of `needs_response` and
    the two have to agree about what counts as the last word. They did not: this
    rule was added here and not there, and the other one's docstring still
    claimed it mirrored this one. One expression, imported by both.
    """
    return and_(
        Message.internal.is_(False),
        or_(
            Message.direction == MessageDirection.INBOUND,
            Message.delivery_status != MessageStatus.FAILED,
        ),
    )


PREVIEW_LEN = 140
_ACTIVE_VISIT_STATUSES = (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED)

# A lead with recent activity it hasn't been triaged ("handled") for still counts
# as needing attention even when it's not awaiting our reply — e.g. a just-finished
# voice call where the agent spoke last. Bounded so old untriaged leads don't pile in.
NEW_ACTIVITY_WINDOW_HOURS = 24


@dataclass
class InboxItem:
    # A column Row, not a `Lead` entity — see `gather_inbox`. It answers to
    # id/name/phone/status/intent/score/zone/human_takeover/inbox_handled_at
    # and to nothing else, so anything needing ORM behaviour must load the row
    # itself rather than reach through here.
    lead: Any
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


async def _last_reaching_message_per_lead(db: AsyncSession) -> dict[int, object]:
    """The most recent message per lead that actually reached somebody.

    Separate from `_last_message_per_lead` on purpose, and the separation is the
    whole point. What to *show* is the newest message, failed sends included —
    the realtor needs to see the attempt. Whether they still owe an answer is a
    different question, and a reply that never left does not answer anybody.

    Collapsing the two made a just-failed send invisible: the display fell back
    to the previous message, `last_message_at` froze at its timestamp, and the
    lead dropped out of the 24-hour attention window.

    Safe to filter here, unlike in `_last_message_per_lead`: this map is only
    ever read with `.get()`, so a lead with no surviving row simply has no
    entry — it cannot remove the lead from the inbox.
    """
    rows = (
        await db.execute(
            select(
                Conversation.lead_id.label("lead_id"),
                Message.direction.label("direction"),
                Message.created_at.label("created_at"),
            )
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(reached_somebody())
            .order_by(Conversation.lead_id, Message.created_at.desc(), Message.id.desc())
            .distinct(Conversation.lead_id)
        )
    ).all()
    return {r.lead_id: r for r in rows}


async def _last_message_per_lead(db: AsyncSession) -> dict[int, object]:
    """The most recent message (any channel) per lead, with its channel.

    Failed sends are shown on purpose (the realtor needs to see the attempt);
    INTERNAL notes are not. This map feeds the preview line and
    `last_message_at`: unfiltered, the inbox card read "Who: <name> / Phone:
    <number>" — the agency's copy of an invitation — as if it were the last
    thing said to the client, and the note's timestamp re-opened the 24-hour
    attention window for a lead nobody actually spoke to.
    """
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
            .where(Message.internal.is_(False))
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
    last_reaching = await _last_reaching_message_per_lead(db)
    channels = await _channels_per_lead(db)
    visits = await _next_visit_per_lead(db)

    # Columns, not entities. At ten thousand leads this single call was 6.2 of
    # the 13.5 seconds the function took, and none of it was the query: the
    # filter costs about 20ms and `load_only` changes nothing, because the cost
    # is SQLAlchemy building ten thousand instrumented, identity-mapped objects.
    # Selecting the nine columns anybody actually reads is 6x faster for the
    # same rows. Every consumer — here and in `api/v1/inbox.py` — touches only
    # these, and a Row answers to the same attribute names.
    leads = (
        await db.execute(
            select(
                Lead.id,
                Lead.name,
                Lead.phone,
                Lead.status,
                Lead.intent,
                Lead.score,
                Lead.zone,
                Lead.human_takeover,
                Lead.inbox_handled_at,
            ).where(Lead.id.in_(list(last.keys())))
        )
    ).all()

    now = datetime.now(UTC)
    fresh_cutoff = now - timedelta(hours=NEW_ACTIVITY_WINDOW_HOURS)

    items: list[InboxItem] = []
    for lead in leads:
        lm = last[lead.id]
        handled_at = lead.inbox_handled_at
        # `lm` is the newest message full stop — what the realtor should see,
        # including a send that just failed. Whether they still owe an answer is
        # a different question, so it reads the newest message that actually
        # reached somebody: ranking the failed row out of the display too made a
        # just-failed send invisible, froze `last_message_at` at the previous
        # message's time, and dropped the lead out of the attention window.
        reaching = last_reaching.get(lead.id)
        last_inbound = (
            reaching is not None and reaching.direction == MessageDirection.INBOUND
        )
        # Pending if the lead spoke last AND we haven't handled it since then.
        needs_response = last_inbound and (
            handled_at is None
            or (reaching.created_at is not None and handled_at < reaching.created_at)
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

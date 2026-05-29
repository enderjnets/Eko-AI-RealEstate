"""Inbox API — the realtor's communications buzón.

GET  /api/v1/inbox            → leads with conversations, filtered + priority-sorted.
GET  /api/v1/inbox/count      → {pending, booked} for the nav badge.
POST /api/v1/inbox/{id}/handled   → mark a lead handled (clears its pending badge).
DELETE /api/v1/inbox/{id}/handled → un-mark.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import Lead, LeadIntent, LeadStatus
from app.services.inbox import InboxItem, gather_inbox, set_handled
from app.services.scoring import score_tier

router = APIRouter()


class InboxItemOut(BaseModel):
    lead_id: int
    name: str | None
    identifier: str
    status: LeadStatus
    intent: LeadIntent | None
    zone: str | None
    score: int
    tier: str
    human_takeover: bool
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


class InboxListOut(BaseModel):
    items: list[InboxItemOut]
    pending_count: int
    booked_count: int


class InboxCountOut(BaseModel):
    pending: int
    booked: int


def _to_out(it: InboxItem) -> InboxItemOut:
    return InboxItemOut(
        lead_id=it.lead.id,
        name=it.lead.name,
        identifier=it.lead.phone,
        status=it.lead.status,
        intent=it.lead.intent,
        zone=it.lead.zone,
        score=it.lead.score,
        tier=score_tier(it.lead.score),
        human_takeover=it.lead.human_takeover,
        channels=it.channels,
        last_message_at=it.last_message_at,
        last_direction=it.last_direction,
        last_channel=it.last_channel,
        last_preview=it.last_preview,
        needs_response=it.needs_response,
        has_visit=it.has_visit,
        next_visit_at=it.next_visit_at,
        visit_status=it.visit_status,
        handled_at=it.handled_at,
    )


_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)
_FAR_PAST = datetime.min.replace(tzinfo=UTC)


def _sort_key_pending(it: InboxItem):
    # Highest score first; within a score, the one waiting longest (oldest last
    # message) first.
    return (-it.lead.score, it.last_message_at or _FAR_FUTURE)


def _sort_key_booked(it: InboxItem):
    return it.next_visit_at or _FAR_FUTURE


def _sort_key_all(it: InboxItem):
    return (-it.lead.score, _neg_time(it.last_message_at))


def _neg_time(dt: datetime | None) -> float:
    # Most-recent first → sort ascending on negative epoch.
    return -(dt.timestamp() if dt else _FAR_PAST.timestamp())


@router.get("", response_model=InboxListOut)
async def list_inbox(
    filter: str = Query(default="pending", pattern="^(pending|booked|all)$"),
    channel: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> InboxListOut:
    items = await gather_inbox(db)

    # Scope the counts to the channel filter so the chip badges match the rows
    # the user would see when switching tabs within the current channel scope.
    if channel:
        items = [it for it in items if channel in it.channels]

    pending_count = sum(1 for it in items if it.needs_response)
    booked_count = sum(1 for it in items if it.has_visit)

    if filter == "pending":
        items = [it for it in items if it.needs_response]
        items.sort(key=_sort_key_pending)
    elif filter == "booked":
        items = [it for it in items if it.has_visit]
        items.sort(key=_sort_key_booked)
    else:  # all
        items.sort(key=_sort_key_all)

    window = items[offset : offset + limit]
    return InboxListOut(
        items=[_to_out(it) for it in window],
        pending_count=pending_count,
        booked_count=booked_count,
    )


@router.get("/count", response_model=InboxCountOut)
async def inbox_count(db: AsyncSession = Depends(get_db)) -> InboxCountOut:
    items = await gather_inbox(db)
    return InboxCountOut(
        pending=sum(1 for it in items if it.needs_response),
        booked=sum(1 for it in items if it.has_visit),
    )


async def _get_lead(lead_id: int, db: AsyncSession) -> Lead:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/handled", response_model=InboxCountOut)
async def mark_handled(lead_id: int, db: AsyncSession = Depends(get_db)) -> InboxCountOut:
    """Mark the lead handled (clears its pending badge until a new inbound arrives)."""
    lead = await _get_lead(lead_id, db)
    set_handled(lead, datetime.now(UTC))
    await db.commit()
    return await inbox_count(db)


@router.delete("/{lead_id}/handled", response_model=InboxCountOut)
async def unmark_handled(lead_id: int, db: AsyncSession = Depends(get_db)) -> InboxCountOut:
    lead = await _get_lead(lead_id, db)
    set_handled(lead, None)
    await db.commit()
    return await inbox_count(db)

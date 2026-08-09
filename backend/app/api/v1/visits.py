"""Visits API — calendar slots + booking + cancellation.

Endpoints mounted at /api/v1:
  GET  /leads/{lead_id}/calendar/slots?days=7   — list available slots
  POST /leads/{lead_id}/calendar/book           — book a slot, create Visit
  GET  /leads/{lead_id}/visits                  — list all visits for a lead
  POST /visits/{visit_id}/cancel                — cancel a visit
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import (
    AgentSettings,
    FollowUp,
    FollowUpStatus,
    Lead,
    Visit,
    VisitStatus,
)
from app.services.calendar_cal import (
    CalComError,
    cancel_booking,
    create_booking,
    list_available_slots,
)
from app.services.tenant_context import get_org_id

log = logging.getLogger(__name__)

leads_calendar_router = APIRouter()
visits_router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────


class SlotOut(BaseModel):
    start: datetime
    end: datetime


class SlotsResponse(BaseModel):
    slots: list[SlotOut]
    timezone: str
    days: int


class BookingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: datetime
    duration_minutes: int = Field(default=30, ge=15, le=240)
    property_address: str | None = None
    notes: str | None = None
    # Defaults to the office timezone (AgentSettings) when omitted, so visits are
    # stored + displayed in the office's local tz rather than UTC.
    timezone: str | None = None


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int | None
    title: str | None
    calendar_provider: str
    external_booking_id: str
    status: VisitStatus
    scheduled_at: datetime
    duration_minutes: int
    timezone: str
    property_address: str | None
    meeting_url: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None


class ManualEventIn(BaseModel):
    """A manual calendar entry created by the realtor from the Calendar tab.

    `lead_id` is optional — a general event (open house, team meeting) has none."""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=600)
    notes: str | None = None
    property_address: str | None = None
    lead_id: int | None = None
    timezone: str | None = None


class CalendarItemOut(BaseModel):
    """A unified calendar entry: a lead visit, a manual event, or a pending
    system follow-up — so the Calendar tab can render them in one timeline."""
    kind: str  # "visit" | "event" | "followup"
    id: int
    title: str
    scheduled_at: datetime
    duration_minutes: int | None
    timezone: str | None
    status: str | None
    lead_id: int | None
    lead_name: str | None
    property_address: str | None
    notes: str | None


class AgendaOut(BaseModel):
    items: list[CalendarItemOut]
    timezone: str


# ── Helpers ────────────────────────────────────────────────────────────


async def _get_lead_or_404(lead_id: int, db: AsyncSession) -> Lead:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


async def _office_tz(db: AsyncSession) -> str:
    """The office IANA timezone from AgentSettings (singleton), default UTC."""
    cfg = (await db.execute(select(AgentSettings).where(AgentSettings.org_id == _acting_org()))).scalar_one_or_none()
    return (cfg.timezone if cfg and cfg.timezone else "UTC")


async def _busy_starts(
    db: AsyncSession, *, since: datetime, until: datetime
) -> set[datetime]:
    """Every start time this agency already has a visit at.

    Filtered by the acting organization, not by lead — the RLS session does the
    filtering, so no `org_id` clause is needed here and none is possible from
    another tenant. Scoping it to one lead meant two different leads were
    offered the same half-hour and both bookings succeeded, sending one realtor
    to two houses at once. A realtor's diary is a property of the agency, not
    of whoever happens to be asking.
    """
    rows = (
        await db.execute(
            select(Visit.scheduled_at).where(
                Visit.status.in_([VisitStatus.SCHEDULED, VisitStatus.CONFIRMED]),
                # Bounded to the window being offered. Unbounded, an agency with
                # years of history loaded its whole visit table into a Python
                # set on every availability request.
                Visit.scheduled_at >= since,
                Visit.scheduled_at < until,
            )
        )
    ).scalars().all()
    return {r for r in rows if r is not None}


# ── Endpoints ──────────────────────────────────────────────────────────


@leads_calendar_router.get("/leads/{lead_id}/calendar/slots", response_model=SlotsResponse)
async def list_slots(
    lead_id: int,
    days: int = Query(default=7, ge=1, le=30),
    tz: str = Query(default="UTC", alias="timezone"),
    db: AsyncSession = Depends(get_db),
) -> SlotsResponse:
    await _get_lead_or_404(lead_id, db)
    now = datetime.now(UTC)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    busy = await _busy_starts(db, since=start, until=end)
    try:
        slots = await list_available_slots(start=start, end=end, timezone_name=tz, busy_starts=busy)
    except CalComError as exc:
        raise HTTPException(status_code=503, detail=f"Cal.com unavailable: {exc}") from exc
    return SlotsResponse(
        slots=[SlotOut(start=s.start, end=s.end) for s in slots],
        timezone=tz,
        days=days,
    )


@leads_calendar_router.post("/leads/{lead_id}/calendar/book", response_model=VisitOut, status_code=201)
async def book_slot(
    lead_id: int,
    body: BookingIn,
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    lead = await _get_lead_or_404(lead_id, db)
    tz = body.timezone or await _office_tz(db)

    # Email-or-phone heuristic: lead.phone holds an email when channel is email.
    attendee_email = lead.phone if "@" in lead.phone else None
    attendee_phone = lead.phone if "@" not in lead.phone else None
    attendee_name = lead.name or "Cliente"

    try:
        booking = await create_booking(
            start_time=body.start_time,
            attendee_name=attendee_name,
            attendee_email=attendee_email,
            attendee_phone=attendee_phone,
            notes=body.notes,
            timezone_name=tz,
            duration_minutes=body.duration_minutes,
        )
    except CalComError as exc:
        raise HTTPException(status_code=503, detail=f"Cal.com booking failed: {exc}") from exc

    visit = Visit(
        lead_id=lead.id,
        calendar_provider="calcom",
        external_booking_id=booking.external_booking_id,
        status=VisitStatus.SCHEDULED,
        scheduled_at=booking.scheduled_at,
        duration_minutes=booking.duration_minutes,
        timezone=tz,
        property_address=body.property_address,
        meeting_url=booking.meeting_url,
        notes=body.notes,
    )
    db.add(visit)
    await db.commit()
    await db.refresh(visit)

    # Phase 10: schedule the reminder + post-visit nurture sequence.
    try:
        from app.services.followups import enqueue_for_visit
        await enqueue_for_visit(visit, db)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not enqueue follow-ups for visit %d: %s", visit.id, exc)

    return VisitOut.model_validate(visit)


@leads_calendar_router.get("/leads/{lead_id}/visits", response_model=list[VisitOut])
async def list_visits_for_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[VisitOut]:
    await _get_lead_or_404(lead_id, db)
    rows = (
        await db.execute(
            select(Visit).where(Visit.lead_id == lead_id).order_by(Visit.scheduled_at.desc())
        )
    ).scalars().all()
    return [VisitOut.model_validate(v) for v in rows]


@visits_router.post("/visits/{visit_id}/cancel", response_model=VisitOut)
async def cancel_visit(
    visit_id: int,
    body: CancelIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    visit = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one_or_none()
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    if visit.status in (VisitStatus.CANCELLED, VisitStatus.COMPLETED, VisitStatus.NO_SHOW):
        raise HTTPException(status_code=400, detail=f"Visit already in terminal status: {visit.status.value}")

    reason = (body.reason if body else None) or "Cancelled from dashboard"
    # Manual events aren't on Cal.com — skip the provider call for them.
    if visit.calendar_provider != "manual":
        ok = await cancel_booking(visit.external_booking_id, reason=reason)
        if not ok:
            raise HTTPException(status_code=503, detail="Cal.com cancellation failed")
    visit.status = VisitStatus.CANCELLED
    if reason and not visit.notes:
        visit.notes = f"Cancelled: {reason}"
    await db.commit()
    await db.refresh(visit)
    return VisitOut.model_validate(visit)


# ── Calendar tab: all visits + manual events + pending follow-ups ──────────

_FOLLOWUP_LABELS = {
    "reminder_24h": "Visit reminder",
    "post_visit_24h": "Post-visit check-in",
    "post_visit_72h": "Post-visit nudge",
    "post_visit_7d": "New listings follow-up",
}


def _visit_item(v: Visit) -> CalendarItemOut:
    lead_name = v.lead.name if v.lead else None
    return CalendarItemOut(
        kind="event" if v.lead_id is None else "visit",
        id=v.id,
        title=v.title or lead_name or "Visit",
        scheduled_at=v.scheduled_at,
        duration_minutes=v.duration_minutes,
        timezone=v.timezone,
        status=v.status.value,
        lead_id=v.lead_id,
        lead_name=lead_name,
        property_address=v.property_address,
        notes=v.notes,
    )


@visits_router.get("/visits", response_model=list[VisitOut])
async def list_all_visits(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> list[VisitOut]:
    """All visits + manual events across leads, optionally within [from, to]."""
    stmt = select(Visit)
    if from_:
        stmt = stmt.where(Visit.scheduled_at >= from_)
    if to:
        stmt = stmt.where(Visit.scheduled_at <= to)
    rows = (await db.execute(stmt.order_by(Visit.scheduled_at.asc()))).scalars().all()
    return [VisitOut.model_validate(v) for v in rows]


@visits_router.post("/visits", response_model=VisitOut, status_code=201)
async def create_manual_event(
    body: ManualEventIn,
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    """Create a manual calendar event (open house, meeting, ...). `lead_id` is
    optional; when set it links the event to that lead. No Cal.com round-trip —
    manual events are local-only (provider="manual")."""
    if body.lead_id is not None:
        await _get_lead_or_404(body.lead_id, db)
    tz = body.timezone or await _office_tz(db)
    # A naive scheduled_at is a wall-clock time in the office tz → localize to UTC
    # (same convention as the voice agent). An aware value is used as-is.
    scheduled_at = body.scheduled_at
    if scheduled_at.tzinfo is None:
        try:
            scheduled_at = scheduled_at.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)
        except (ZoneInfoNotFoundError, ValueError):
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
    visit = Visit(
        lead_id=body.lead_id,
        title=body.title,
        calendar_provider="manual",
        external_booking_id=f"manual-{uuid.uuid4().hex[:16]}",
        status=VisitStatus.SCHEDULED,
        scheduled_at=scheduled_at,
        duration_minutes=body.duration_minutes,
        timezone=tz,
        property_address=body.property_address,
        notes=body.notes,
    )
    db.add(visit)
    await db.commit()
    await db.refresh(visit)
    return VisitOut.model_validate(visit)


@visits_router.get("/visits/agenda", response_model=AgendaOut)
async def visits_agenda(
    days: int = Query(default=30, ge=1, le=120),
    db: AsyncSession = Depends(get_db),
) -> AgendaOut:
    """Unified upcoming agenda: active visits/events + PENDING system follow-ups
    within the next `days`. Powers the Calendar tab."""
    now = datetime.now(UTC)
    floor = now - timedelta(days=1)  # keep today visible even past its start
    horizon = now + timedelta(days=days)
    tz = await _office_tz(db)

    vrows = (
        await db.execute(
            select(Visit)
            .where(
                Visit.scheduled_at >= floor,
                Visit.scheduled_at <= horizon,
                Visit.status.in_([VisitStatus.SCHEDULED, VisitStatus.CONFIRMED]),
            )
            .order_by(Visit.scheduled_at.asc())
        )
    ).scalars().all()
    items = [_visit_item(v) for v in vrows]

    frows = (
        await db.execute(
            select(FollowUp)
            .where(
                FollowUp.status == FollowUpStatus.PENDING,
                FollowUp.scheduled_for >= floor,
                FollowUp.scheduled_for <= horizon,
            )
            .order_by(FollowUp.scheduled_for.asc())
        )
    ).scalars().all()
    for f in frows:
        lead_name = f.lead.name if f.lead else None
        items.append(
            CalendarItemOut(
                kind="followup",
                id=f.id,
                title=_FOLLOWUP_LABELS.get(f.kind.value, "Follow-up"),
                scheduled_at=f.scheduled_for,
                duration_minutes=None,
                timezone=tz,
                status=f.status.value,
                lead_id=f.lead_id,
                lead_name=lead_name,
                property_address=None,
                notes=None,
            )
        )

    items.sort(key=lambda i: i.scheduled_at)
    return AgendaOut(items=items, timezone=tz)


def _acting_org() -> int:
    """The org whose settings row applies to this call."""
    org_id = get_org_id()
    if org_id is None:
        # Was `or DEFAULT_ORG_ID`. It fails closed today because these paths run
        # on the RLS session — an unset org reads nothing and cannot write — but
        # the fallback is one `get_bypass_db` away from silently reading and
        # overwriting client zero's row, and there are six of these. Say so
        # instead of guessing.
        raise RuntimeError(
            "no acting organization is bound; refusing to fall back to the "
            "default one"
        )
    return org_id

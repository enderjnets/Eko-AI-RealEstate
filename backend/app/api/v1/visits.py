"""Visits API — calendar slots + booking + cancellation.

Endpoints mounted at /api/v1:
  GET  /leads/{lead_id}/calendar/slots?days=7   — list available slots
  POST /leads/{lead_id}/calendar/book           — book a slot, create Visit
  GET  /leads/{lead_id}/visits                  — list all visits for a lead
  POST /visits/{visit_id}/cancel                — cancel a visit
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import Lead, Visit, VisitStatus
from app.services.calendar_cal import (
    CalComError,
    cancel_booking,
    create_booking,
    list_available_slots,
)

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
    timezone: str = "UTC"


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
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


# ── Helpers ────────────────────────────────────────────────────────────


async def _get_lead_or_404(lead_id: int, db: AsyncSession) -> Lead:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


async def _busy_starts_for_lead(lead_id: int, db: AsyncSession) -> set[datetime]:
    """The lead's already-scheduled visit start times — filtered out of /slots
    so we never offer a slot that conflicts with another booking for THIS lead."""
    rows = (
        await db.execute(
            select(Visit.scheduled_at).where(
                Visit.lead_id == lead_id,
                Visit.status.in_([VisitStatus.SCHEDULED, VisitStatus.CONFIRMED]),
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
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    busy = await _busy_starts_for_lead(lead_id, db)
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
            timezone_name=body.timezone,
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
        timezone=body.timezone,
        property_address=body.property_address,
        meeting_url=booking.meeting_url,
        notes=body.notes,
    )
    db.add(visit)
    await db.commit()
    await db.refresh(visit)
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
    ok = await cancel_booking(visit.external_booking_id, reason=reason)
    if not ok:
        raise HTTPException(status_code=503, detail="Cal.com cancellation failed")
    visit.status = VisitStatus.CANCELLED
    if reason and not visit.notes:
        visit.notes = f"Cancelled: {reason}"
    await db.commit()
    await db.refresh(visit)
    return VisitOut.model_validate(visit)

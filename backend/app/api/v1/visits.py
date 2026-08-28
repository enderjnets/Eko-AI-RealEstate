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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._validators import trimmed, trimmed_or_none
from app.db.base import get_db
from app.models import (
    AgentSettings,
    FollowUp,
    FollowUpStatus,
    Lead,
    Property,
    Visit,
    VisitStatus,
)
from app.services.calendar_cal import (
    BookingUnrecordable,
    CalComError,
    cancel_booking,
    create_booking,
    ensure_recordable,
    list_available_slots,
)
from app.services.tenant_context import get_org_id
from app.services.timezones import resolve_zone

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


def _valid_timezone(value: object) -> object:
    """Trim, then prove it is a real IANA zone. Refuse rather than fall back.

    An unrecognised zone used to be swallowed by `_resolve_wall_clock`, which
    returned the wall clock stamped UTC. In Denver that files a 10:00
    appointment at 04:00 — six hours early, answered 201, with the bad string
    stored beside it. `" America/Denver"` pasted with a leading space was
    enough, and nothing anywhere said so.

    `settings.py` has always validated this field with `ZoneInfo` and returned
    a 400. The same string was shouted at on one endpoint and quietly moved an
    appointment six hours on another.

    Bad zones are told apart from unusable ones by `resolve_zone`, which is the
    single place that knows how many ways `ZoneInfo` can fail. The first version
    of this helper inlined that knowledge and got it wrong: it caught two of the
    three exception types, so a 300-character timezone escaped as an `OSError`
    and FastAPI answered **500** — where the same input, before this validator
    existed, had been a clean 422 from `max_length`. Adding a guard made that
    input strictly worse, which is why the knowledge now lives in one module and
    not in each caller. See `app/services/timezones.py` for the measured surface
    and for the macOS/Linux case-sensitivity difference.

    `bytes` is handled by `resolve_zone` rather than falling through the
    `isinstance(value, str)` gate: Pydantic coerces bytes to str **after** a
    `mode="before"` validator runs, so a str-only guard hands the model an
    unvalidated, untrimmed value. Not reachable over JSON — but this is the
    second time that exact hole has been written down in this repo without
    being closed.
    """
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return value
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed:
        return None
    if resolve_zone(trimmed) is None:
        raise ValueError(
            f"Unknown timezone {trimmed!r}. Use an IANA name such as "
            "'America/Denver'."
        )
    return trimmed


class BookingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: datetime
    duration_minutes: int = Field(default=30, ge=15, le=240)
    # Which listing this showing is for. The address stays as the human-
    # readable line and as the only thing a viewing arranged off-MLS has;
    # without the id the post-visit follow-up cannot name the house.
    # Bounded so a caller gets a 422 rather than a silent trim. The model
    # trims too, which is what stops a booking already made at Cal.com from
    # 500ing on the insert that was meant to record it.
    property_address: str | None = Field(default=None, max_length=280)
    property_id: int | None = None
    notes: str | None = None
    # Defaults to the office timezone (AgentSettings) when omitted, so visits are
    # stored + displayed in the office's local tz rather than UTC.
    timezone: str | None = Field(default=None, max_length=50)

    _tz = field_validator("timezone", mode="before")(
        classmethod(lambda cls, v: _valid_timezone(v))
    )
    # The SAME two nullable columns `ManualEventIn` writes, through the other
    # route into `visits`. The blank-means-absent rule was added to one schema
    # and not to the other, so `notes="  "` was still stored as "  " here and
    # asking whether a visit has notes still meant checking `IS NULL` AND
    # `= ''` — the fix's own stated reason, left half-applied one class away.
    # `Visit._clip` truncates but never strips, so nothing downstream repairs it.
    _trim_optional = field_validator("property_address", "notes", mode="before")(
        classmethod(lambda cls, v: trimmed_or_none(v))
    )


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
    property_id: int | None
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
    # Bounded so a caller gets a 422 rather than a silent trim. The model
    # trims too, which is what stops a booking already made at Cal.com from
    # 500ing on the insert that was meant to record it.
    property_address: str | None = Field(default=None, max_length=280)
    property_id: int | None = None
    lead_id: int | None = None
    timezone: str | None = Field(default=None, max_length=50)

    _tz = field_validator("timezone", mode="before")(
        classmethod(lambda cls, v: _valid_timezone(v))
    )

    # Split by the column's nullability, not by convenience: `title` refuses
    # NULL so it is trim-only and `min_length=1` refuses the blank; `notes` and
    # `property_address` accept NULL, where blank means absent. Lumping the
    # three together stored "" where the schema says "no notes".
    _trim_title = field_validator("title", mode="before")(
        classmethod(lambda cls, v: trimmed(v))
    )
    _trim_optional = field_validator("notes", "property_address", mode="before")(
        classmethod(lambda cls, v: trimmed_or_none(v))
    )


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
    property_id: int | None
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



async def _booking_contact(db: AsyncSession) -> str | None:
    """The agency's booking contact, read on the session we already hold."""
    from app.models.agent_settings import AgentSettings

    found = (
        await db.execute(select(AgentSettings.booking_contact_email))
    ).scalars().first()
    return (found or "").strip() or None


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


async def _ensure_slot_free(
    db: AsyncSession, *, start_time: datetime, duration_minutes: int
) -> None:
    """Refuse a start time the agency is already committed to.

    `_busy_starts` exists for this and its docstring describes this exact
    failure — two leads offered the same half-hour, both bookings succeeding,
    one realtor sent to two houses at once. It was fixed there and then only
    ever consulted when *offering* slots. Booking never asked.

    That is not a race: the second request can arrive a minute later, see the
    same free-looking calendar, and both clients get a confirmation for the
    same time. Whoever arrives second is standing outside a house nobody is
    coming to.

    Checked here, before `create_booking`, because the calendar booking is the
    irreversible half.
    """
    if start_time is None:
        return
    busy = await _busy_starts(
        db,
        since=start_time - timedelta(minutes=duration_minutes),
        until=start_time + timedelta(minutes=duration_minutes),
    )
    if start_time in busy:
        raise HTTPException(
            status_code=409,
            detail=(
                "slot_taken: there is already a visit at that time. Pick another "
                "slot — the calendar moved between the page loading and this click."
            ),
        )


async def _valid_property_or_400(property_id: int | None, db: AsyncSession) -> int | None:
    """Refuse a listing id that does not exist, before anything irreversible.

    A match can be purged by the MLS sync between the moment the card renders
    and the moment somebody clicks "book a showing". Writing the id blind hit
    the foreign key and surfaced as a 500 — and in `book_slot` the Cal.com
    booking is created first, so the lead received a real calendar invite for a
    showing the CRM never recorded and nothing reconciles.
    """
    if property_id is None:
        return None
    exists = (
        await db.execute(select(Property.id).where(Property.id == property_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=400, detail="unknown_property: that listing no longer exists"
        )
    return property_id


def _resolve_wall_clock(when: datetime, tz: str) -> datetime:
    """A naive time is a wall clock in the office's timezone, never UTC.

    `create_manual_event` has always done this and `book_slot` never did, so the
    same 10:00 meant two different instants depending on which route wrote it —
    in Denver, six hours apart. A naive value also silently defeats the
    double-booking check, because comparing it against the aware times already
    in the diary is simply False rather than an error.
    """
    if when.tzinfo is not None:
        return when
    zone = resolve_zone(tz)
    if zone is None:
        # NOT a fallback to UTC. That is what turned an unrecognised zone into
        # a six-hour error in Denver, stored with a 201 and no complaint —
        # exactly the "same 10:00, two different instants" this function was
        # written to end. The schemas now refuse a bad zone from the caller, so
        # reaching here means the ORGANISATION's configured timezone is
        # unusable, and saying so is the only answer that does not invent a
        # time for somebody's appointment.
        raise HTTPException(
            status_code=400,
            detail=(
                f"The configured timezone {tz!r} is not a known IANA zone, so "
                "this time cannot be resolved. Fix it in Settings."
            ),
        )

    resolved = when.replace(tzinfo=zone).astimezone(UTC)
    # `replace(tzinfo=...)` is not DST-aware and never raises for it, so the
    # hour that does not exist on a spring-forward date was silently moved an
    # hour later: 02:30 became a real appointment at 03:30, and 02:30 and 03:30
    # resolved to the same instant — which the new double-booking guard then
    # reads as a clash between two different requests. Refuse it instead of
    # inventing a time nobody asked for.
    if resolved.astimezone(zone).replace(tzinfo=None) != when:
        raise HTTPException(
            status_code=400,
            detail=(
                "nonexistent_local_time: that clock time does not exist on that "
                "date in this timezone — the clocks move forward through it"
            ),
        )
    # An ambiguous time on a fall-back date resolves to the first pass through
    # it (fold=0, still on summer time), deterministically.
    return resolved


# ── Endpoints ──────────────────────────────────────────────────────────


@leads_calendar_router.get("/leads/{lead_id}/calendar/slots", response_model=SlotsResponse)
async def list_slots(
    lead_id: int,
    days: int = Query(default=7, ge=1, le=30),
    tz: str = Query(default="UTC", alias="timezone", max_length=50),
    db: AsyncSession = Depends(get_db),
) -> SlotsResponse:
    # The same defect the POST beside this one was fixed for, on the GET that
    # feeds it. `" America/Denver"` — one pasted leading space — reached
    # `list_available_slots`, whose `except Exception` turns any bad zone into
    # UTC, and the slots came back six hours out with the bad string echoed
    # back in `timezone` so the caller believed they were the office's. Measured:
    # 10:00-06:00 becomes 10:00+00:00. Offering an hour is the same promise as
    # booking one, so it gets the same answer instead of a quiet fallback.
    #
    # Trimmed and defaulted exactly as `_valid_timezone` does for the request
    # bodies, so one product does not accept a pasted space on the POST and
    # refuse it on the GET next door — which is the shape of the bug being
    # fixed, not a fix for it.
    try:
        tz = _valid_timezone(tz) or "UTC"  # type: ignore[assignment]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    if lead.opted_out_at is not None:
        # Cal.com emails the attendee a confirmation and then reminders, so
        # booking somebody who told us to stop is us contacting them again
        # through a third party — which is neither less of a contact nor less
        # of a liability for having been sent by someone else's server.
        raise HTTPException(
            status_code=409,
            detail="lead_opted_out: this person asked not to be contacted",
        )
    property_id = await _valid_property_or_400(body.property_id, db)
    # Resolved before the conflict check, not after: a wall-clock time only
    # names a half-hour once you know whose office it belongs to.
    tz = body.timezone or await _office_tz(db)
    start_time = _resolve_wall_clock(body.start_time, tz)
    await _ensure_slot_free(
        db, start_time=start_time, duration_minutes=body.duration_minutes
    )

    # Email-or-phone heuristic: lead.phone holds an email when channel is email.
    # The lead's own address when we have one; `phone` holds it for
    # email-channel leads. Neither, and `create_booking` uses the
    # agency's booking contact rather than failing.
    attendee_email = lead.email or (lead.phone if "@" in (lead.phone or "") else None)
    attendee_phone = lead.phone if "@" not in lead.phone else None
    attendee_name = lead.name or "Cliente"

    try:
        booking = await create_booking(
            start_time=start_time,
            attendee_name=attendee_name,
            attendee_email=attendee_email,
            booking_contact=await _booking_contact(db),
            attendee_phone=attendee_phone,
            notes=body.notes,
            timezone_name=tz,
            duration_minutes=body.duration_minutes,
        )
    except CalComError as exc:
        raise HTTPException(status_code=503, detail=f"Cal.com booking failed: {exc}") from exc

    # The appointment exists now, so everything from here has to leave the
    # world consistent with that. If the calendar's reference will not fit the
    # column that has to cancel it later, `ensure_recordable` undoes the
    # booking — shared with the voice path, which had no such guard when this
    # one was written, because guarding one route and not its sibling is the
    # defect this codebase produces more than any other.
    try:
        booking = await ensure_recordable(booking)
    except BookingUnrecordable as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "calendar_id_too_long: the calendar returned a booking reference this "
                "system cannot store, so the appointment was cancelled again. Nothing "
                "was left on anyone's calendar."
                if exc.recovered
                else "calendar_id_too_long: the appointment was created but cannot be "
                "recorded or cancelled automatically. Check the calendar directly — "
                "the reference is in the server log."
            ),
        ) from exc

    visit = Visit(
        lead_id=lead.id,
        calendar_provider="calcom",
        external_booking_id=booking.external_booking_id,
        status=VisitStatus.SCHEDULED,
        scheduled_at=booking.scheduled_at,
        duration_minutes=booking.duration_minutes,
        timezone=tz,
        property_address=body.property_address,
        property_id=property_id,
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

    # The calendar invitation. AFTER the commit, on purpose: the booking is the
    # fact and this is the announcement of it, so nothing here may cost the
    # visit. `send_visit_invitation` swallows its own failures for the same
    # reason — and this is what makes the appointment reach a real calendar,
    # which `create_booking` has never done while CALENDAR_SIMULATED is true.
    from app.services.followups import _lead_language  # single source of truth
    from app.services.visit_invite import send_visit_invitation

    try:
        language = await _lead_language(lead, db)
    except Exception:  # noqa: BLE001 — a language guess must not cost the invitation
        language = "en"
    await send_visit_invitation(db, visit, lead, language=language)

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
    local_only: bool = Query(
        default=False,
        description=(
            "Cancel in Eko without calling the calendar. For a booking already "
            "cancelled in Cal.com, or a calendar that is misconfigured — "
            "otherwise the visit can never be cancelled from anywhere."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    visit = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one_or_none()
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    if visit.status in (VisitStatus.CANCELLED, VisitStatus.COMPLETED, VisitStatus.NO_SHOW):
        raise HTTPException(status_code=400, detail=f"Visit already in terminal status: {visit.status.value}")

    reason = (body.reason if body else None) or "Cancelled from dashboard"
    # Manual events aren't on Cal.com — skip the provider call for them.
    if visit.calendar_provider != "manual" and not local_only:
        try:
            ok = await cancel_booking(visit.external_booking_id, reason=reason)
        except CalComError as exc:
            # `list_slots` and `book_slot` already degraded on this; cancel did
            # not, so a misconfigured calendar turned a cancellation into a 500
            # and left the visit SCHEDULED — the realtor still shows up.
            # 503, and the visit stays as it was, so a retry is meaningful.
            log.warning("cancel refused, calendar unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Calendar unavailable; visit not cancelled. Retry, or use "
                    "?local_only=true to cancel in Eko alone."
                ),
            ) from exc
        if not ok:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Cal.com cancellation failed. Retry, or use "
                    "?local_only=true if it is already cancelled there."
                ),
            )
    visit.status = VisitStatus.CANCELLED
    if local_only:
        # Recorded, because the two states now differ: this visit is cancelled
        # here and may still stand on the calendar.
        reason = f"{reason} (cancelled in Eko only; check the calendar)"
        log.warning(
            "visit %s cancelled locally without calling the calendar", visit.id
        )
    if reason and not visit.notes:
        visit.notes = f"Cancelled: {reason}"
    await db.commit()
    await db.refresh(visit)

    # Tell the people, not just the calendar provider.
    #
    # Until this existed, `send_visit_invitation` was called from exactly two
    # places and both were bookings: the `cancelled=True` path and the
    # METHOD:CANCEL builder were written, commented, and unreachable. Cancelling
    # from the dashboard marked the row and left the appointment standing in the
    # lead's calendar and in the agent's — both would show up.
    #
    # AFTER the commit, and failure never rolls it back: a cancellation that was
    # recorded but could not be announced is still cancelled, and undoing it
    # would put back an appointment the agent already considers dead. The send
    # is best-effort by design and `send_visit_invitation` never raises.
    #
    # `local_only` still notifies. That flag means "do not call the calendar
    # provider", which is exactly the case where the provider is untrustworthy
    # and a human being told matters most.
    from app.services.followups import _lead_language  # single source of truth
    from app.services.visit_invite import send_visit_invitation

    lead = visit.lead  # lazy="joined"; None for a manual calendar event
    try:
        language = await _lead_language(lead, db) if lead is not None else "en"
    except Exception:  # noqa: BLE001 — a language guess must not cost the notice
        language = "en"
    await send_visit_invitation(db, visit, lead, language=language, cancelled=True)

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
        property_id=v.property_id,
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
    scheduled_at = _resolve_wall_clock(body.scheduled_at, tz)

    # Checked after the timezone is resolved, because a wall-clock time only
    # says which half-hour it occupies once you know which office it belongs
    # to. Manual events are how a realtor blocks out their own commitments, so
    # this is also where they find out they have double-booked themselves.
    await _ensure_slot_free(
        db, start_time=scheduled_at, duration_minutes=body.duration_minutes
    )

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
        property_id=await _valid_property_or_400(body.property_id, db),
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
                # When it will actually go out, not when it was originally for:
                # a held follow-up keeps its `scheduled_for` now and carries the
                # deferral in `postponed_until`, so reading the raw column would
                # show it in the past — or drop it off the calendar entirely.
                func.coalesce(FollowUp.postponed_until, FollowUp.scheduled_for) >= floor,
                func.coalesce(FollowUp.postponed_until, FollowUp.scheduled_for) <= horizon,
            )
            .order_by(func.coalesce(FollowUp.postponed_until, FollowUp.scheduled_for).asc())
        )
    ).scalars().all()
    for f in frows:
        lead_name = f.lead.name if f.lead else None
        items.append(
            CalendarItemOut(
                kind="followup",
                id=f.id,
                title=_FOLLOWUP_LABELS.get(f.kind.value, "Follow-up"),
                # The effective date, matching the filter and the sort above.
                # Projecting the raw column put a deferred follow-up back at its
                # original date — selected because COALESCE fell inside the
                # window, then rendered weeks in the past, before the endpoint's
                # own floor. Fixing a query in its WHERE and not in its SELECT
                # leaves it half-fixed and looking right.
                scheduled_at=f.postponed_until or f.scheduled_for,
                duration_minutes=None,
                timezone=tz,
                status=f.status.value,
                lead_id=f.lead_id,
                lead_name=lead_name,
                property_address=None,
                property_id=None,
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

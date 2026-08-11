"""Cal.com calendar service — list available slots + create / cancel bookings.

When CALENDAR_SIMULATED=true (dev default), all calls work in-memory: slots are
generated for the next 7 weekdays at 10/11/14/15/16 in the requested timezone,
bookings get synthetic `calcom-sim-<uuid>` ids, cancellation flips status only.
Lets us develop the dashboard + tests without a Cal.com account or event type.

When SIMULATED is off, the real Cal.com v2 API is hit with the acting
organization's own key and event type — a `calendar` row in `channel_routes`,
falling back to CALCOM_API_KEY + CALCOM_EVENT_TYPE_ID. Every agency booking
onto one shared calendar put their leads' names, emails and phone numbers in
front of another agency's realtors, and let one agency's bookings blank out
another's availability. The v2 shape can shift; if a real piloto fails, the
fix is here (no schema/orchestrator changes needed).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.services.channel_identity import (
    MissingChannelCredential,
    resolve_calendar_identity,
)

log = logging.getLogger(__name__)

SIMULATED_HOURS_OF_DAY = (10, 11, 14, 15, 16)  # local time
SIMULATED_DURATION_MIN = 30


class CalComError(RuntimeError):
    pass


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class BookingResult:
    external_booking_id: str
    scheduled_at: datetime
    duration_minutes: int
    meeting_url: str | None
    simulated: bool


# ── Simulated slots (dev mode) ─────────────────────────────────────────


def _simulated_slots(
    start: datetime,
    end: datetime,
    *,
    timezone_name: str = "UTC",
    busy_starts: set[datetime] | None = None,
) -> list[Slot]:
    """Weekday slots between [start, end), skipping any in `busy_starts`.

    The hours and the weekday test are LOCAL to the office, not to UTC. This
    argument used to be accepted by `list_available_slots` and then dropped on
    the way in here, so simulated availability was always generated in UTC
    while `_parse_dt` interprets the caller's time as office wall-clock. Any
    office not on UTC therefore had an availability calendar that did not line
    up with its own business hours: an agency in Denver asking for 3 PM was
    told nothing was free that day, because 3 PM Denver is 22:00 UTC and the
    generator only ever offered 10, 11, 14, 15 and 16 UTC.

    It also silently moved the weekend. A Saturday morning in Denver is still
    Friday evening in UTC, so slots were offered on days the office is shut.
    """
    busy = busy_starts or set()
    out: list[Slot] = []
    try:
        office = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 — a bad tz must not empty the calendar
        log.warning("Unknown timezone %r; generating slots in UTC", timezone_name)
        office = UTC

    day = start.astimezone(office).replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end.astimezone(office).replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end_day:
        if day.weekday() < 5:  # Mon-Fri, in the office's own week
            for hour in SIMULATED_HOURS_OF_DAY:
                # Rebuilt rather than `.replace(hour=…)` so a DST transition
                # lands on the right instant instead of an hour either side.
                slot_start = datetime(
                    day.year, day.month, day.day, hour, tzinfo=office
                )
                if slot_start < start or slot_start >= end:
                    continue
                if slot_start in busy:
                    continue
                slot_end = slot_start + timedelta(minutes=SIMULATED_DURATION_MIN)
                out.append(Slot(start=slot_start, end=slot_end))
        day += timedelta(days=1)
    return out


# ── Public API ─────────────────────────────────────────────────────────


async def list_available_slots(
    *,
    start: datetime,
    end: datetime,
    timezone_name: str = "UTC",
    busy_starts: set[datetime] | None = None,
) -> list[Slot]:
    """Return slots between [start, end). In SIMULATED mode, generated locally;
    otherwise hits Cal.com v2 `/slots/available`."""
    s = get_settings()

    if s.CALENDAR_SIMULATED:
        return _simulated_slots(
            start, end, timezone_name=timezone_name, busy_starts=busy_starts
        )

    try:
        identity = await resolve_calendar_identity()
    except MissingChannelCredential as exc:
        # As a CalComError, so the callers that already degrade gracefully on a
        # calendar outage — the voice tool, the visits endpoint — keep doing so
        # instead of turning a missing route into a 500.
        raise CalComError(str(exc)) from exc
    if not identity.credential or not identity.destination:
        raise CalComError(
            "Cal.com not configured for this organization: an API key and an "
            "event type must be set, either globally in .env or on the agency's "
            "calendar route. Set CALENDAR_SIMULATED=true for dev."
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{s.CALCOM_BASE_URL}/v2/slots/available",
            params={
                "eventTypeId": identity.destination,
                "startTime": start.isoformat(),
                "endTime": end.isoformat(),
                "timeZone": timezone_name,
            },
            headers={"Authorization": f"Bearer {identity.credential}"},
        )
        if resp.status_code >= 400:
            log.error("Cal.com slots fetch failed: %d %s", resp.status_code, resp.text[:300])
            raise CalComError(f"Cal.com slots HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()

    # v2 returns {data: {slots: {"2026-05-26": [{start: iso, end: iso}, …], …}}}
    out: list[Slot] = []
    data = (payload.get("data") or {}).get("slots") or {}
    for day_slots in data.values():
        if not isinstance(day_slots, list):
            continue
        for entry in day_slots:
            start_iso = entry.get("start") or entry.get("time")
            if not start_iso:
                continue
            slot_start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_iso = entry.get("end")
            slot_end = (
                datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
                if end_iso
                else slot_start + timedelta(minutes=SIMULATED_DURATION_MIN)
            )
            if busy_starts and slot_start in busy_starts:
                continue
            out.append(Slot(start=slot_start, end=slot_end))
    return sorted(out, key=lambda s: s.start)



async def _booking_contact_email() -> str | None:
    """The agency's own inbox, for the leads who never gave us an address.

    Most of them: the main channel is WhatsApp, so a lead is a phone number.
    Cal.com refuses a booking without an attendee address, and the derivation
    in use — the phone, if it happens to contain an "@" — is only ever true of
    email-channel leads. So every WhatsApp, SMS and voice booking failed
    against a real Cal.com account, invisibly, because the simulated mode that
    is the default everywhere but production returns before the HTTP call.

    Read on the RLS session, so it is this agency's address and no other's.
    """
    from sqlalchemy import select

    from app.db.base import get_session_factory
    from app.models.agent_settings import AgentSettings

    try:
        async with get_session_factory()() as db:
            found = (
                (await db.execute(select(AgentSettings.booking_contact_email)))
                .scalars()
                .first()
            )
    except Exception as exc:  # noqa: BLE001 — never fail a booking on a lookup
        # Re-raised as itself rather than folded into "no address configured".
        # A pool timeout, an unbound organization and a database outage all
        # surfaced as "set the agency's booking contact address in Settings",
        # sending an operator to change a setting that was never the problem.
        raise CalComError(
            f"could not read the agency's booking contact address: {exc}"
        ) from exc
    return (found or "").strip() or None


async def create_booking(
    *,
    start_time: datetime,
    booking_contact: str | None = None,
    attendee_name: str,
    attendee_email: str | None = None,
    attendee_phone: str | None = None,
    notes: str | None = None,
    timezone_name: str = "UTC",
    duration_minutes: int = SIMULATED_DURATION_MIN,
) -> BookingResult:
    """Create a booking. In SIMULATED mode returns a fake id; otherwise hits
    Cal.com v2 `/bookings`.

    For real Cal.com, attendee_email is REQUIRED (the platform requires email
    on bookings). attendee_phone is optional and stored as metadata.
    """
    s = get_settings()

    if s.CALENDAR_SIMULATED:
        sim_id = f"calcom-sim-{uuid.uuid4().hex[:12]}"
        log.info(
            "Cal.com SIMULATED booking attendee=%s phone=%s start=%s id=%s",
            attendee_email or attendee_phone, attendee_phone, start_time.isoformat(), sim_id,
        )
        return BookingResult(
            external_booking_id=sim_id,
            scheduled_at=start_time,
            duration_minutes=duration_minutes,
            meeting_url=None,
            simulated=True,
        )

    try:
        identity = await resolve_calendar_identity()
    except MissingChannelCredential as exc:
        # As a CalComError, so the callers that already degrade gracefully on a
        # calendar outage — the voice tool, the visits endpoint — keep doing so
        # instead of turning a missing route into a 500.
        raise CalComError(str(exc)) from exc
    if not identity.credential or not identity.destination:
        raise CalComError(
            "Cal.com not configured for this organization: an API key and an "
            "event type must be set, either globally or on the agency's "
            "calendar route. Booking onto the operator's calendar would put "
            "this lead's name, email and phone in front of another agency."
        )
    if not attendee_email:
        # Preferably handed in by a caller that already holds a session — this
        # runs inside an in-flight request, and opening a second pooled
        # connection per booking starves the pool under concurrency.
        attendee_email = booking_contact or await _booking_contact_email()
    if not attendee_email:
        raise CalComError(
            "this booking has no attendee email, and Cal.com requires one. Set "
            "the agency's booking contact address in Settings — the "
            "confirmation goes there, and the lead is confirmed on the channel "
            "they wrote on."
        )

    body: dict[str, Any] = {
        "eventTypeId": int(identity.destination),
        "start": start_time.isoformat(),
        "attendee": {
            "name": attendee_name,
            "email": attendee_email,
            "timeZone": timezone_name,
            "language": "es",
        },
    }
    if notes:
        body["bookingFieldsResponses"] = {"notes": notes}
    if attendee_phone:
        body["attendee"]["phoneNumber"] = attendee_phone

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{s.CALCOM_BASE_URL}/v2/bookings",
            json=body,
            headers={
                "Authorization": f"Bearer {identity.credential}",
                "Content-Type": "application/json",
                "cal-api-version": "2024-08-13",
            },
        )
        if resp.status_code >= 400:
            log.error("Cal.com booking failed: %d %s", resp.status_code, resp.text[:300])
            raise CalComError(f"Cal.com booking HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()

    data = payload.get("data") or payload
    booking_id = str(data.get("id") or data.get("uid") or "")
    meeting_url = data.get("meetingUrl") or data.get("videoCallUrl")
    if not booking_id:
        raise CalComError(f"Cal.com response missing booking id: {payload}")
    return BookingResult(
        external_booking_id=booking_id,
        scheduled_at=start_time,
        duration_minutes=duration_minutes,
        meeting_url=meeting_url,
        simulated=False,
    )


async def cancel_booking(external_booking_id: str, *, reason: str | None = None) -> bool:
    """Cancel a booking on Cal.com. SIMULATED mode is a no-op (returns True)."""
    s = get_settings()
    if s.CALENDAR_SIMULATED or external_booking_id.startswith("calcom-sim-"):
        log.info("Cal.com SIMULATED cancel id=%s reason=%r", external_booking_id, reason)
        return True

    try:
        identity = await resolve_calendar_identity()
    except MissingChannelCredential as exc:
        # As a CalComError, so the callers that already degrade gracefully on a
        # calendar outage — the voice tool, the visits endpoint — keep doing so
        # instead of turning a missing route into a 500.
        raise CalComError(str(exc)) from exc
    if not identity.credential:
        raise CalComError("Cal.com not configured for this organization.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{s.CALCOM_BASE_URL}/v2/bookings/{external_booking_id}/cancel",
            json={"cancellationReason": reason or "Cancelled from dashboard"},
            headers={
                "Authorization": f"Bearer {identity.credential}",
                "Content-Type": "application/json",
                "cal-api-version": "2024-08-13",
            },
        )
        if resp.status_code >= 400:
            log.error("Cal.com cancel failed: %d %s", resp.status_code, resp.text[:300])
            return False
    return True

"""Cal.com calendar service — list available slots + create / cancel bookings.

When CALENDAR_SIMULATED=true (dev default), all calls work in-memory: slots are
generated for the next 7 weekdays at 10/11/14/15/16 in the requested timezone,
bookings get synthetic `calcom-sim-<uuid>` ids, cancellation flips status only.
Lets us develop the dashboard + tests without a Cal.com account or event type.

When SIMULATED is off, real Cal.com v2 API is hit with CALCOM_API_KEY +
CALCOM_EVENT_TYPE_ID. The v2 shape can shift; if a real piloto fails, the
fix is here (no schema/orchestrator changes needed).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings

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
    busy_starts: set[datetime] | None = None,
) -> list[Slot]:
    """Return weekday slots between [start, end), skipping any in `busy_starts`."""
    busy = busy_starts or set()
    out: list[Slot] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end_day:
        if day.weekday() < 5:  # Mon-Fri only
            for hour in SIMULATED_HOURS_OF_DAY:
                slot_start = day.replace(hour=hour)
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
        return _simulated_slots(start, end, busy_starts=busy_starts)

    if not s.CALCOM_API_KEY or not s.CALCOM_EVENT_TYPE_ID:
        raise CalComError(
            "Cal.com not configured: CALCOM_API_KEY + CALCOM_EVENT_TYPE_ID must be "
            "set, or set CALENDAR_SIMULATED=true for dev."
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{s.CALCOM_BASE_URL}/v2/slots/available",
            params={
                "eventTypeId": s.CALCOM_EVENT_TYPE_ID,
                "startTime": start.isoformat(),
                "endTime": end.isoformat(),
                "timeZone": timezone_name,
            },
            headers={"Authorization": f"Bearer {s.CALCOM_API_KEY}"},
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


async def create_booking(
    *,
    start_time: datetime,
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

    if not s.CALCOM_API_KEY or not s.CALCOM_EVENT_TYPE_ID:
        raise CalComError("Cal.com not configured (CALCOM_API_KEY + CALCOM_EVENT_TYPE_ID required).")
    if not attendee_email:
        raise CalComError("attendee_email is required for real Cal.com bookings.")

    body: dict[str, Any] = {
        "eventTypeId": int(s.CALCOM_EVENT_TYPE_ID),
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
                "Authorization": f"Bearer {s.CALCOM_API_KEY}",
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

    if not s.CALCOM_API_KEY:
        raise CalComError("Cal.com not configured.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{s.CALCOM_BASE_URL}/v2/bookings/{external_booking_id}/cancel",
            json={"cancellationReason": reason or "Cancelled from dashboard"},
            headers={
                "Authorization": f"Bearer {s.CALCOM_API_KEY}",
                "Content-Type": "application/json",
                "cal-api-version": "2024-08-13",
            },
        )
        if resp.status_code >= 400:
            log.error("Cal.com cancel failed: %d %s", resp.status_code, resp.text[:300])
            return False
    return True

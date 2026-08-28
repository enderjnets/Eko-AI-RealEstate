"""Agent scheduling — the only module that talks to Cal.com's schedules.

The product needs to answer "when can *this person* be booked". Cal.com already
answers it, correctly, including the parts that are easy to get wrong: recurring
weekly windows, timezones, daylight saving, buffers, minimum notice and
conflicts against a real calendar. So this module does not compute
availability — it provisions the Cal.com objects that own it, reads them back,
and writes them. `agent_calendars` stores the link, never the hours.

**Every endpoint here wants a different `cal-api-version` header, and the wrong
one is rejected.** Measured against the live API on 2026-08-27, not guessed:

    /v2/schedules      -> 2024-06-11
    /v2/event-types    -> 2024-06-14
    /v2/bookings       -> 2024-08-13   (in `calendar_cal.py`, not here)

They are named constants next to their calls rather than one module-level value
precisely because they differ; a single "API version" would have to be wrong for
two of the three.

The credential comes from `resolve_calendar_identity()`, the same guard the
booking path uses. That guard exists because a booking writes a lead's name,
email and phone onto a calendar: an organization that resolves to the operator's
own Cal.com key is refused rather than served. Provisioning a *schedule* is a
weaker act than booking, but it is provisioning on that same account — so it
goes through the same door, and an agency without its own credential gets a
clear "not configured" rather than somebody else's calendar.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AgentCalendar, AppointmentActivity
from app.models.agent_calendar import DEFAULT_DURATION_MINUTES
from app.services.channel_identity import (
    MissingChannelCredential,
    resolve_calendar_identity,
)
from app.services.tenant_context import get_org_id

log = logging.getLogger(__name__)

SCHEDULES_API_VERSION = "2024-06-11"
EVENT_TYPES_API_VERSION = "2024-06-14"

# Cal.com names days in English, capitalised, and rejects anything else. Ours is
# the same order Python's `weekday()` uses, so index 0 is Monday in both.
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

# What each activity is called where a person can see it. Not derived from the
# enum name: "open_house" is not a label.
ACTIVITY_LABELS: dict[AppointmentActivity, str] = {
    AppointmentActivity.SHOWING: "Property showing",
    AppointmentActivity.VALUATION: "Home valuation",
    AppointmentActivity.CALL: "Consultation call",
    AppointmentActivity.OPEN_HOUSE: "Open house",
}

# Travel is what makes these differ: a call has none, an in-person appointment
# needs the agent to get across town afterwards.
AFTER_BUFFER_MINUTES: dict[AppointmentActivity, int] = {
    AppointmentActivity.SHOWING: 30,
    AppointmentActivity.VALUATION: 30,
    AppointmentActivity.CALL: 0,
    AppointmentActivity.OPEN_HOUSE: 30,
}

# Nobody should be able to drop an appointment on an agent with no notice. Four
# hours for anything that needs travel; one for a call.
MIN_NOTICE_MINUTES: dict[AppointmentActivity, int] = {
    AppointmentActivity.SHOWING: 240,
    AppointmentActivity.VALUATION: 240,
    AppointmentActivity.CALL: 60,
    AppointmentActivity.OPEN_HOUSE: 240,
}

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class CalComScheduleError(RuntimeError):
    """Cal.com refused, or answered in a shape we do not recognise."""


@dataclass(frozen=True)
class Window:
    """One weekly window: these days, from this time to this time.

    Times are wall-clock strings in the schedule's own timezone, exactly as
    Cal.com stores them. Deliberately not `datetime.time`: the value never takes
    part in arithmetic here, and parsing it into a type that implies a date is
    how a timezone gets applied twice.
    """

    days: tuple[int, ...]  # 0 = Monday, matching `date.weekday()`
    start: str  # "HH:MM"
    end: str  # "HH:MM"


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def validate_windows(windows: list[Window]) -> None:
    """Reject what Cal.com would accept and a human would not mean.

    Cal.com is permissive here — it will take a window that ends before it
    starts, or two that overlap — and the result is availability nobody can
    explain. Refusing at our door means the agent sees "10:00 is after 12:00"
    instead of an empty day they cannot account for.
    """
    if not windows:
        return  # An empty list is "not available", which is a real answer.
    if len(windows) > 20:
        raise ValueError("too many windows: at most 20 per activity")

    per_day: dict[int, list[tuple[int, int]]] = {}
    for w in windows:
        if not w.days:
            raise ValueError("a window must name at least one day")
        for day in w.days:
            if day not in range(7):
                raise ValueError(f"day out of range: {day}")
        for value in (w.start, w.end):
            if not _TIME.match(value):
                raise ValueError(f"time must be HH:MM in 24-hour form, got {value!r}")
        if _minutes(w.start) >= _minutes(w.end):
            raise ValueError(f"window ends before it starts: {w.start}-{w.end}")
        for day in w.days:
            per_day.setdefault(day, []).append((_minutes(w.start), _minutes(w.end)))

    for day, spans in per_day.items():
        spans.sort()
        for (_, prev_end), (next_start, _) in zip(spans, spans[1:], strict=False):
            if next_start < prev_end:
                raise ValueError(f"overlapping windows on {WEEKDAYS[day]}")


def undeliverable_reason() -> str | None:
    """Why no attempt can work, or None if one might.

    The distinction the `ops_alert` pattern exists for: "this attempt failed"
    is worth retrying, "nothing is configured" is worth telling a person. A UI
    that shows a spinner forever because CALCOM_API_KEY is empty is the failure
    this prevents.
    """
    s = get_settings()
    if s.CALENDAR_SIMULATED:
        return "the calendar is in simulated mode (CALENDAR_SIMULATED=true)"
    if not s.CALCOM_API_KEY:
        return "no Cal.com API key is configured"
    return None


async def _credential() -> str:
    identity = await resolve_calendar_identity()
    if not identity.credential:
        raise MissingChannelCredential(
            "this organization has no Cal.com credential, so an agent schedule "
            "cannot be provisioned on it"
        )
    return identity.credential


async def _call(
    method: str,
    path: str,
    *,
    api_version: str,
    json: dict | None = None,
) -> dict:
    """One request to Cal.com, with the version header this path needs."""
    s = get_settings()
    token = await _credential()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.request(
            method,
            f"{s.CALCOM_BASE_URL}{path}",
            json=json,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "cal-api-version": api_version,
            },
        )
    if resp.status_code >= 400:
        # `resp.text` can carry the request echo; truncate rather than log a
        # body that might contain the key.
        log.error("Cal.com %s %s failed: %d %s", method, path, resp.status_code, resp.text[:300])
        raise CalComScheduleError(f"Cal.com {method} {path} → HTTP {resp.status_code}")
    payload = resp.json()
    if payload.get("status") != "success":
        raise CalComScheduleError(f"Cal.com {method} {path} → {str(payload)[:200]}")
    return payload.get("data") or {}


# ── Provisioning ─────────────────────────────────────────────────────────────


def _schedule_name(email: str, activity: AppointmentActivity) -> str:
    """Derived, never random: a retry after a partial failure has to be able to
    recognise what it already created."""
    return f"{email} — {ACTIVITY_LABELS[activity]}"


def _slug(email: str, activity: AppointmentActivity) -> str:
    local = email.split("@", 1)[0]
    safe = re.sub(r"[^a-z0-9]+", "-", local.lower()).strip("-") or "agent"
    return f"{safe}-{activity.value.replace('_', '-')}"


async def ensure_calendar(
    db: AsyncSession,
    email: str,
    activity: AppointmentActivity,
    *,
    timezone_name: str,
) -> AgentCalendar:
    """The row and its Cal.com objects, creating whatever is missing.

    Safe to call on every page load. Idempotency has two layers, and both are
    needed: `uq_agent_calendar` stops a second row, and the schedule/event-type
    ids already on the row stop a second Cal.com object. A partially provisioned
    row — schedule created, event type not — is resumed rather than restarted,
    which is why the two ids are stored and checked separately.
    """
    org_id = get_org_id()
    row = (
        await db.execute(
            select(AgentCalendar).where(
                AgentCalendar.email == email, AgentCalendar.activity == activity
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AgentCalendar(
            org_id=org_id,
            email=email,
            activity=activity,
            duration_minutes=DEFAULT_DURATION_MINUTES[activity],
        )
        db.add(row)
        await db.flush()

    if row.calcom_schedule_id is None:
        data = await _call(
            "POST",
            "/v2/schedules",
            api_version=SCHEDULES_API_VERSION,
            json={
                "name": _schedule_name(email, activity),
                "timeZone": timezone_name,
                "isDefault": False,
                # Starts empty on purpose. A default of "weekdays 9-5" would be
                # us inventing this person's working hours and then showing them
                # back as if they had said so.
                "availability": [],
            },
        )
        row.calcom_schedule_id = str(data.get("id") or "")
        if not row.calcom_schedule_id:
            raise CalComScheduleError("Cal.com created a schedule with no id")

    if row.calcom_event_type_id is None:
        data = await _call(
            "POST",
            "/v2/event-types",
            api_version=EVENT_TYPES_API_VERSION,
            json={
                "title": f"{ACTIVITY_LABELS[activity]} — {email}",
                "slug": _slug(email, activity),
                "lengthInMinutes": row.duration_minutes,
                "scheduleId": int(row.calcom_schedule_id),
                "beforeEventBuffer": 0,
                "afterEventBuffer": AFTER_BUFFER_MINUTES[activity],
                "minimumBookingNotice": MIN_NOTICE_MINUTES[activity],
                # A call is the only one that is not at an address.
                "locations": (
                    [{"type": "integration", "integration": "cal-video"}]
                    if activity == AppointmentActivity.CALL
                    else [
                        {
                            "type": "address",
                            "address": "At the property - address in the appointment invitation",
                            "public": True,
                        }
                    ]
                ),
            },
        )
        row.calcom_event_type_id = str(data.get("id") or "")
        if not row.calcom_event_type_id:
            raise CalComScheduleError("Cal.com created an event type with no id")

    return row


# ── Reading and writing the hours ────────────────────────────────────────────


def _to_windows(availability: list[dict]) -> list[Window]:
    out: list[Window] = []
    for entry in availability or []:
        names = entry.get("days") or []
        days = tuple(WEEKDAYS.index(n) for n in names if n in WEEKDAYS)
        start, end = entry.get("startTime"), entry.get("endTime")
        if days and isinstance(start, str) and isinstance(end, str):
            out.append(Window(days=days, start=start[:5], end=end[:5]))
    return out


def _from_windows(windows: list[Window]) -> list[dict]:
    return [
        {
            "days": [WEEKDAYS[d] for d in sorted(set(w.days))],
            "startTime": w.start,
            "endTime": w.end,
        }
        for w in windows
    ]


async def get_windows(row: AgentCalendar) -> list[Window]:
    if not row.calcom_schedule_id:
        return []
    data = await _call(
        "GET",
        f"/v2/schedules/{row.calcom_schedule_id}",
        api_version=SCHEDULES_API_VERSION,
    )
    return _to_windows(data.get("availability") or [])


async def set_windows(
    row: AgentCalendar, windows: list[Window], *, timezone_name: str
) -> list[Window]:
    """Replace this activity's weekly windows. Returns what Cal.com stored.

    Returning the stored value rather than the submitted one is the point: if
    Cal.com normalises or drops something, the agent sees what is actually in
    force instead of what they typed.
    """
    validate_windows(windows)
    if not row.calcom_schedule_id:
        raise CalComScheduleError("this calendar has no Cal.com schedule yet")
    data = await _call(
        "PATCH",
        f"/v2/schedules/{row.calcom_schedule_id}",
        api_version=SCHEDULES_API_VERSION,
        json={"timeZone": timezone_name, "availability": _from_windows(windows)},
    )
    return _to_windows(data.get("availability") or [])

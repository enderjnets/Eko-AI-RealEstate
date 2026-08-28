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

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select
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


def _minutes(hhmm: str, *, as_end: bool = False) -> int:
    """Minutes past midnight. As an END, "00:00" means the end of the day.

    Cal.com writes a shift that runs to midnight as `endTime "00:00:00"`, so
    reading one back and saving it unchanged used to fail our own validation
    with "ends before it starts" — the agent could not re-save hours they had
    not touched. And an evening shift simply could not be expressed except as
    23:59.
    """
    hours, minutes = hhmm.split(":")
    total = int(hours) * 60 + int(minutes)
    return 24 * 60 if (as_end and total == 0) else total


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
        if _minutes(w.start) >= _minutes(w.end, as_end=True):
            raise ValueError(f"window ends before it starts: {w.start}-{w.end}")
        # `set`: the schema allows [1, 1], and counting Tuesday twice reported
        # a window as overlapping itself — a true statement about a list and a
        # useless message to the person who typed one day.
        for day in set(w.days):
            per_day.setdefault(day, []).append(
                (_minutes(w.start), _minutes(w.end, as_end=True))
            )

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
    try:
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
    except httpx.HTTPError as exc:
        # A timeout is an expected outcome, not an exception nobody thought
        # about: this client sets one. Left as httpx it escaped every caller's
        # `except CalComScheduleError`, so the request 500'd and — worse — the
        # Cal.com object it had just created was orphaned while its row rolled
        # back, so the retry made another one.
        raise CalComScheduleError(f"Cal.com {method} {path} did not answer: {exc}") from exc
    if resp.status_code >= 400:
        # `resp.text` can carry the request echo; truncate rather than log a
        # body that might contain the key.
        log.error("Cal.com %s %s failed: %d %s", method, path, resp.status_code, resp.text[:300])
        raise CalComScheduleError(f"Cal.com {method} {path} → HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise CalComScheduleError(f"Cal.com {method} {path} → not JSON") from exc
    if payload.get("status") != "success":
        raise CalComScheduleError(f"Cal.com {method} {path} → {str(payload)[:200]}")
    return payload.get("data") or {}


# ── Provisioning ─────────────────────────────────────────────────────────────


def _schedule_name(email: str, activity: AppointmentActivity) -> str:
    """Derived rather than random, so a human reading the Cal.com account can
    tell whose schedule this is.

    An earlier version of this docstring claimed the name let "a retry after a
    partial failure recognise what it already created". That was false — nothing
    ever lists schedules by name — and an audit caught it. What actually makes a
    retry safe is the id stored on the row; what remains unhandled is an object
    created in Cal.com whose row never committed. Those are orphans, they are
    inert (nothing books against a schedule no row names), and cleaning them up
    is a manual job in the Cal.com UI. Said plainly rather than implied away.
    """
    return f"{email} — {ACTIVITY_LABELS[activity]}"


def _slug(email: str, activity: AppointmentActivity) -> str:
    """Readable, and unique per full address.

    The local part alone is not injective, and an audit proved the collision:
    `natalia@gmail.com` and `natalia@remaxdenver.com` both produced
    `natalia-showing`, as did `Natalia.Perez@x` and `natalia-perez@y`. Two
    colleagues of the same agency would then fight over one Cal.com slug — and
    since a rejected `POST /v2/event-types` leaves the row with no event type
    id, every retry would fail the same way: a permanent 502 for the second
    person. The digest is short, stable, and derived from the WHOLE address.
    """
    local = email.split("@", 1)[0]
    safe = re.sub(r"[^a-z0-9]+", "-", local.lower()).strip("-") or "agent"
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:6]
    return f"{safe}-{digest}-{activity.value.replace('_', '-')}"


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
            # Off until the person saves real hours. Provisioning happens on
            # page LOAD, and a freshly provisioned schedule is deliberately
            # empty — so an active row here would make `pick_agent` prefer an
            # empty calendar over the agency default, and the assistant would
            # offer NO hours to callers because somebody merely opened a page.
            active=False,
        )
        db.add(row)
        await db.flush()

    # `not`, not `is None`: an empty string must also mean "not done yet".
    if not row.calcom_schedule_id:
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
        schedule_id = str(data.get("id") or "")
        if not schedule_id:
            # Never write the empty string. `read_my_availability` commits on
            # this error on purpose, to keep partial provisioning — so a "" here
            # would be persisted, and the resume guard below (`if not ...`) once
            # read `is None`, which "" is not. The row was then skipped forever:
            # `int("")` raised ValueError, which is not CalComScheduleError, and
            # every later request 500'd with no way back but a manual UPDATE.
            raise CalComScheduleError("Cal.com created a schedule with no id")
        row.calcom_schedule_id = schedule_id

    if not row.calcom_event_type_id:
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
        event_type_id = str(data.get("id") or "")
        if not event_type_id:
            raise CalComScheduleError("Cal.com created an event type with no id")
        row.calcom_event_type_id = event_type_id

    return row


# ── Reading and writing the hours ────────────────────────────────────────────


def _to_windows(availability: list[dict]) -> list[Window]:
    out: list[Window] = []
    for entry in availability or []:
        names = entry.get("days") or []
        unknown = [n for n in names if n not in WEEKDAYS]
        if unknown:
            # Silence here loses hours twice over: the window is not shown, and
            # the next save — which REPLACES the whole schedule — deletes it
            # from Cal.com. At least leave a trace.
            log.warning("Cal.com returned day names we do not know: %s", unknown)
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


# ── Who takes this kind of appointment ───────────────────────────────────────


@dataclass(frozen=True)
class BookingTarget:
    """Whose appointment this is, and which Cal.com event type owns the hours.

    Both None means "nobody has declared this activity yet", and the caller
    falls back to the global `CALCOM_EVENT_TYPE_ID` — the behaviour before agent
    scheduling existed. That fallback is deliberate: turning this feature on
    must not stop bookings for an agency that has not filled it in.
    """

    agent_email: str | None = None
    event_type_id: str | None = None


async def pick_agent(db: AsyncSession, activity: AppointmentActivity) -> BookingTarget:
    """The agent who takes this activity, and their event type.

    Today one person is bookable, which makes the rule look like an accident
    waiting to be written. It is not deferred: with two or more configured
    agents this picks the one carrying the fewest upcoming appointments, and a
    test fixes that behaviour so enabling the second agent is a data change, not
    a code change. The owner asked for exactly that — "por ahora solo Natalia,
    pero el sistema debe ser escalable".

    Only rows that are `active` and actually provisioned count: a row whose
    Cal.com event type is missing cannot be booked on, and offering hours
    against it would promise a slot nothing can take.
    """
    from app.models import Visit, VisitStatus

    rows = (
        await db.execute(
            select(AgentCalendar).where(
                AgentCalendar.activity == activity,
                AgentCalendar.active.is_(True),
                AgentCalendar.calcom_event_type_id.isnot(None),
            )
        )
    ).scalars().all()
    rows = [r for r in rows if r.calcom_event_type_id]
    if not rows:
        return BookingTarget()
    if len(rows) == 1:
        return BookingTarget(rows[0].email, rows[0].calcom_event_type_id)

    now = datetime.now(UTC)
    counts = dict(
        (
            await db.execute(
                select(Visit.assigned_email, func.count())
                .where(
                    Visit.assigned_email.in_([r.email for r in rows]),
                    Visit.scheduled_at >= now,
                    Visit.status.in_((VisitStatus.SCHEDULED, VisitStatus.CONFIRMED)),
                )
                .group_by(Visit.assigned_email)
            )
        ).all()
    )
    # `email` as the tiebreak, not insertion order: two agents with the same
    # load must resolve the same way on every call, or the same lead gets a
    # different agent for the slots they were offered and the one they book.
    chosen = min(rows, key=lambda r: (counts.get(r.email, 0), r.email))
    return BookingTarget(chosen.email, chosen.calcom_event_type_id)


async def pick_agent_safely(activity: AppointmentActivity) -> BookingTarget:
    """`pick_agent` on a throwaway session, so a failure cannot poison anyone.

    The obvious pattern — call `pick_agent(db, ...)` with the request's session
    inside try/except — existed in three copies and an audit proved all three
    broke their own promise. A failed statement aborts the shared transaction:
    the except returns the fallback, and the very NEXT statement on that session
    dies with `InFailedSQLTransactionError`. On the panel that was a 500, on the
    phone the call dropped, in chat the lead got no reply — precisely in the
    deploy-before-migrate window where the fallback matters most. A plain
    rollback was no fix either: the voice lane has a freshly flushed,
    uncommitted lead at that point, and rollback would erase it.

    A private session makes the failure mode local. The org travels with it:
    tenant identity is a ContextVar read at transaction begin, so a session
    opened here inherits the caller's scope (same mechanism the whole RLS
    layer rests on).
    """
    from app.db.base import get_session_factory

    try:
        async with get_session_factory()() as own:
            return await pick_agent(own, activity)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not resolve the agent for %s: %s", activity.value, exc)
        return BookingTarget()


def activity_for_lead(lead) -> AppointmentActivity:
    """What kind of appointment this person is actually asking for.

    A seller and a buyer do not want the same meeting. `LeadIntent.VALUATION` is
    somebody asking what their house is worth, and until now the system booked
    them a buyer's showing — the wrong length, the wrong hours, and a calendar
    entry that told the agent the wrong thing to prepare. This mapping is the
    single place that decision is made.

    Anything else, including a lead created moments ago whose intent has not
    been classified yet, is a showing. Written down rather than left implicit:
    a caller who turns out to be a seller keeps the showing that was already
    booked, and correcting the kind of an existing appointment is another
    round's work.
    """
    from app.models.lead import LeadIntent

    intent = getattr(lead, "intent", None)
    if intent == LeadIntent.VALUATION:
        return AppointmentActivity.VALUATION
    return AppointmentActivity.SHOWING

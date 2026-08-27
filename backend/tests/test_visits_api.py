"""Visits API E2E — slots / book / list / cancel (against live DB, simulated Cal.com)."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — visits API needs live Postgres")
    return url


async def _delete_events_on(database_url: str, day: str) -> None:
    """Clear this suite's own day so a stale row cannot masquerade as a bug."""
    from sqlalchemy import text as _text

    engine = create_async_engine(database_url, echo=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                _text("DELETE FROM visits WHERE scheduled_at::date = :d"),
                {"d": datetime.fromisoformat(day).date()},
            )
    finally:
        await engine.dispose()


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert_lead(database_url: str, phone: str) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Visit Test")
            s.add(lead)
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _cleanup_lead(database_url: str, phone: str) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            row = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_slots_endpoint_returns_weekday_slots(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SLT{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.get(f"/api/v1/leads/{lead_id}/calendar/slots?days=7")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["days"] == 7
        assert len(body["slots"]) > 0
        # All returned starts must be on weekdays (Mon-Fri).
        for slot in body["slots"]:
            d = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
            assert d.weekday() < 5
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_slots_lead_not_found_returns_404() -> None:
    async with await _http_client() as client:
        r = await client.get("/api/v1/leads/999999999/calendar/slots?days=3")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_book_creates_visit_persists_with_calcom_sim_id(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666BOK{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    start_time = (datetime.now(UTC) + timedelta(days=1)).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        async with await _http_client() as client:
            r = await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={
                    "start_time": start_time.isoformat(),
                    "duration_minutes": 30,
                    "property_address": "Calle Fuencarral 100, Madrid",
                    "notes": "primera visita",
                    "timezone": "Europe/Madrid",
                },
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["lead_id"] == lead_id
        assert body["calendar_provider"] == "calcom"
        assert body["external_booking_id"].startswith("calcom-sim-")
        assert body["status"] == "scheduled"
        assert body["duration_minutes"] == 30
        assert body["property_address"] == "Calle Fuencarral 100, Madrid"
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_list_visits_returns_inserted_one(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666LST{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    start_time = (datetime.now(UTC) + timedelta(days=2)).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        async with await _http_client() as client:
            await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={"start_time": start_time.isoformat(), "timezone": "Europe/Madrid"},
            )
            r = await client.get(f"/api/v1/leads/{lead_id}/visits")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["lead_id"] == lead_id
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_cancel_visit_flips_status_to_cancelled(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CXL{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    start_time = (datetime.now(UTC) + timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        async with await _http_client() as client:
            book = await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={"start_time": start_time.isoformat()},
            )
            visit_id = book.json()["id"]
            cancel = await client.post(
                f"/api/v1/visits/{visit_id}/cancel",
                json={"reason": "cliente reagendó"},
            )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "cancelled"

        # Cancelling again returns 400 (terminal status).
        async with await _http_client() as client:
            second_cancel = await client.post(f"/api/v1/visits/{visit_id}/cancel", json={})
        assert second_cancel.status_code == 400
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_slots_excludes_already_booked_starts(database_url: str) -> None:
    """If lead has a SCHEDULED visit at T, /slots must not return T again."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666BSY{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    # Pick the next weekday 10 AM UTC for predictability.
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    target = (now + timedelta(days=1)).replace(hour=10)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    try:
        async with await _http_client() as client:
            await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={"start_time": target.isoformat(), "timezone": "UTC"},
            )
            r = await client.get(f"/api/v1/leads/{lead_id}/calendar/slots?days=7&timezone=UTC")
        body = r.json()
        slot_starts = {
            datetime.fromisoformat(s["start"].replace("Z", "+00:00")) for s in body["slots"]
        }
        assert target not in slot_starts
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" America/Denver", "America/Denver"),
        ("America/Denver ", "America/Denver"),
        ("  America/Denver  ", "America/Denver"),
    ],
)
def test_a_pasted_timezone_is_trimmed_not_silently_reinterpreted(
    raw: str, expected: str
) -> None:
    """A leading space used to move an appointment six hours.

    `_resolve_wall_clock` swallowed `ZoneInfoNotFoundError` and returned the
    wall clock stamped UTC, so `" America/Denver"` filed a 10:00 showing at
    10:00 UTC — 04:00 in Denver. The response was 201 and the bad string was
    stored beside it. Nothing anywhere said a word, and the realtor would have
    found out when nobody opened the door.

    The irony is that `_resolve_wall_clock`'s own docstring names this exact
    number: "the same 10:00 meant two different instants depending on which
    route wrote it — in Denver, six hours apart".
    """
    from app.api.v1.visits import ManualEventIn

    event = ManualEventIn(
        title="Open house", scheduled_at=datetime(2026, 9, 15, 10, 0), timezone=raw
    )
    assert event.timezone == expected


def test_an_unknown_timezone_is_refused_by_name() -> None:
    """Refused, not defaulted. A wrong zone is a question, not a fact.

    `settings.py` has always validated this field with `ZoneInfo` and returned
    a 400; the same string quietly moved an appointment on this endpoint. One
    product, two answers to one input.
    """
    from app.api.v1.visits import BookingIn, ManualEventIn

    with pytest.raises(ValueError, match="Invented/Zone"):
        ManualEventIn(
            title="Open house",
            scheduled_at=datetime(2026, 9, 15, 10, 0),
            timezone="Invented/Zone",
        )
    with pytest.raises(ValueError, match="Denverr"):
        BookingIn(
            start_time=datetime(2026, 9, 15, 10, 0),
            duration_minutes=30,
            timezone="America/Denverr",
        )


def test_an_empty_timezone_still_means_use_the_office_one() -> None:
    """Omitted and blank must keep meaning "the agency's zone", not an error.

    The refusal above is for a zone that was named and is wrong. A caller who
    names none is asking for the default, which is the documented behaviour of
    both schemas and what every existing client relies on.
    """
    from app.api.v1.visits import ManualEventIn

    for blank in (None, "", "   "):
        event = ManualEventIn(
            title="Team meeting",
            scheduled_at=datetime(2026, 9, 15, 10, 0),
            timezone=blank,
        )
        assert event.timezone is None, blank


def test_a_good_timezone_still_resolves_to_the_right_instant() -> None:
    """The control. Without it the fix could be "reject everything" and pass."""
    from app.api.v1.visits import _resolve_wall_clock

    resolved = _resolve_wall_clock(datetime(2026, 9, 15, 10, 0), "America/Denver")
    # 10:00 Denver in September (MDT, UTC-6) is 16:00 UTC.
    assert resolved == datetime(2026, 9, 15, 16, 0, tzinfo=UTC)


def test_a_broken_office_timezone_is_reported_not_papered_over() -> None:
    """Reaching the resolver with a bad zone now means the ORG's config is bad.

    The schemas refuse a bad zone from the caller, so the only way in is
    `_office_tz` returning something unusable. Falling back to UTC there files
    every appointment six hours out for that agency, silently and forever.
    A 400 naming the value is the only answer that does not invent a time for
    somebody's appointment.
    """
    from fastapi import HTTPException

    from app.api.v1.visits import _resolve_wall_clock

    with pytest.raises(HTTPException) as caught:
        _resolve_wall_clock(datetime(2026, 9, 15, 10, 0), "Not/AZone")
    assert caught.value.status_code == 400
    assert "Not/AZone" in str(caught.value.detail)


def test_an_event_title_of_spaces_is_refused() -> None:
    """`min_length=1` judged the raw string, so "   " was a valid title and the
    entry rendered blank in the diary. Same ordering bug as `RejectIn.reason`."""
    from app.api.v1.visits import ManualEventIn

    with pytest.raises(ValueError, match="title"):
        ManualEventIn(title="   ", scheduled_at=datetime(2026, 9, 15, 10, 0))
    kept = ManualEventIn(title="  Open house  ", scheduled_at=datetime(2026, 9, 15, 10, 0))
    assert kept.title == "Open house"


@pytest.mark.asyncio
async def test_a_pasted_timezone_no_longer_files_the_event_six_hours_early(
    database_url: str,
) -> None:
    """End to end, against Postgres: the number that made this worth fixing.

    Before, `POST /api/v1/visits` with `" America/Denver"` answered **201** and
    stored 10:00 UTC — 04:00 Denver. The realtor saw a confirmation and the
    appointment was on the diary six hours before anyone expected it.

    Asserted on the stored instant rather than on the response body, because
    the response was never the thing that was wrong.
    """
    # Its own day, well clear of every other test's fixtures: the double-booking
    # guard answers 409 for a clash, and a 409 here would look like the timezone
    # bug it is meant to catch. September, so Denver is plainly MDT and no
    # DST edge is in play.
    day = "2028-09-20"
    await _delete_events_on(database_url, day)

    async with await _http_client() as client:
        created = await client.post(
            "/api/v1/visits",
            json={
                "title": "Open house",
                "scheduled_at": f"{day}T10:00:00",
                "duration_minutes": 60,
                "timezone": " America/Denver",
            },
        )
        assert created.status_code == 201, created.text
        stored = datetime.fromisoformat(
            created.json()["scheduled_at"].replace("Z", "+00:00")
        ).astimezone(UTC)
        expected = datetime(2028, 9, 20, 16, 0, tzinfo=UTC)
        # 10:00 Denver in September (MDT, UTC-6) is 16:00 UTC. The bug stored 10:00.
        assert stored == expected, f"filed at {stored}, which is {expected - stored} off"

        # And a zone that is genuinely wrong is refused, not filed anywhere.
        refused = await client.post(
            "/api/v1/visits",
            json={
                "title": "Open house",
                "scheduled_at": f"{day}T14:00:00",
                "timezone": "Invented/Zone",
            },
        )
        assert refused.status_code == 422, refused.text
        assert "Invented/Zone" in refused.text
    await _delete_events_on(database_url, day)


def test_blank_optional_fields_are_stored_as_null_not_empty_string() -> None:
    """Nullable columns take the other rule: blank means absent.

    Found auditing my own change: all three text fields were given the
    trim-only validator, which is right for `title` (NOT NULL in effect, guarded
    by `min_length=1`) and wrong for the other two. It stored "" where the
    schema says "no notes", so asking whether an event has notes meant checking
    `IS NULL` *and* `= ''`. Same split as `settings.py`, applied by inertia
    rather than by looking at the columns.
    """
    from app.api.v1.visits import ManualEventIn

    event = ManualEventIn(
        title="  Open house  ",
        scheduled_at=datetime(2028, 9, 20, 10, 0),
        notes="   ",
        property_address="  ",
    )
    assert event.title == "Open house"
    assert event.notes is None, event.notes
    assert event.property_address is None, event.property_address

    # And real content still survives the trim.
    kept = ManualEventIn(
        title="Open house",
        scheduled_at=datetime(2028, 9, 20, 10, 0),
        notes="  Bring the brochures.  ",
    )
    assert kept.notes == "Bring the brochures."


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("A" * 300, "OSError, [Errno 63] File name too long"),
        ("America", "IsADirectoryError — a tzdata directory, not a zone"),
        ("Etc", "IsADirectoryError — same shape, short enough to look real"),
    ],
)
def test_a_timezone_that_breaks_the_lookup_is_a_422_not_a_500(
    raw: str, why: str
) -> None:
    """The guard must never be worse than no guard, and this one was.

    `ZoneInfo` raises THREE unrelated exception types, not two. The first
    version of `_valid_timezone` caught `ZoneInfoNotFoundError` and `ValueError`
    and let `OSError` through, so these inputs escaped validation entirely and
    FastAPI answered **500**.

    The damning part is the comparison with the code this replaced: before the
    validator existed, `"A" * 300` was a clean **422** from `max_length=50`.
    Adding a `mode="before"` validator moved the check to the wrong side of that
    bound, so a guard written to make bad input safer made this input strictly
    worse — a stack trace where the caller had been getting a field name.

    Parametrised on the reason each one breaks, because "unknown zone" and
    "the lookup itself failed" are different failures that must land alike.
    """
    from app.api.v1.visits import BookingIn, ManualEventIn

    with pytest.raises(ValidationError):
        BookingIn(start_time=datetime(2026, 9, 15, 10, 0), timezone=raw)

    with pytest.raises(ValidationError):
        ManualEventIn(
            title="Open house",
            scheduled_at=datetime(2026, 9, 15, 10, 0),
            timezone=raw,
        )


def test_a_bytes_timezone_is_trimmed_and_validated_like_a_string() -> None:
    """Pydantic coerces bytes to str AFTER a `mode="before"` validator runs.

    So a validator guarding only `isinstance(v, str)` hands the model back the
    raw bytes and the model accepts them — untrimmed and unchecked. Not
    reachable over JSON, which has no byte string. It is here because this repo
    has now written that exact argument into a docstring twice while leaving the
    hole open underneath it; the third time it should fail a test instead.
    """
    from app.api.v1.visits import BookingIn

    booking = BookingIn(
        start_time=datetime(2026, 9, 15, 10, 0), timezone=b" America/Denver"
    )
    assert booking.timezone == "America/Denver"

    with pytest.raises(ValidationError):
        BookingIn(start_time=datetime(2026, 9, 15, 10, 0), timezone=b"Invented/Zone")


@pytest.mark.asyncio
async def test_a_pasted_timezone_does_not_shift_the_offered_hours(
    database_url: str,
) -> None:
    """The reported bug, still live on the GET beside the POST that was fixed.

    `?timezone=%20America/Denver` — one pasted leading space — reached
    `list_available_slots`, whose `except Exception` turns any bad zone into UTC
    with a `log.warning` nobody reads. The slots came back generated in UTC
    while the response echoed the requested zone back in `timezone`, so the
    caller was told these were the office's hours. Measured before the fix:

        America/Denver    -> 2028-09-25T10:00:00-06:00
        ' America/Denver' -> 2028-09-25T10:00:00+00:00

    Six hours, the same number as the booking bug, on the endpoint that feeds
    it. Offering an hour is the same promise as booking one.

    Asserts the OFFSET, not the status code: a 200 with the right shape is
    exactly what the bug already produced.
    """
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666TZD{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            clean = await client.get(
                f"/api/v1/leads/{lead_id}/calendar/slots"
                "?days=3&timezone=America/Denver"
            )
            pasted = await client.get(
                f"/api/v1/leads/{lead_id}/calendar/slots"
                "?days=3&timezone=%20America/Denver%20"
            )
        assert clean.status_code == 200, clean.text
        assert pasted.status_code == 200, pasted.text

        first_clean = datetime.fromisoformat(clean.json()["slots"][0]["start"])
        first_pasted = datetime.fromisoformat(pasted.json()["slots"][0]["start"])
        drift = abs(first_pasted - first_clean)
        assert drift == timedelta(0), (
            f"a pasted space moved the first offered slot by {drift} — "
            f"{first_clean.isoformat()} became {first_pasted.isoformat()}"
        )
        # And the echoed value is the zone actually used, not the raw string.
        assert pasted.json()["timezone"] == "America/Denver"
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_an_unknown_timezone_on_the_slots_endpoint_is_refused(
    database_url: str,
) -> None:
    """A zone we cannot use is a question, not a reason to answer in UTC.

    Covers the lookup-failure shapes too (`"America"` is a tzdata directory),
    which is where the narrow `except` let a 500 through on the sibling POST.
    """
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666TZR{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            for bad in ("Mars/Phobos", "America", "A" * 300):
                r = await client.get(
                    f"/api/v1/leads/{lead_id}/calendar/slots?days=3&timezone={bad}"
                )
                assert r.status_code in (400, 422), f"{bad!r} -> {r.status_code}"
    finally:
        await _cleanup_lead(database_url, phone)

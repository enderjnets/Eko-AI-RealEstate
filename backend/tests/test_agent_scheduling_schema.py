"""The schema behind "when can this person be booked" — proved, not declared.

Following `test_tenant_isolation.py`: none of these assert that a policy *exists*
in the catalogue. A policy row is a declaration, and this repo has paid for the
difference before. Every isolation test here asserts that a hostile query comes
back **empty**, or that a hostile write is **refused** — the behaviour, not the
paperwork.

`agent_calendars` is the first table whose rows are about a *person* rather than
about the agency, so the leak it must not have is specific and worth naming: one
agency being able to read, or overwrite, the working hours of another agency's
realtors.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.base import get_bypass_session_factory, get_engine, get_session_factory
from app.models import AgentCalendar, AppointmentActivity, Visit, VisitStatus
from app.models.agent_calendar import DEFAULT_DURATION_MINUTES
from app.services.tenant_context import org_scope

ORG_A = 1
ORG_B = 2

EMAIL_A = "schema-probe-a@example.com"
EMAIL_B = "schema-probe-b@example.com"


async def _seed(email: str, org_id: int, activity: AppointmentActivity) -> int:
    """Insert straight past RLS, so both orgs have something to leak."""
    async with get_bypass_session_factory()() as db:
        row = AgentCalendar(
            org_id=org_id,
            email=email,
            activity=activity,
            calcom_event_type_id="et-seed",
        )
        db.add(row)
        await db.commit()
        return row.id


async def _cleanup(*emails: str) -> None:
    async with get_bypass_session_factory()() as db:
        for email in emails:
            await db.execute(
                text("DELETE FROM agent_calendars WHERE email = :e"), {"e": email}
            )
        await db.commit()


# ── The instrument itself ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_app_role_cannot_ignore_rls() -> None:
    """Repeated from `test_tenant_isolation` on purpose, not by oversight.

    A superuser ignores RLS even under FORCE, which would turn every assertion
    below green while isolating nothing. If this file is ever run against a
    different DATABASE_URL_APP than that one, its own guard has to travel with
    it — a false green here is invisible.
    """
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    assert row.rolsuper is False, "the app connects as a superuser — RLS is not enforced"
    assert row.rolbypassrls is False, "the app role has BYPASSRLS — RLS is not enforced"


# ── Isolation: reads ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_agency_cannot_read_another_agencys_schedules() -> None:
    await _seed(EMAIL_A, ORG_A, AppointmentActivity.SHOWING)
    await _seed(EMAIL_B, ORG_B, AppointmentActivity.SHOWING)
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                # No WHERE clause on purpose: the forgotten-filter case.
                rows = (await db.execute(select(AgentCalendar))).scalars().all()
        emails = {r.email for r in rows}
        assert EMAIL_B not in emails, "another agency's realtor schedule is visible"
        assert EMAIL_A in emails, "own row disappeared"
        assert {r.org_id for r in rows} <= {ORG_A}
    finally:
        await _cleanup(EMAIL_A, EMAIL_B)


@pytest.mark.asyncio
async def test_an_unset_org_sees_nothing_rather_than_everything() -> None:
    """Default-deny: a background worker that forgets to scope must read zero
    rows, not every agency's calendar."""
    await _seed(EMAIL_A, ORG_A, AppointmentActivity.SHOWING)
    try:
        with org_scope(None):
            async with get_session_factory()() as db:
                rows = (await db.execute(select(AgentCalendar))).scalars().all()
        assert rows == [], f"unset org returned {len(rows)} rows instead of none"
    finally:
        await _cleanup(EMAIL_A)


# ── Isolation: writes ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_agency_cannot_write_a_schedule_into_another() -> None:
    """USING alone filters reads and still permits writes — this is WITH CHECK.

    The damage this prevents is not abstract: an INSERT with somebody else's
    `org_id` would put working hours on a realtor of another agency.
    """
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                db.add(
                    AgentCalendar(
                        org_id=ORG_B,
                        email=EMAIL_B,
                        activity=AppointmentActivity.CALL,
                    )
                )
                with pytest.raises(DBAPIError):
                    await db.commit()
    finally:
        await _cleanup(EMAIL_B)


# ── The constraint that makes provisioning idempotent ────────────────────────


@pytest.mark.asyncio
async def test_the_same_person_cannot_get_two_calendars_for_one_activity() -> None:
    """This UNIQUE is not tidiness, it is the idempotency of provisioning.

    `ensure_calendars` is meant to be safe to call on every page load. Without
    this constraint a retry after a partial failure would create a second
    Cal.com schedule for the same person and activity, and the second one would
    silently win — the realtor would edit hours that nothing books against.
    """
    await _seed(EMAIL_A, ORG_A, AppointmentActivity.SHOWING)
    try:
        async with get_bypass_session_factory()() as db:
            db.add(
                AgentCalendar(
                    org_id=ORG_A,
                    email=EMAIL_A,
                    activity=AppointmentActivity.SHOWING,
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
    finally:
        await _cleanup(EMAIL_A)


@pytest.mark.asyncio
async def test_two_agencies_can_hold_the_same_person() -> None:
    """The `org_id` leg of the UNIQUE, which nothing else exercises.

    An independent audit removed it — `UNIQUE (email, activity)` — and all 1188
    tests stayed green while the schema had a cross-tenant collision in it: the
    second agency's INSERT fails against a row it is not even allowed to see, so
    provisioning breaks *and* the error reveals that another agency already has
    that person. A realtor working for two agencies is ordinary; the leak is not.
    """
    await _seed(EMAIL_A, ORG_A, AppointmentActivity.SHOWING)
    await _seed(EMAIL_A, ORG_B, AppointmentActivity.SHOWING)
    try:
        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(AgentCalendar).where(AgentCalendar.email == EMAIL_A)
                )
            ).scalars().all()
        assert {r.org_id for r in rows} == {ORG_A, ORG_B}, (
            "the same person cannot exist in two agencies — the UNIQUE is "
            "missing its org_id leg and collides across the tenant boundary"
        )
    finally:
        await _cleanup(EMAIL_A)


@pytest.mark.asyncio
async def test_a_row_that_predates_the_column_still_says_what_kind_it_is() -> None:
    """The server default, which the ORM default hides from every other test.

    `Visit(...)` sends `purpose` in the INSERT because the model carries a
    Python default, so the *server* default is never exercised — an audit
    dropped it (`ALTER COLUMN purpose DROP DEFAULT`) and all 1188 tests stayed
    green. That default is the only reason `ADD COLUMN ... NOT NULL` survives a
    non-empty `visits`, and every test and CI database migrates an empty one.
    Measured: with one row present, the same statement without a default fails
    with `column "purpose" ... contains null values`.

    So this inserts the way a pre-migration row effectively arrives — through
    SQL that never mentions the column — and asserts the database fills it.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO visits (org_id, external_booking_id, status, "
                "scheduled_at, duration_minutes, timezone, calendar_provider) "
                "VALUES (:o, :e, 'scheduled', now(), 30, 'UTC', 'calcom')"
            ),
            {"o": ORG_A, "e": "schema-probe-default"},
        )
        await db.commit()
    try:
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT purpose, assigned_email FROM visits "
                        "WHERE external_booking_id = :e"
                    ),
                    {"e": "schema-probe-default"},
                )
            ).one()
        assert row.purpose == "showing", (
            "a row inserted without `purpose` did not get the server default — "
            "migrating a non-empty visits table would fail on NOT NULL"
        )
        assert row.assigned_email is None
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM visits WHERE external_booking_id = :e"),
                {"e": "schema-probe-default"},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_the_same_person_can_hold_one_calendar_per_activity() -> None:
    """The other half of the constraint: four kinds of appointment, one person."""
    try:
        for activity in AppointmentActivity:
            await _seed(EMAIL_A, ORG_A, activity)
        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(AgentCalendar).where(AgentCalendar.email == EMAIL_A)
                )
            ).scalars().all()
        assert {r.activity for r in rows} == set(AppointmentActivity)
    finally:
        await _cleanup(EMAIL_A)


# ── Defaults that other code will lean on ────────────────────────────────────


@pytest.mark.asyncio
async def test_a_visit_records_what_kind_of_appointment_it_is() -> None:
    """`purpose` is NOT NULL with a default, so no visit can be of unknown kind.

    Every existing row was a property showing — the only thing the product could
    book — so the server default is a true statement about them, not a guess.
    """
    async with get_bypass_session_factory()() as db:
        visit = Visit(
            org_id=ORG_A,
            external_booking_id="schema-probe-visit",
            status=VisitStatus.SCHEDULED,
            scheduled_at=datetime.now(UTC),
        )
        db.add(visit)
        await db.commit()
        visit_id = visit.id
    try:
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(Visit).where(Visit.id == visit_id))
            ).scalar_one()
            assert row.purpose == AppointmentActivity.SHOWING
            assert row.assigned_email is None, "unassigned must be expressible"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM visits WHERE external_booking_id = :e"),
                {"e": "schema-probe-visit"},
            )
            await db.commit()


def test_every_activity_has_a_starting_length() -> None:
    """Imported, not copied: a fifth activity added to the enum without a length
    would otherwise provision a calendar with no duration and fail at booking
    time, far from the cause."""
    assert set(DEFAULT_DURATION_MINUTES) == set(AppointmentActivity)
    assert all(v > 0 for v in DEFAULT_DURATION_MINUTES.values())

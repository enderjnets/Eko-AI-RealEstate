"""Resources every agency touches, and the ones that only look shared.

Eighteen audit rounds went through the inbound webhooks, the platform routes
and the credential model. These cover what those rounds did not: the calendar,
the MLS feed, and the slot arithmetic — where a defect is not a broken boundary
but a client's phone number appearing on somebody else's screen.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.channel_route import CHANNEL_CALENDAR, normalize_destination
from app.models.organization import DEFAULT_ORG_ID
from app.services import tenant_resolver
from app.services.channel_identity import resolve_outbound_identity
from app.services.tenant_context import org_scope

AGENCY = 930


async def _make_agency(**route: object) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, 'Cal Agency', 'cal-agency', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": AGENCY},
        )
        if route:
            dest = normalize_destination(str(route.pop("_dest", "77")))
            cols = ["org_id", "channel", "destination", *route]
            await db.execute(
                text(
                    f"INSERT INTO channel_routes ({', '.join(cols)}) "
                    f"VALUES ({', '.join(':' + c for c in cols)})"
                ),
                {
                    "org_id": AGENCY,
                    "channel": CHANNEL_CALENDAR,
                    "destination": dest,
                    **route,
                },
            )
        await db.commit()
    tenant_resolver.reset_cache()


async def _cleanup() -> None:
    """Remove everything this module creates, in dependency order.

    `follow_ups` and `agent_settings` were missing from the original list, so a
    single reminder row made `DELETE FROM leads` fail on its foreign key — and
    because it is all one transaction, the whole cleanup rolled back. The next
    run then found a lead it merged with, and a test that passed alone failed
    in the suite.
    """
    async with get_bypass_session_factory()() as db:
        for table in (
            "follow_ups",
            "messages",
            "conversations",
            "visits",
            "leads",
            "agent_settings",
            "channel_routes",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE org_id = :i"), {"i": AGENCY}
            )
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": AGENCY})
        await db.commit()
    tenant_resolver.reset_cache()


async def _make_empty_database(name: str) -> None:
    """A real database with no schema in it, for the first-boot test."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        "postgresql+asyncpg://eko:eko_local_pass@localhost:5434/postgres",
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _drop_database(name: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        "postgresql+asyncpg://eko:eko_local_pass@localhost:5434/postgres",
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    except Exception:  # noqa: BLE001 — cleanup must not fail the run
        pass
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_an_agency_books_onto_its_own_calendar(monkeypatch) -> None:
    """Every channel was given per-agency credentials; the calendar was not.

    So a booking made by agency B landed on the operator's Cal.com with the
    lead's name, email and phone as an attendee — visible to whoever else uses
    that calendar — and B's bookings blanked out slots for everyone. It never
    showed up in dev because CALENDAR_SIMULATED short-circuits before the HTTP
    call.
    """
    from app.config import get_settings

    monkeypatch.setenv("CALCOM_KEY_AGENCY", "their-cal-key")
    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "the-operators-cal-key")
    monkeypatch.setattr(get_settings(), "CALCOM_EVENT_TYPE_ID", 11)
    await _make_agency(credential_ref="CALCOM_KEY_AGENCY", _dest="42")
    try:
        with org_scope(AGENCY):
            theirs = await resolve_outbound_identity(CHANNEL_CALENDAR)
        assert theirs.credential == "their-cal-key"
        assert theirs.destination == "42"

        # And the single-customer install is untouched.
        with org_scope(DEFAULT_ORG_ID):
            ours = await resolve_outbound_identity(CHANNEL_CALENDAR)
        assert ours.credential == "the-operators-cal-key"
        assert ours.destination == "11"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_calendar_refuses_rather_than_booking_onto_the_operators(
    monkeypatch,
) -> None:
    """With no key at all there is nothing to book against, and guessing means
    putting a stranger's client on the operator's calendar."""
    from app.config import get_settings
    from app.services.calendar_cal import CalComError, create_booking

    monkeypatch.setattr(get_settings(), "CALENDAR_SIMULATED", False)
    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "")
    await _make_agency()
    try:
        with org_scope(AGENCY), pytest.raises(CalComError):
            await create_booking(
                start_time=datetime.now(UTC) + timedelta(days=1),
                attendee_name="A Lead",
                attendee_email="lead@x.test",
                attendee_phone="+13035550000",
                timezone_name="America/Denver",
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_two_leads_are_not_offered_the_same_half_hour() -> None:
    """A realtor's diary belongs to the agency, not to whoever is asking.

    De-conflicting per lead offered the same slot to two different leads and
    let both bookings succeed, sending one realtor to two houses at once.
    """
    from app.api.v1.visits import _busy_starts
    from app.models import Lead, Visit
    from app.models.visit import VisitStatus

    when = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
    await _make_agency()
    try:
        with org_scope(AGENCY):
            async with get_session_factory()() as db:
                first = Lead(phone="+13035551000")
                second = Lead(phone="+13035552000")
                db.add_all([first, second])
                await db.flush()
                db.add(
                    Visit(
                        lead_id=first.id,
                        scheduled_at=when,
                        status=VisitStatus.SCHEDULED,
                        external_booking_id="cal-busy-1",
                    )
                )
                await db.commit()

            async with get_session_factory()() as db:
                busy = await _busy_starts(
                    db,
                    since=when - timedelta(days=1),
                    until=when + timedelta(days=1),
                )
        assert when in busy, (
            "the other lead's booking was invisible, so both would be offered it"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_upgrade_path_does_not_hand_agency_b_the_operators_calendar(
    monkeypatch,
) -> None:
    """The round-19 fix only covered a fresh install.

    Every pilot being upgraded already has CALCOM_API_KEY in its `.env`, and the
    global fallback answered with it — so onboarding agency B before creating
    their calendar route put their lead's name, email and phone on the
    operator's calendar anyway. Falling back is right for one customer and
    wrong the moment there are two.
    """
    from app.config import get_settings
    from app.services.channel_identity import (
        MissingChannelCredential,
        resolve_calendar_identity,
    )

    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "the-operators-cal-key")
    monkeypatch.setattr(get_settings(), "CALCOM_EVENT_TYPE_ID", 11)
    await _make_agency()  # active, routable, and no calendar route
    try:
        with org_scope(AGENCY), pytest.raises(MissingChannelCredential):
            await resolve_calendar_identity()

        # The single-customer install still books on the configured calendar.
        with org_scope(DEFAULT_ORG_ID):
            mine = await resolve_calendar_identity()
        assert mine.credential == "the-operators-cal-key"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_tenant_cannot_spend_the_operators_discovery_credit() -> None:
    """Outscraper, Yelp and SerpApi are billed to the operator and metered per
    install, not per agency, so an agency member looping /discovery/search
    drains the credit every other agency's replies depend on."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        for path, body in (
            ("/api/v1/discovery/search", {"query": "realtors denver"}),
            ("/api/v1/discovery/enrich-pending", {}),
            # `/import` was left open when the other four were gated. It writes
            # unscored leads that the enrichment worker then sweeps and runs
            # through the LLM, so it spends the shared budget one step removed.
            ("/api/v1/discovery/import", {"business_ids": [1]}),
            ("/api/v1/discovery/enrich/1", {}),
        ):
            resp = await client.post(path, json=body)
            assert resp.status_code in (401, 403), (
                f"{path} answered {resp.status_code} to an unauthenticated caller"
            )


@pytest.mark.asyncio
async def test_an_event_type_without_a_key_is_not_a_calendar_of_ones_own(
    monkeypatch,
) -> None:
    """The second wrong question in two rounds.

    Asking "does this org have a calendar row" looked right, but a row carrying
    only an event type id is a legal onboarding shape — `platform.py` exempts
    calendar from the must-name-both-refs rule — and the resolver fills its
    credential from the operator's key. So the route existed, the guard passed,
    and the booking still landed on the operator's calendar.
    """
    from app.config import get_settings
    from app.services.channel_identity import (
        MissingChannelCredential,
        resolve_calendar_identity,
    )

    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "the-operators-cal-key")
    monkeypatch.setattr(get_settings(), "CALCOM_EVENT_TYPE_ID", 11)
    await _make_agency(_dest="42")  # a route, but no credential_ref
    try:
        with org_scope(AGENCY), pytest.raises(MissingChannelCredential):
            await resolve_calendar_identity()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_cancelling_survives_a_calendar_that_is_not_configured() -> None:
    """`list_slots` and `book_slot` degraded on CalComError; cancel did not, so
    a missing calendar route turned a cancellation into a 500 and left the
    visit SCHEDULED — the realtor still drives to the house."""
    import app.api.v1.visits as visits_mod
    from app.models.visit import VisitStatus
    from app.services.calendar_cal import CalComError

    async def _boom(*a: object, **k: object) -> bool:
        raise CalComError("no calendar for this organization")

    visit = SimpleNamespace(
        id=1,
        status=VisitStatus.SCHEDULED,
        calendar_provider="calcom",
        external_booking_id="cal-1",
        notes=None,
    )

    class _Result:
        def scalar_one_or_none(self) -> object:
            return visit

    class _Db:
        async def execute(self, *a: object, **k: object) -> _Result:
            return _Result()

        async def commit(self) -> None:  # pragma: no cover — must not be reached
            raise AssertionError("committed a cancellation the calendar refused")

    with patch.object(visits_mod, "cancel_booking", _boom):
        with pytest.raises(HTTPException) as caught:
            await visits_mod.cancel_visit(
                visit_id=1, body=None, local_only=False, db=_Db()
            )
    assert caught.value.status_code == 503
    assert visit.status is VisitStatus.SCHEDULED, (
        "the visit was left cancelled locally while the booking still stands"
    )


def test_startup_refuses_only_when_isolation_is_actually_missing() -> None:
    """The guard has to fire on the dangerous states and on nothing else.

    Verified live against the real database as well: pointing DATABASE_URL_APP
    at the owner role boots with one agency and refuses with two. This pins the
    decision so a later change cannot quietly widen or silence it.
    """
    from app.main import _must_refuse_to_serve

    # RLS enforced: never refuse, whatever the count says.
    assert not _must_refuse_to_serve(False, [1, 2, 3], True)
    assert not _must_refuse_to_serve(False, [], False)
    # RLS off, one customer: nobody to leak to, so it may run — loudly.
    assert not _must_refuse_to_serve(True, [1], True)
    # RLS off and more than one agency: the whole point.
    assert _must_refuse_to_serve(True, [1, 3], True)
    # RLS off and the count unreadable. An empty list used to look like "one
    # agency" and silenced this, which is exactly what an unreadable count
    # means: the bypass session came back empty because it is not bypassing.
    assert _must_refuse_to_serve(True, [], False)


@pytest.mark.asyncio
async def test_a_route_naming_the_operators_own_key_is_not_a_calendar_of_ones_own(
    monkeypatch,
) -> None:
    """Fourth attempt at one condition, and the first that says it.

    Every earlier guard was a proxy something legal could satisfy. This is the
    one that survived: an agency whose `credential_ref` points at a variable
    holding the operator's key — the documented global one, or a copy under
    another name — resolves to the operator's calendar, and the guard has to
    notice that whatever the route looks like.
    """
    from app.config import get_settings
    from app.services.channel_identity import (
        MissingChannelCredential,
        resolve_calendar_identity,
    )

    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "the-operators-cal-key")
    monkeypatch.setattr(get_settings(), "CALCOM_EVENT_TYPE_ID", 11)
    # A copy of the operator's key under an agency-looking name. The route is
    # well-formed, the ref is unique to this agency, the variable is set.
    monkeypatch.setenv("CALCOM_KEY_ACME", "the-operators-cal-key")
    await _make_agency(credential_ref="CALCOM_KEY_ACME", _dest="42")
    try:
        with org_scope(AGENCY), pytest.raises(MissingChannelCredential):
            await resolve_calendar_identity()

        # And a genuinely different key is accepted.
        monkeypatch.setenv("CALCOM_KEY_ACME", "acmes-own-cal-key")
        with org_scope(AGENCY):
            theirs = await resolve_calendar_identity()
        assert theirs.credential == "acmes-own-cal-key"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_second_agency_is_refused_even_while_it_looks_like_the_only_one(
    monkeypatch,
) -> None:
    """The previous guard asked how many agencies were active first, and that
    count is cached for fifteen seconds. A stale answer meant "one customer,
    fall back" — booking on the operator's calendar rather than refusing. The
    count is gone from this path: anything past the default organization brings
    its own calendar, cache or no cache."""
    from app.config import get_settings
    from app.services import tenant_resolver
    from app.services.channel_identity import (
        MissingChannelCredential,
        resolve_calendar_identity,
    )

    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "the-operators-cal-key")
    monkeypatch.setattr(get_settings(), "CALCOM_EVENT_TYPE_ID", 11)
    await _make_agency()
    # A cache that has not yet seen the new agency, exactly as it looks in
    # the fifteen seconds after onboarding.
    tenant_resolver._cache = (1e18, {DEFAULT_ORG_ID: "active"})
    try:
        with org_scope(AGENCY), pytest.raises(MissingChannelCredential):
            await resolve_calendar_identity()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visit_is_never_stuck_uncancellable() -> None:
    """`cancel` is the only route that changes a visit's status, and round 21
    made it 503 whenever the calendar is unreachable. An org whose credential
    variable was rotated out of `.env` then had visits that could not be
    cancelled from anywhere, while the follow-up worker kept sending reminders
    for them."""
    import app.api.v1.visits as visits_mod
    from app.models.visit import VisitStatus
    from app.services.calendar_cal import CalComError

    async def _boom(*a: object, **k: object) -> bool:
        raise CalComError("no calendar for this organization")

    visit = SimpleNamespace(
        id=1,
        status=VisitStatus.SCHEDULED,
        calendar_provider="calcom",
        external_booking_id="cal-1",
        notes=None,
    )

    class _Result:
        def scalar_one_or_none(self) -> object:
            return visit

    class _Db:
        committed = False

        async def execute(self, *a: object, **k: object) -> _Result:
            return _Result()

        async def commit(self) -> None:
            self.committed = True

        async def refresh(self, *a: object, **k: object) -> None:
            return None

    db = _Db()
    with patch.object(visits_mod, "cancel_booking", _boom), patch.object(
        visits_mod.VisitOut, "model_validate", staticmethod(lambda v: v)
    ):
        await visits_mod.cancel_visit(
            visit_id=1, body=None, local_only=True, db=db
        )
    assert visit.status is VisitStatus.CANCELLED
    assert db.committed
    assert "check the calendar" in (visit.notes or ""), (
        "cancelled locally without recording that the booking may still stand"
    )


@pytest.mark.asyncio
async def test_a_first_boot_is_not_mistaken_for_a_broken_one() -> None:
    """The refusal added last round would have bricked every new install.

    Migrations run *after* the container starts, so on a first boot the
    organizations table does not exist yet, the count is unreadable, and a
    refusal crash-loops the container — which means the migration that creates
    the RLS role can never run and the documented install has no way out. The
    same unreadable count after migrations is the real symptom, so the two have
    to be told apart.
    """
    import contextlib

    import app.main as main_mod

    # Against the real database, where the table exists: not a first boot.
    assert await main_mod._schema_is_empty() is False

    class _Conn:
        async def execute(self, *a: object, **k: object) -> object:
            return SimpleNamespace(scalar=lambda: None)  # to_regclass → NULL

    class _Engine:
        @contextlib.asynccontextmanager
        async def _c(self):  # noqa: ANN202
            yield _Conn()

        def connect(self):  # noqa: ANN201
            return self._c()

    import app.db.base as base_mod

    with patch.object(base_mod, "get_bypass_engine", lambda: _Engine()):
        assert await main_mod._schema_is_empty() is True, (
            "a pre-migration boot reads as a broken one and crash-loops"
        )


@pytest.mark.asyncio
async def test_the_app_boots_against_a_database_with_no_schema_yet() -> None:
    """The end-to-end version of the previous test, against a real empty
    database. `docker compose up` starts the container and only then runs
    `alembic upgrade`, so this is literally the first boot of every new
    install. It must not raise."""
    import os

    from app.db.base import dispose_engine
    from app.main import _schema_is_empty, _startup_isolation_state

    empty = "postgresql+asyncpg://eko:eko_local_pass@localhost:5434/eko_firstboot"
    # Created here rather than assumed: a test that silently skips its own
    # premise is the kind of green this whole audit has been about.
    await _make_empty_database("eko_firstboot")
    previous = {
        k: os.environ.get(k)
        for k in ("DATABASE_URL", "DATABASE_URL_APP", "DATABASE_URL_BYPASS")
    }
    await dispose_engine()
    try:
        for key in previous:
            os.environ[key] = empty
        from app.config import get_settings

        get_settings.cache_clear()
        assert await _schema_is_empty() is True
        rls_off, real_orgs, known = await _startup_isolation_state()
        # The owner role IS a superuser, so RLS is genuinely not enforced here —
        # which is exactly the state that must NOT refuse before migrations.
        assert rls_off is True
        assert known is True and real_orgs == []
        from app.main import _must_refuse_to_serve

        assert not _must_refuse_to_serve(rls_off, real_orgs, known), (
            "a brand-new install crash-loops before its migrations can run"
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        from app.config import get_settings

        get_settings.cache_clear()
        await dispose_engine()
        await _drop_database("eko_firstboot")


@pytest.mark.asyncio
async def test_a_whatsapp_lead_can_actually_be_booked(monkeypatch) -> None:
    """The defect twenty-two rounds of tenant auditing never looked for.

    Cal.com refuses a booking with no attendee email. Leads are keyed by phone
    on every channel, and the attendee address was derived as "the phone, if it
    contains an @" — true only for email-channel leads. So against a real
    Cal.com account, every WhatsApp, SMS and voice booking failed: the dashboard
    showed 503 and the caller heard "trouble with the calendar". Invisible
    everywhere but production, because CALENDAR_SIMULATED returns before the
    HTTP call and simulated is the default.
    """
    from app.config import get_settings
    from app.models.agent_settings import AgentSettings
    from app.services.calendar_cal import CalComError, _booking_contact_email

    monkeypatch.setattr(get_settings(), "CALENDAR_SIMULATED", False)
    monkeypatch.setattr(get_settings(), "CALCOM_API_KEY", "k")
    monkeypatch.setattr(get_settings(), "CALCOM_EVENT_TYPE_ID", "11")
    # A properly onboarded agency: its own Cal.com key, its own event type.
    monkeypatch.setenv("CALCOM_KEY_ACME", "acmes-own-cal-key")
    await _make_agency(credential_ref="CALCOM_KEY_ACME", _dest="42")
    try:
        with org_scope(AGENCY):
            async with get_session_factory()() as db:
                db.add(
                    AgentSettings(
                        agency_name="Acme",
                        booking_contact_email="visits@acme.test",
                    )
                )
                await db.commit()
            assert await _booking_contact_email() == "visits@acme.test"

            # And it actually reaches Cal.com as the attendee, which is the
            # part that was broken: the check above passing means nothing if
            # `create_booking` never consults it.
            sent: dict[str, object] = {}

            class _Resp:
                status_code = 200

                def json(self) -> dict[str, object]:
                    return {"data": {"id": "cal-9", "uid": "u9"}}

            class _Client:
                def __init__(self, *a: object, **k: object) -> None:
                    pass

                async def __aenter__(self) -> "_Client":
                    return self

                async def __aexit__(self, *a: object) -> None:
                    return None

                async def post(self, url: str, **kwargs: object) -> _Resp:
                    sent.update(kwargs.get("json") or {})
                    return _Resp()

            import app.services.calendar_cal as cal_mod
            from app.services.calendar_cal import create_booking

            with patch.object(cal_mod.httpx, "AsyncClient", _Client):
                await create_booking(
                    start_time=datetime.now(UTC) + timedelta(days=1),
                    attendee_name="A WhatsApp Lead",
                    attendee_phone="+13035550000",
                )
            attendee = (sent.get("attendee") or {}) if isinstance(sent, dict) else {}
            assert attendee.get("email") == "visits@acme.test", (
                f"Cal.com was sent {attendee!r}; a phone-only lead is unbookable"
            )

        # And with nothing set, the refusal names the fix instead of being a
        # bare 503 nobody can act on.
        with org_scope(DEFAULT_ORG_ID):
            from app.services.calendar_cal import create_booking

            with pytest.raises(CalComError) as caught:
                await create_booking(
                    start_time=datetime.now(UTC) + timedelta(days=1),
                    attendee_name="A Lead",
                    attendee_phone="+13035550000",
                )
            assert "booking contact" in str(caught.value).lower()
    finally:
        await _cleanup()


def test_the_settings_a_customer_fills_in_actually_reach_the_agent() -> None:
    """`business_hours` and `greeting_template` were stored, editable in the
    Settings UI, and read by nothing. An agency set their opening line and the
    agent opened with something else; they set 9–7 and at 11pm the agent still
    said someone would call right back."""
    from zoneinfo import ZoneInfo

    from app.models.agent_settings import AgentSettings
    from app.services.conversation import (
        _greeting_note,
        _office_hours_note,
        _office_is_open,
    )

    cfg = AgentSettings(agency_name="Acme")
    cfg.timezone = "America/Denver"
    cfg.business_hours = {
        "monday": {"open": "09:00", "close": "19:00"},
        "sunday": None,
    }
    cfg.greeting_template = "Hola, soy el asistente de {agency_name}."

    note = _office_hours_note(cfg)
    assert "America/Denver" in note

    monday_hours = cfg.business_hours["monday"]
    assert _office_is_open(
        datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("America/Denver")), monday_hours
    )
    assert not _office_is_open(
        datetime(2026, 8, 10, 23, 0, tzinfo=ZoneInfo("America/Denver")), monday_hours
    )
    assert not _office_is_open(
        datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("America/Denver")), None
    )
    # An evening span that crosses midnight. Compared straight, the condition
    # is unsatisfiable, so an agency open 22:00–02:00 had every single reply
    # told the office was shut.
    evening = {"open": "22:00", "close": "02:00"}
    assert _office_is_open(
        datetime(2026, 8, 10, 23, 30, tzinfo=ZoneInfo("America/Denver")), evening
    )
    assert _office_is_open(
        datetime(2026, 8, 10, 1, 0, tzinfo=ZoneInfo("America/Denver")), evening
    )
    assert not _office_is_open(
        datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("America/Denver")), evening
    )

    # A malformed row must not turn every reply into an out-of-hours one.
    assert _office_is_open(
        datetime(2026, 8, 10, 23, 0, tzinfo=ZoneInfo("America/Denver")),
        {"open": "nonsense"},
    )

    assert "Acme" in _greeting_note(cfg)
    cfg.greeting_template = None
    assert _greeting_note(cfg) == ""


@pytest.mark.asyncio
async def test_the_agent_offers_real_times_or_none_at_all(monkeypatch) -> None:
    """The chat agent has no tools wired, so it cannot query a calendar — and
    left to itself it invents plausible viewing times, which is worse than
    saying nothing. It is now handed the real openings, the same way it is
    handed real listings, and only when the lead is actually asking."""
    from app.models.agent_settings import AgentSettings
    from app.services import conversation as conv

    cfg = AgentSettings(agency_name="Acme")
    cfg.timezone = "America/Denver"

    when = datetime(2026, 8, 12, 16, 0, tzinfo=UTC)

    async def _slots(**kwargs: object) -> list[object]:
        return [SimpleNamespace(start=when)]

    async def _no_busy(*a: object, **k: object) -> set[object]:
        return set()

    with patch("app.services.calendar_cal.list_available_slots", _slots), patch(
        "app.api.v1.visits._busy_starts", _no_busy
    ):
        # Not asking about a time: no calendar call, nothing added.
        assert await conv._real_slots_note(cfg, "how much is the condo?", None) == ""
        # And a word that only CONTAINS one: "necesita" holds "cita", which as a
        # substring spent a calendar call on every routine Spanish message.
        assert await conv._real_slots_note(cfg, "necesita algo mas?", None) == ""
        assert await conv._real_slots_note(cfg, "vi esto en Facebook", None) == ""
        note = await conv._real_slots_note(cfg, "can I book a viewing?", None)
    assert "10:00" in note, f"the office-local time is missing from {note!r}"
    assert "NUNCA inventes" in note

    # A calendar that is down costs a slot list, never the reply.
    async def _boom(**kwargs: object) -> list[object]:
        raise RuntimeError("cal.com is down")

    with patch("app.services.calendar_cal.list_available_slots", _boom), patch(
        "app.api.v1.visits._busy_starts", _no_busy
    ):
        assert await conv._real_slots_note(cfg, "can I book a viewing?", None) == ""


def test_every_feed_listing_carries_a_broker_to_credit() -> None:
    """Colorado requires the listing broker to be named wherever an IDX listing
    reaches a consumer, and the obligation sits on the agency's licence. The
    only place the name was kept was `raw`, which no API response exposed — so
    every property card, every detail view and every match list showed a
    REcolorado listing with no credit. In chat it was a line appended to the
    system prompt, which is to say a model was free to drop it."""
    from app.models.property import PropertySource
    from app.services.listings import listing_broker

    assert listing_broker("Kentwood Real Estate", PropertySource.RESO) == (
        "Kentwood Real Estate"
    )
    # A feed listing whose broker field is empty still gets credited. One
    # missing field in one record must not silently drop the attribution.
    assert listing_broker(None, PropertySource.RESO) == "REcolorado"
    assert listing_broker("", "reso") == "REcolorado"
    # A property the agency typed in itself is theirs; crediting a broker that
    # does not exist would be its own kind of wrong.
    assert listing_broker(None, PropertySource.MANUAL) is None
    # But if they named one, credit it whatever the source.
    assert listing_broker("Co-Broker LLC", PropertySource.MANUAL) == "Co-Broker LLC"


@pytest.mark.asyncio
async def test_a_scoped_import_does_not_hide_the_rest_of_the_feed() -> None:
    """`city` is applied on our side, so a scoped run sees every record and
    imports a few. Advancing the shared cursor past the rest told the
    unfiltered background sweep they were already handled — permanently. One
    `POST /properties/sync?city=Denver` made every Boulder listing modified in
    that window invisible, including the ones that had just gone under
    contract, which the agent kept offering at a stale price."""
    from sqlalchemy import select

    from app.models import SyncState
    from app.services import listings as mod

    far_future = datetime(2030, 1, 1, tzinfo=UTC)

    async def _one_empty_page(*a: object, **k: object):
        # A page the city filter emptied: nothing to import, but a high
        # watermark that must not be adopted.
        yield SimpleNamespace(listings=[], max_modified=far_future)

    async def _set_cursor(value: object) -> None:
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(SyncState).where(SyncState.source == mod.RESO_SOURCE_KEY)
                )
            ).scalar_one_or_none()
            if row is None:
                db.add(SyncState(source=mod.RESO_SOURCE_KEY, cursor_modified_at=value))
            else:
                row.cursor_modified_at = value
            await db.commit()

    async def _cursor() -> object:
        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(SyncState).where(SyncState.source == mod.RESO_SOURCE_KEY)
                )
            ).scalar_one_or_none()
            return row.cursor_modified_at if row else None

    from app.config import get_settings

    settings = get_settings()
    was_simulated = settings.LISTINGS_SIMULATED
    settings.LISTINGS_SIMULATED = False
    settings.RESO_BASE_URL = settings.RESO_BASE_URL or "https://feed.test"
    settings.RESO_ACCESS_TOKEN = settings.RESO_ACCESS_TOKEN or "t"
    baseline = datetime(2020, 1, 1, tzinfo=UTC)
    try:
        with org_scope(DEFAULT_ORG_ID):
            # A known baseline, and restored in `finally`. Left to whatever the
            # last run wrote, a failed assertion here leaves the cursor at the
            # value the next run expects to prove it did NOT reach — which is
            # how this test passed under its own mutation.
            await _set_cursor(baseline)
            with patch.object(mod, "_fetch_reso_pages", _one_empty_page):
                async with get_session_factory()() as db:
                    await mod.sync_listings(db, city="Denver")
            assert await _cursor() == baseline, (
                "a city-scoped import moved the sweep's cursor past listings it "
                "never looked at"
            )

            # And an unfiltered run still advances it, or the sweep never ends.
            with patch.object(mod, "_fetch_reso_pages", _one_empty_page):
                async with get_session_factory()() as db:
                    await mod.sync_listings(db)
            assert await _cursor() == far_future
    finally:
        with org_scope(DEFAULT_ORG_ID):
            await _set_cursor(None)
        settings.LISTINGS_SIMULATED = was_simulated


@pytest.mark.asyncio
async def test_the_same_person_on_two_channels_is_one_lead() -> None:
    """Leads are keyed on `phone` for every channel, so someone who wrote from
    WhatsApp and later emailed became two records: two score histories, two
    rows in the funnel, and a realtor reading half a conversation each time."""
    from sqlalchemy import func, select

    from app.models import Lead
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult

    async def _reply(**kwargs: object) -> LLMResult:
        return LLMResult(
            text="Of course.", provider="kimi", model="k2",
            input_tokens=1, output_tokens=1,
        )

    async def _sent(*a: object, **k: object) -> tuple[str, None]:
        return "id-1", None

    await _make_agency()
    try:
        with org_scope(AGENCY):
            async with get_session_factory()() as db:
                # They wrote from WhatsApp first, and gave us their address.
                lead = Lead(phone="+13035554444", email="buyer@example.test")
                db.add(lead)
                await db.commit()
                first_id = lead.id

            arriving_by_email = ParsedMessage(
                channel="email",
                external_id="msg-merge-1",
                from_identifier="buyer@example.test",
                from_name="A Buyer",
                content="Following up on the Aurora place.",
            )
            async with get_session_factory()() as db:
                with patch(
                    "app.services.conversation.generate_reply", _reply
                ), patch("app.services.conversation._dispatch_send", _sent):
                    await handle_inbound_message(arriving_by_email, db)

            async with get_session_factory()() as db:
                total = (
                    await db.execute(select(func.count()).select_from(Lead))
                ).scalar()
                same = (
                    await db.execute(
                        select(Lead).where(Lead.email == "buyer@example.test")
                    )
                ).scalars().all()
            assert total == 1, f"{total} leads for one person"
            assert same[0].id == first_id
    finally:
        await _cleanup()


def test_the_broker_credit_is_added_when_it_is_missing() -> None:
    """Three versions of this tried to detect whether the reply had offered a
    given listing — first by looking for the credit itself, which credited only
    what was already credited; then by looking for the title or address, which
    misses the moment the model paraphrases or translates. It no longer
    guesses: every broker whose listing was put in front of the model is
    credited."""
    from app.services.conversation import OfferedListing, _with_broker_credits

    offered = [
        OfferedListing(
            "Kentwood Real Estate", "Casa en Wash Park", "1200 S Gaylord St", 650000
        )
    ]

    # The case that matters: the model paraphrased the title out of existence.
    paraphrased = "I have a great place near the park for $650k, interested?"
    assert "Cortesía de Kentwood Real Estate" in _with_broker_credits(
        paraphrased, offered, "whatsapp"
    )

    # Already credited: do not say it twice.
    credited = paraphrased + " Cortesía de Kentwood Real Estate."
    assert _with_broker_credits(credited, offered, "whatsapp").count("Kentwood") == 1

    # A broker's own name inside a listing title is not a credit. Matching the
    # bare name treated it as one and dropped the real credit.
    tricky = [
        OfferedListing("Coldwell Banker", "Coldwell Banker Tower, Unit 5", None, 425000)
    ]
    out = _with_broker_credits(
        "The Coldwell Banker Tower, Unit 5 is available at $425,000.",
        tricky,
        "whatsapp",
    )
    assert "Cortesía de Coldwell Banker" in out

    # Nothing offered, nothing appended.
    assert _with_broker_credits("Abrimos los sábados.", [], "whatsapp") == (
        "Abrimos los sábados."
    )

    # And a reply that shows no listing data at all gets no footer, even though
    # listings were offered to the model this turn. Crediting regardless
    # stapled three brokers onto "we open at nine" for the rest of the
    # conversation.
    hours = "Abrimos de 9 a 6, de lunes a viernes."
    assert _with_broker_credits(hours, offered, "whatsapp") == hours


def test_the_credit_survives_a_reply_too_long_for_sms() -> None:
    """Twilio hard-rejects over 1600 characters, and a rejected message is now
    retried five times before it is given up on. The prose gives way; the
    credit does not."""
    from app.services.conversation import (
        _SMS_MAX_CHARS,
        OfferedListing,
        _with_broker_credits,
    )

    offered = [
        OfferedListing("Kentwood Real Estate", "Casa en Wash Park", None, 650000)
    ]
    long_reply = "Casa en Wash Park por $650,000. " + ("detalle " * 400)
    out = _with_broker_credits(long_reply, offered, "sms")
    assert "Cortesía de Kentwood Real Estate" in out
    assert len(out) <= _SMS_MAX_CHARS

    # And a footer that cannot fit at all must not produce a message that is
    # still over the limit. Subtracting an oversized footer from the budget
    # gave a body of "…" and returned "…" plus the footer — mangled AND
    # rejected, which is the worst of both.
    many = [
        OfferedListing(f"Very Long Brokerage Name Number {i}" * 12, "T", None, 650000)
        for i in range(8)
    ]
    out = _with_broker_credits(long_reply, many, "sms")
    assert len(out) <= _SMS_MAX_CHARS


@pytest.mark.asyncio
async def test_a_shared_mailbox_does_not_merge_two_people() -> None:
    """`info@agency.com` on two leads is not one person. Taking the oldest of
    several matches picked one and orphaned the other's conversations, score
    and funnel row — while the code believed it had merged them."""
    from sqlalchemy import func, select

    from app.models import Lead
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult

    async def _reply(**kwargs: object) -> LLMResult:
        return LLMResult(
            text="Claro.", provider="kimi", model="k2",
            input_tokens=1, output_tokens=1,
        )

    async def _sent(*a: object, **k: object) -> tuple[str, None]:
        return "id-shared", None

    await _make_agency()
    try:
        with org_scope(AGENCY):
            async with get_session_factory()() as db:
                db.add_all(
                    [
                        Lead(phone="+13035551111", email="info@shared.test"),
                        Lead(phone="+13035552222", email="info@shared.test"),
                    ]
                )
                await db.commit()

            async with get_session_factory()() as db:
                with patch(
                    "app.services.conversation.generate_reply", _reply
                ), patch("app.services.conversation._dispatch_send", _sent):
                    await handle_inbound_message(
                        ParsedMessage(
                            channel="email",
                            external_id="msg-shared-1",
                            from_identifier="info@shared.test",
                            from_name=None,
                            content="Hola",
                        ),
                        db,
                    )

            async with get_session_factory()() as db:
                total = (
                    await db.execute(select(func.count()).select_from(Lead))
                ).scalar()
            # A third lead, keyed on the address itself — not one of the two
            # strangers who happen to share a mailbox.
            assert total == 3
    finally:
        await _cleanup()


def test_the_footer_is_not_read_back_to_the_model() -> None:
    """The credit lives in `Message.content`, which is also what conversation
    history is built from — so the model read three credit lines back for every
    past turn and dutifully repeated them, and the inbox preview showed them
    instead of the answer."""
    from app.services.conversation import strip_broker_credits

    with_footer = (
        "Tengo una casa en Wash Park por $650k.\n\nCortesía de Kentwood Real Estate"
    )
    assert strip_broker_credits(with_footer) == "Tengo una casa en Wash Park por $650k."
    # A message that never had one is untouched, including one that merely
    # mentions a broker mid-sentence.
    plain = "Cortesía de la casa, el café es gratis."
    assert strip_broker_credits(plain) == plain


def test_the_credit_does_not_fire_on_things_that_are_not_listings() -> None:
    """Broad matching is not the safe direction it looks like.

    Matching the part of a title before a comma meant "Apartamento, 3 hab"
    credited all three offered brokers on any reply containing the word
    "apartamento"; matching a bare street number meant "9 Park Ave" matched
    "abrimos de 9 a 6"; and matching any money-shaped text credited a reply
    quoting a phone number. Each of those puts a broker's name on an answer
    that never showed their listing.
    """
    from app.services.conversation import OfferedListing, _with_broker_credits

    offered = [
        OfferedListing("Kentwood", "Apartamento, 3 habitaciones", "9 Park Ave", 425000)
    ]
    for innocent in (
        "Sí, tenemos apartamento disponible para verlo.",
        "Abrimos de 9 a 6 de lunes a viernes.",
        "Llámanos al 303.555.0134.",
        "La consulta es gratis, $0 de comisión por la visita.",
    ):
        assert _with_broker_credits(innocent, offered, "whatsapp") == innocent, (
            f"credited a broker on: {innocent!r}"
        )

    # And it still fires on the real thing, by price alone.
    real = "Ese está en 425,000 y podemos verlo mañana."
    assert "Cortesía de Kentwood" in _with_broker_credits(real, offered, "whatsapp")


def test_a_long_reply_is_cut_to_the_channel_even_without_a_credit() -> None:
    """The cap lived inside the credit branch, so a reply that earned no footer
    was never measured — and a 2200-character SMS is rejected by Twilio and
    then retried five times to the same rejection."""
    from app.services.conversation import _SMS_MAX_CHARS, _with_broker_credits

    huge = "detalle " * 400
    assert len(_with_broker_credits(huge, [], "sms")) <= _SMS_MAX_CHARS


def test_a_lead_s_own_words_are_never_trimmed() -> None:
    """The footer stripper ran on inbound messages too. A lead who pastes the
    agent's listing block and asks their question underneath had the question
    deleted from the model's context, so the agent answered the previous turn."""
    from app.models.message import MessageDirection
    from app.services.conversation import history_content

    pasted = (
        "Vi esto:\n\nCortesía de Kentwood Real Estate\n\n"
        "¿Sigue disponible y cuánto piden?"
    )
    from_lead = SimpleNamespace(
        direction=MessageDirection.INBOUND, content=pasted
    )
    assert history_content(from_lead) == pasted, (
        "the lead's actual question was deleted from the model's context"
    )

    ours = SimpleNamespace(
        direction=MessageDirection.OUTBOUND,
        content="Sí, sigue.\n\nCortesía de Kentwood Real Estate",
    )
    assert history_content(ours) == "Sí, sigue."


def test_a_price_is_matched_as_a_number_not_as_a_substring() -> None:
    """The credit failed in both directions at once.

    "1k" — the form for a $1,200 rental — is inside "451k", so an unrelated
    sale credited the rental's broker; and "1,200" is inside "1,200 sq ft", so
    a floor area did too. Meanwhile a listing with a short title, no address
    and no price could never match anything and so could never be credited at
    all, which is the failure that costs a licence.
    """
    from app.services.conversation import OfferedListing, _reply_shows

    sale = OfferedListing("K", "Casa en Wash Park", "1200 S Gaylord St", 650000)
    rental = OfferedListing("K", "Loft 5A", None, 1200)

    assert _reply_shows("for $650k, interested?", sale)
    assert _reply_shows("piden 650,000.", sale)
    assert not _reply_shows("tenemos otra en 451k", rental)
    assert not _reply_shows("tiene 1,200 sq ft", rental)
    assert not _reply_shows("una en 1650k", sale)
    # A small price still counts when it arrives as money.
    assert _reply_shows("son $1,200 al mes", rental)

    # Nothing to match on: credited rather than silently skipped.
    sparse = OfferedListing("K", "Loft", None, None)
    assert _reply_shows("cualquier cosa", sparse)


def test_the_footer_stripper_never_eats_the_body() -> None:
    """The listing block handed to the model already contains "Cortesía de", so
    the model echoes it, and a bulleted reply puts one mid-body. Splitting at
    the first occurrence deleted everything after it — including the actual
    question — from the history the model reads next turn."""
    from app.services.conversation import strip_broker_credits

    mid_body = (
        "Tengo dos:\n\nCortesía de Kentwood — Casa en Wash Park\n\n"
        "¿Cuál te interesa ver primero?"
    )
    assert strip_broker_credits(mid_body) == mid_body

    with_footer = "Tengo una en Wash Park.\n\nCortesía de Kentwood Real Estate"
    assert strip_broker_credits(with_footer) == "Tengo una en Wash Park."

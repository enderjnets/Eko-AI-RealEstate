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
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM channel_routes WHERE org_id = :i"), {"i": AGENCY})
        await db.execute(text("DELETE FROM visits WHERE org_id = :i"), {"i": AGENCY})
        await db.execute(text("DELETE FROM leads WHERE org_id = :i"), {"i": AGENCY})
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": AGENCY})
        await db.commit()
    tenant_resolver.reset_cache()


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
            await visits_mod.cancel_visit(visit_id=1, body=None, db=_Db())
    assert caught.value.status_code == 503
    assert visit.status is VisitStatus.SCHEDULED, (
        "the visit was left cancelled locally while the booking still stands"
    )

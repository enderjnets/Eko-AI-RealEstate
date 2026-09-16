"""The visit that came from a machine room, and the neighbour who did not.

Measured against production on 16-sep-2026. Of 212 landing sessions, 197 read
`traffic_class = 'unknown'` — the classifier that runs at ingest knows only the
QA marker, `navigator.webdriver` and nine user-agent signatures, and a crawler
in somebody's cloud region announces none of them.

Seven of the eight sessions that ever "started the form" were infrastructure:
Clonee, Boardman, Prineville, Forest City, Luleå and Springfield, 38 to 41
events each and **zero scroll**. Two more cities turned up the same day with
the same signature and no referrer at all: Council Bluffs (nine sessions) and
Ashburn (three).

The eighth was a person in The Pinery, Colorado.

That asymmetry is the whole design. This operation has no leads, so a session
wrongly called `automated` throws away the only kind of row that matters, while
one wrongly left `unknown` costs a slightly noisier denominator. Every rule
here is built to fail towards `unknown`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import LandingSession
from app.services.datacenter_cities import (
    KNOWN_SITES,
    NOT_LISTED_DESPITE_BEING_A_DATACENTER,
    OBSERVED,
    is_datacenter_city,
)
from app.services.landing_analytics import SETTLED_MINUTES, classify_datacenter_visits
from app.services.tenant_context import org_scope

ORG = 1


# ── The list itself, with no database in the way ─────────────────────────


def test_every_city_we_measured_is_recognised():
    """The seven that arrived as Facebook and AWS infrastructure, plus the two
    found while profiling the one-event bucket."""
    for city in ("Forest City", "Clonee", "Prineville", "Boardman", "Springfield"):
        assert is_datacenter_city(city), city
    assert is_datacenter_city("Council Bluffs")
    assert is_datacenter_city("Ashburn")


def test_the_mojibake_spelling_is_matched_because_it_is_what_we_store():
    """Luleå is stored in our own database as `LuleÃ¥` — the bytes measured on
    16-sep are `4c756c65c383c2a5`, which is `å` read as Latin-1 and written
    back as UTF-8. Matching only the correct spelling would give a list that
    looks right and catches nothing."""
    assert is_datacenter_city("LuleÃ¥")
    # And the correct one, so the day the header bug is fixed nothing silently
    # stops working.
    assert is_datacenter_city("Luleå")
    assert is_datacenter_city("Lulea")


def test_a_real_city_that_also_hosts_clouds_is_not_on_the_list():
    """The error that costs something. Every one of these is a place hundreds
    of thousands of people live, some of whom move to Denver."""
    for city in ("Dublin", "San Jose", "Chicago", "New York City", "Mountain View",
                 "Dallas", "Phoenix", "Los Angeles", "Boston"):
        assert not is_datacenter_city(city), city


def test_the_denver_metro_is_never_a_datacenter():
    """The suburbs this business actually sells in."""
    for city in ("Denver", "Aurora", "Parker", "The Pinery", "Wheat Ridge",
                 "Highlands Ranch", "Lakewood", "Ken Caryl", "Westminster"):
        assert not is_datacenter_city(city), city


def test_boydton_is_left_out_although_it_is_a_datacenter():
    """Four visits from Microsoft's Virginia region scrolled to 100%. Whatever
    they are, they are not the signature this module is about — and listing a
    city we have no evidence against is the habit the file exists to resist."""
    assert "boydton" in NOT_LISTED_DESPITE_BEING_A_DATACENTER
    assert not is_datacenter_city("Boydton")


def test_nothing_is_in_both_tiers():
    """Evidence and expectation have to stay apart, or the next person cannot
    tell which entries were measured."""
    assert not (set(OBSERVED) & set(KNOWN_SITES))


def test_an_absent_city_is_not_a_machine():
    assert not is_datacenter_city(None)
    assert not is_datacenter_city("")
    assert not is_datacenter_city("   ")


def test_capitalisation_and_padding_do_not_decide_it():
    assert is_datacenter_city("  COUNCIL BLUFFS  ")
    assert is_datacenter_city("council bluffs")


# ── The sweep, against the database ──────────────────────────────────────


async def _seed_session(
    key: str,
    *,
    city: str | None,
    max_scroll: int,
    event_count: int = 1,
    last_seen: datetime | None = None,
) -> int:
    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES + 5)
    async with get_bypass_session_factory()() as db:
        row = LandingSession(
            org_id=ORG,
            session_key=key,
            first_seen_at=settled,
            last_seen_at=last_seen or settled,
            source="direct",
            city=city,
            event_count=event_count,
            max_scroll_pct=max_scroll,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _class_of(session_id: int) -> tuple[str, str | None]:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                select(
                    LandingSession.traffic_class,
                    LandingSession.traffic_class_reason,
                ).where(LandingSession.id == session_id)
            )
        ).one()
        return row[0], row[1]


async def _cleanup(session_ids: list[int]) -> None:
    async with get_bypass_session_factory()() as db:
        for sid in session_ids:
            row = await db.get(LandingSession, sid)
            if row is not None:
                await db.delete(row)
        await db.commit()


@pytest.mark.asyncio
async def test_the_machine_room_is_marked_and_the_neighbour_is_not():
    """Both halves in one test, because the rule is only correct as a pair."""
    machine = await _seed_session("dc" + "1" * 30, city="Council Bluffs", max_scroll=0)
    person = await _seed_session("dc" + "2" * 30, city="Aurora", max_scroll=0)

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_datacenter_visits(db) == 1
        assert await _class_of(machine) == ("automated", "datacenter_city")
        # The one the inherited plan would have caught too. Aurora is a Denver
        # suburb; somebody who landed and left without scrolling is a bounce,
        # and until v0.108.0 that was the reasonable response to a calculator
        # that opened on two empty fields.
        assert await _class_of(person) == ("unknown", None)
    finally:
        await _cleanup([machine, person])


@pytest.mark.asyncio
async def test_a_datacenter_city_that_scrolled_is_left_alone():
    """Fifty thousand people live in Ashburn. The scroll is what separates one
    of them from the racks next door, and it is why the city can be listed at
    all."""
    scrolled = await _seed_session("dc" + "3" * 30, city="Ashburn", max_scroll=50)

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_datacenter_visits(db) == 0
        assert await _class_of(scrolled) == ("unknown", None)
    finally:
        await _cleanup([scrolled])


@pytest.mark.asyncio
async def test_a_visit_still_in_progress_is_left_for_later():
    """A row last seen a minute ago has not finished being a visit. A person
    reading the first screen scrolls at minute three, and by then the verdict
    would already be written."""
    fresh = await _seed_session(
        "dc" + "4" * 30, city="Council Bluffs", max_scroll=0,
        last_seen=datetime.now(UTC),
    )

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_datacenter_visits(db) == 0
        assert await _class_of(fresh) == ("unknown", None)
    finally:
        await _cleanup([fresh])


@pytest.mark.asyncio
async def test_it_never_overwrites_a_verdict_that_knew_more():
    """`test` was set by somebody holding the QA link, which is a claim a
    person made on purpose. A city name is weaker evidence than that."""
    ours = await _seed_session("dc" + "5" * 30, city="Clonee", max_scroll=0)
    async with get_bypass_session_factory()() as db:
        row = await db.get(LandingSession, ours)
        row.traffic_class = "test"
        row.traffic_class_reason = "explicit_qa"
        await db.commit()

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_datacenter_visits(db) == 0
        assert await _class_of(ours) == ("test", "explicit_qa")
    finally:
        await _cleanup([ours])


@pytest.mark.asyncio
async def test_a_session_with_no_city_is_never_judged():
    """The geo header is absent often enough that treating its absence as
    evidence would be its own bug."""
    nowhere = await _seed_session("dc" + "6" * 30, city=None, max_scroll=0)

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_datacenter_visits(db) == 0
        assert await _class_of(nowhere) == ("unknown", None)
    finally:
        await _cleanup([nowhere])


@pytest.mark.asyncio
async def test_the_person_who_started_the_form_survives_every_rule():
    """Session 208 in production, and the reason this file is careful.

    The Pinery, Colorado, 15-sep at 19:09. Desktop, arrived `direct`. Read the
    home page to 75%, went to the calculator, got $374,000, scrolled again and
    began the contact form — forty-eight seconds from landing to `form_start`.
    They did not submit.

    Seven of the eight form starters were machine rooms. This one was a person,
    and no rule here may ever reach them.
    """
    pinery = await _seed_session(
        "dc" + "7" * 30, city="The Pinery", max_scroll=75, event_count=19,
    )

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_datacenter_visits(db) == 0
        assert await _class_of(pinery) == ("unknown", None)
    finally:
        await _cleanup([pinery])

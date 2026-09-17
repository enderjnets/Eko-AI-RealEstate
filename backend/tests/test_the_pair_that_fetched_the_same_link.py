"""Two machines following the same link, seconds apart, from two cities.

A link posted or edited on a platform is fetched by several checkers at once,
each from a different egress point, and each arrives here as its own session in
its own city. Measured on the live rail twice: sixteen rows on 16-sep after
descriptions were edited, and ten rows on 15-sep between 21:59 and 22:07 UTC on
five videos published ten days earlier. Nothing records the trigger — those
edits are made by hand in YouTube Studio — so the signature is the evidence.

The rule that matters is DIFFERENT CITIES, and it is what keeps this from being
`one_shot_no_scroll` under another name, which this repo has already refused
once. One person opening a link twice is one city.

Every timestamp below is real, to the microsecond, from `landing_sessions`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import LandingSession
from app.services.landing_analytics import (
    SETTLED_MINUTES,
    classify_paired_link_checks,
)
from app.services.tenant_context import org_scope

ORG = 1

#: 22:00:18.941004 and 22:00:18.965470 on 15-sep-2026, New York City and
#: Denver, both on `piece-10`. Twenty-four milliseconds apart.
REAL_NY = datetime(2026, 9, 15, 22, 0, 18, 941004, tzinfo=UTC)
REAL_DENVER = datetime(2026, 9, 15, 22, 0, 18, 965470, tzinfo=UTC)


@pytest.fixture
def database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM landing_sessions WHERE session_key LIKE 'pair-test-%'")
        )
        await db.commit()


async def _visit(
    key: str,
    *,
    city: str,
    seen: datetime | None = None,
    utm_content: str = "piece-10",
    utm_source: str = "youtube",
    max_scroll: int = 0,
    cta_clicks: int = 0,
    form_started: datetime | None = None,
    traffic_class: str = "unknown",
    org_id: int = ORG,
) -> int:
    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES + 5)
    async with get_bypass_session_factory()() as db:
        row = LandingSession(
            org_id=org_id,
            session_key=f"pair-test-{key}",
            first_seen_at=seen or settled,
            last_seen_at=settled,
            source=utm_source,
            utm_source=utm_source,
            utm_medium="social",
            utm_content=utm_content,
            city=city,
            event_count=1,
            max_scroll_pct=max_scroll,
            cta_clicks=cta_clicks,
            form_started_at=form_started,
            traffic_class=traffic_class,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _class_of(session_id: int) -> tuple[str, str | None]:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                select(
                    LandingSession.traffic_class, LandingSession.traffic_class_reason
                ).where(LandingSession.id == session_id)
            )
        ).first()
        return row[0], row[1]


async def _sweep() -> int:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            return await classify_paired_link_checks(db)


@pytest.mark.asyncio
async def test_the_pair_twenty_four_milliseconds_apart_is_not_two_people(
    database_url: str,
) -> None:
    """The real pair, with its real timestamps. A reader in New York and a
    reader in Denver do not open the same video's link 24 milliseconds apart,
    and a rule that let Denver through by name would be blind exactly where a
    machine room with a Denver address is."""
    ny = await _visit("ny", city="New York City", seen=REAL_NY)
    denver = await _visit("denver", city="Denver", seen=REAL_DENVER)
    try:
        assert await _sweep() == 2
        # BOTH sides are marked, not just the one the join started from.
        assert await _class_of(ny) == ("automated", "paired_link_check")
        assert await _class_of(denver) == ("automated", "paired_link_check")
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_same_city_twice_is_one_person_opening_a_link_twice(
    database_url: str,
) -> None:
    """The counterweight, and the reason this rule is allowed to exist. Without
    it this is `one_shot_no_scroll`, which this repo refused."""
    first = await _visit("a", city="Denver", seen=REAL_NY)
    second = await _visit("b", city="Denver", seen=REAL_DENVER)
    try:
        assert await _sweep() == 0
        assert await _class_of(first) == ("unknown", None)
        assert await _class_of(second) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_visit_alone_is_not_a_pair(database_url: str) -> None:
    alone = await _visit("alone", city="Boston", seen=REAL_NY)
    try:
        assert await _sweep() == 0
        assert await _class_of(alone) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_pair_a_minute_and_a_second_apart_is_not_a_pair(
    database_url: str,
) -> None:
    """The widest real gap measured is 21 seconds. Sixty-one is a person."""
    a = await _visit("a", city="Boston", seen=REAL_NY)
    b = await _visit("b", city="Chicago", seen=REAL_NY + timedelta(seconds=61))
    try:
        assert await _sweep() == 0
        assert await _class_of(a) == ("unknown", None)
        assert await _class_of(b) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_pair_where_one_read_the_page_is_two_readers(
    database_url: str,
) -> None:
    """Scrolling is the one thing a link checker never does."""
    reader = await _visit("reader", city="Denver", seen=REAL_NY, max_scroll=25)
    other = await _visit("other", city="Boston", seen=REAL_DENVER)
    try:
        assert await _sweep() == 0
        assert await _class_of(reader) == ("unknown", None)
        assert await _class_of(other) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_pair_where_one_started_the_form_is_two_readers(
    database_url: str,
) -> None:
    """The expensive mistake this avoids: filing a lead's own visit as a
    machine."""
    lead = await _visit(
        "lead", city="Denver", seen=REAL_NY, form_started=REAL_NY
    )
    other = await _visit("other", city="Boston", seen=REAL_DENVER)
    try:
        assert await _sweep() == 0
        assert await _class_of(lead) == ("unknown", None)
        # And the other half too: a pair is judged whole or not at all.
        assert await _class_of(other) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_pair_where_one_clicked_the_call_to_action_is_two_readers(
    database_url: str,
) -> None:
    clicker = await _visit("click", city="Denver", seen=REAL_NY, cta_clicks=1)
    other = await _visit("other", city="Boston", seen=REAL_DENVER)
    try:
        assert await _sweep() == 0
        assert await _class_of(clicker) == ("unknown", None)
        assert await _class_of(other) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_two_visits_with_no_campaign_never_pair(database_url: str) -> None:
    """Without a link there is nothing for a checker to have followed, and NULL
    does not equal NULL in SQL — which is the behaviour we want, so it is
    asserted rather than left to chance. The two real Denver visits in that
    range fall out here and by scrolling, not by any list of cities."""
    a = await _visit("a", city="Denver", seen=REAL_NY, utm_source=None, utm_content=None)
    b = await _visit("b", city="Boston", seen=REAL_DENVER, utm_source=None, utm_content=None)
    try:
        assert await _sweep() == 0
        assert await _class_of(a) == ("unknown", None)
        assert await _class_of(b) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visit_already_judged_is_never_overwritten(
    database_url: str,
) -> None:
    """This is the weakest evidence of the three rules. `test` was set by a
    person who knew, and the QA marker outranks an inference."""
    qa = await _visit("qa", city="Denver", seen=REAL_NY, traffic_class="test")
    other = await _visit("other", city="Boston", seen=REAL_DENVER)
    try:
        assert await _sweep() == 0
        assert await _class_of(qa) == ("test", None)
        assert await _class_of(other) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visit_that_has_not_settled_is_left_alone(
    database_url: str,
) -> None:
    """A reader can sit on the first screen for a while; the tracker records
    nothing until they scroll."""
    fresh = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        for key, city in (("fresh-a", "Denver"), ("fresh-b", "Boston")):
            db.add(
                LandingSession(
                    org_id=ORG,
                    session_key=f"pair-test-{key}",
                    first_seen_at=fresh,
                    last_seen_at=fresh,
                    source="youtube",
                    utm_source="youtube",
                    utm_content="piece-10",
                    city=city,
                    event_count=1,
                    max_scroll_pct=0,
                )
            )
        await db.commit()
    try:
        assert await _sweep() == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_pair_belonging_to_another_agency_is_not_touched(
    database_url: str,
) -> None:
    mine = await _visit("mine", city="Denver", seen=REAL_NY)
    theirs = await _visit("theirs", city="Boston", seen=REAL_DENVER, org_id=2)
    try:
        assert await _sweep() == 0
        assert await _class_of(mine) == ("unknown", None)
        assert await _class_of(theirs) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_three_checkers_on_one_link_are_counted_once_each(
    database_url: str,
) -> None:
    """A link fetched by three pairs each row with two others; without the
    `distinct` the same session would be counted three times."""
    ids = [
        await _visit("a", city="Greenfield", seen=REAL_NY),
        await _visit("b", city="Mountain View", seen=REAL_DENVER),
        # NOT a city on the data-centre list: that rule runs in the same loop,
        # and a test whose cities it also claims would assert a number
        # production never produces.
        await _visit("c", city="Pittsburgh", seen=REAL_NY + timedelta(seconds=2)),
    ]
    try:
        assert await _sweep() == 3
        for session_id in ids:
            assert await _class_of(session_id) == ("automated", "paired_link_check")
    finally:
        await _cleanup()


# ── That somebody pulls the rope ─────────────────────────────────────────


def test_every_classifier_is_actually_called_by_the_loop() -> None:
    """Proving a sweep works says nothing about whether production runs it.

    This repo has paid for that twice: a fair-housing watch written and never
    scheduled, and a doorbell wired to nothing. All three landing classifiers
    are driven by hand in their own tests, so this reads the loop's source and
    fails if any of them stops being called.
    """
    import ast
    import inspect

    from app import main as app_main

    loop = next(
        node
        for node in ast.walk(ast.parse(inspect.getsource(app_main)))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_llm_monitor_loop"
    )
    called = {
        arg.id
        for node in ast.walk(loop)
        if isinstance(node, ast.Call)
        for arg in node.args
        if isinstance(arg, ast.Name)
    }
    for name in (
        "classify_paired_link_checks",
        "classify_publish_previews",
        "classify_datacenter_visits",
    ):
        assert name in called, f"{name} exists but the loop never calls it"


def test_the_pairing_runs_before_the_looser_rule() -> None:
    """Order is the rule here, not a detail.

    Pairing needs BOTH halves still `unknown`. The data-centre rule is looser
    on the same rows — a listed city and no scroll, nothing said about clicks
    or forms — so running it first takes one half and leaves the other
    orphaned, `unknown` for ever with no partner left to pair with.
    """
    import ast
    import inspect

    from app import main as app_main

    loop = next(
        node
        for node in ast.walk(ast.parse(inspect.getsource(app_main)))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_llm_monitor_loop"
    )
    order = [
        arg.id
        for node in ast.walk(loop)
        if isinstance(node, ast.Call)
        for arg in node.args
        if isinstance(arg, ast.Name) and arg.id.startswith("classify_")
    ]
    assert order.index("classify_paired_link_checks") < order.index(
        "classify_datacenter_visits"
    ), f"the looser rule runs first and will orphan half of every pair: {order}"


@pytest.mark.asyncio
async def test_a_visit_that_became_a_lead_is_never_a_machine(
    database_url: str,
) -> None:
    """The row that would have cost something.

    The public capture endpoint creates a session for a form post whose key the
    beacon never registered — which is what happens when a content blocker eats
    the tracking call and lets the form through. That row is born with no
    scroll, no clicks and no `form_started_at`, and it carries the campaign of
    the link the person followed. Without this guard a link checker fetching
    the same link from another city inside the minute would have taken the two
    of them down together, and a false `automated` throws away the only kind of
    row that matters.
    """
    from app.models import Lead

    async with get_bypass_session_factory()() as db:
        person_row = Lead(org_id=ORG, phone="+13035550199", name="A person")
        db.add(person_row)
        await db.commit()
        lead_id = person_row.id
    person = await _visit("person", city="Denver", seen=REAL_NY)
    checker = await _visit("checker", city="Boston", seen=REAL_DENVER)
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE landing_sessions SET lead_id = :l WHERE id = :i"),
            {"l": lead_id, "i": person},
        )
        await db.commit()
    try:
        assert await _sweep() == 0
        assert await _class_of(person) == ("unknown", None)
        # And its partner with it: a pair is judged whole or not at all.
        assert await _class_of(checker) == ("unknown", None)
    finally:
        await _cleanup()
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
            await db.commit()


@pytest.mark.asyncio
async def test_a_pair_older_than_the_lookback_is_left_where_it_is(
    database_url: str,
) -> None:
    """Nothing purges `landing_sessions`, and this join is quadratic inside
    each campaign. Without a floor every row ever recorded would be compared
    against every other one, every five minutes, for ever."""
    from app.services.landing_analytics import PAIRED_CHECK_LOOKBACK_DAYS

    old = datetime.now(UTC) - timedelta(days=PAIRED_CHECK_LOOKBACK_DAYS + 1)
    a = await _visit("old-a", city="Denver", seen=old)
    b = await _visit("old-b", city="Boston", seen=old + timedelta(seconds=1))
    try:
        assert await _sweep() == 0
        assert await _class_of(a) == ("unknown", None)
        assert await _class_of(b) == ("unknown", None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visit_that_pressed_send_is_never_a_machine(
    database_url: str,
) -> None:
    """Pressing send and no lead arriving is the row this repo went looking for.

    `merge_values` writes `form_submitted_at` from the beacon's own
    `form_submit` event, and the comment above it says why: the disagreement
    with `lead_id` is the interesting case, the captcha refusal or the dropped
    connection, invisible if only the successful path writes it. Such a row has
    no scroll, no clicks, no `form_started_at` and no lead, so the other eight
    clauses let it through. Only this one holds it back, and it is the last
    thing anyone would want thrown away as a machine.
    """
    person = await _visit("sent", city="Denver", seen=REAL_NY)
    checker = await _visit("checker", city="Boston", seen=REAL_DENVER)
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE landing_sessions SET form_submitted_at = :t WHERE id = :i"),
            {"t": REAL_NY, "i": person},
        )
        await db.commit()
    try:
        assert await _sweep() == 0
        assert await _class_of(person) == ("unknown", None)
        # And its partner with it: a pair is judged whole or not at all.
        assert await _class_of(checker) == ("unknown", None)
    finally:
        await _cleanup()

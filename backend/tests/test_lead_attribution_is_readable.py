"""Which video produced this lead — captured for versions, readable from today.

`services/capture.py` has whitelisted `utm_*`, `gclid`, `fbclid`,
`landing_variant`, `tier` and `referrer` into `lead.meta` since the landing
shipped, and the comment above that whitelist says out loud what it is for:
"which video produced this lead". Nothing ever read it back. The API did not
return it and no component drew it, so the one number that says whether the
videos are working was written to a column nobody could open — which matters
now, with the seller rotation about to go live.

**Every test that touches the stored shape goes through `capture_lead`.** The
first version of this file hand-built a flat `meta` dict, and that is exactly
how it certified a broken feature green: `_record_attribution` nests the pairs
under `meta["attribution"]`, the reader looked at the top level, and the
endpoint returned `{}` for every real lead while eight tests passed. A fixture
that invents the shape it is testing cannot fail — so the shape is no longer
invented here.

The calculator tests at the bottom set `calculator_snapshot` directly, because
until the capture form learns to send a calculation (the next phase) no writer
exists — but the VALUE is not invented: it is what `build_snapshot` produces,
so the real shape (floats, nested dicts, nulls under the floor) is what goes
through JSONB and comes back. They assert the read side: the column returns
whole, and its absence is SQL NULL, not a JSON `null`. The write side gets its
tests through `capture_lead` in the phase that adds it.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.api.v1.leads import _attribution_of
from app.db.base import get_bypass_session_factory, get_session_factory
from app.main import app
from app.models.lead import Lead
from app.services.calculator import build_snapshot
from app.services.capture import FormSubmission, capture_lead
from app.services.tenant_context import org_scope

ORG = 1
PHONE = "+19995550612"

# What the landing form POSTs. `capture_lead` is what turns this into whatever
# lives in the column — which is the point: this test never asserts the storage
# shape, it asserts what comes back out.
POSTED = {
    "utm_source": "youtube",
    "utm_campaign": "seller-oct",
    "landing_variant": "denver-home-story",
    "sneaky": "should-not-survive",
}


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — this needs live Postgres")
    return url


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": PHONE})
        await db.commit()


async def _capture(attribution: dict | None) -> int:
    """A lead created the way the landing creates one. No hand-built meta."""
    await _cleanup()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await capture_lead(
                FormSubmission(
                    name="Attribution Probe",
                    phone=PHONE,
                    message="I want to sell my house",
                    attribution=attribution or {},
                ),
                db,
            )
            await db.commit()
    async with get_bypass_session_factory()() as db:
        lead = (
            await db.execute(select(Lead).where(Lead.phone == PHONE))
        ).scalar_one()
        return lead.id


async def _get(lead_id: int) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/v1/leads/{lead_id}")
    assert r.status_code == 200, r.text
    return r.json()


# ── End to end: the landing writes it, the API returns it ────────────────────


@pytest.mark.asyncio
async def test_a_lead_captured_by_the_landing_shows_where_it_came_from(
    database_url: str,
) -> None:
    """The test the first version of this file was missing.

    It is the only one that can catch a reader pointed at the wrong level of
    `meta`, because it is the only one where the shape comes from the writer.
    """
    lead_id = await _capture(POSTED)
    try:
        assert (await _get(lead_id))["attribution"] == {
            "utm_source": "youtube",
            "utm_campaign": "seller-oct",
            "landing_variant": "denver-home-story",
        }
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_api_never_ships_the_rest_of_meta(database_url: str) -> None:
    """`captured_at` is stamped beside the pairs by the writer and is not
    attribution; `sneaky` was posted and dropped at capture. Neither may appear."""
    lead_id = await _capture(POSTED)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get(f"/api/v1/leads/{lead_id}")
        raw = r.text
        assert "captured_at" not in raw, "the writer's timestamp leaked as attribution"
        assert "sneaky" not in raw
        assert "meta" not in r.json(), "meta is exposed as a field"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_only_the_first_touch_is_returned(database_url: str) -> None:
    """First touch wins, by design: crediting the newest submission would
    credit the retargeting ad instead of the video that found the person.
    A second submission is kept in `attribution_later` and is NOT returned."""
    lead_id = await _capture(POSTED)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await capture_lead(
                    FormSubmission(
                        phone=PHONE,
                        message="second visit",
                        attribution={"utm_source": "retargeting"},
                    ),
                    db,
                )
                await db.commit()
        body = await _get(lead_id)
        assert body["attribution"]["utm_source"] == "youtube", (
            "the later touch overwrote the credit for the content that found them"
        )
        assert "retargeting" not in str(body["attribution"])
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_with_no_attribution_gets_an_empty_object(
    database_url: str,
) -> None:
    """Not null, not missing: the component counts keys and hides the whole
    block — the landing's own rule for absent data."""
    lead_id = await _capture(None)
    try:
        assert (await _get(lead_id))["attribution"] == {}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_list_endpoint_carries_it_too(database_url: str) -> None:
    """Both build sites go through `_lead_out`; the list one is the easy one to
    forget, and it is the screen a realtor actually scans.

    `sort=recent` on purpose. There is no text filter on this endpoint — an
    unknown query parameter is silently ignored by FastAPI, so the first
    version of this test appeared to filter by phone and in fact just read the
    default page, passing only while the database was small enough for the
    seeded lead to land on it. `capture_lead` writes an inbound message, so
    `last_message_at` is now and the row is first by construction.
    """
    lead_id = await _capture(POSTED)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/leads?sort=recent&limit=5")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items and items[0]["id"] == lead_id, (
            "the just-captured lead is not the most recent one — the fixture or "
            "the ordering changed, and this test is no longer reading what it thinks"
        )
        assert items[0]["attribution"]["utm_source"] == "youtube"
    finally:
        await _cleanup()


# ── The filter, in isolation ─────────────────────────────────────────────────


def test_junk_meta_does_not_raise() -> None:
    assert _attribution_of(None) == {}
    assert _attribution_of("not a dict") == {}
    assert _attribution_of({}) == {}
    assert _attribution_of({"attribution": "not a dict either"}) == {}
    assert _attribution_of({"attribution": ["a", "list"]}) == {}


def test_a_non_string_under_a_whitelisted_key_is_dropped() -> None:
    """`meta` is JSON and promises nothing about what a future writer stores
    under a key we happen to whitelist."""
    assert _attribution_of({"attribution": {"utm_medium": 42}}) == {}
    assert _attribution_of({"attribution": {"utm_source": {"nested": "x"}}}) == {}


def test_top_level_pairs_are_not_mistaken_for_attribution() -> None:
    """The exact defect this file shipped with: reading the wrong level.

    A `meta` with whitelisted keys at the top and nothing nested is not a lead
    the landing captured, and must not be reported as one."""
    assert _attribution_of({"utm_source": "youtube", "source": "manual"}) == {}


def test_every_captured_key_is_readable() -> None:
    """Imported, not copied. Two lists would drift silently: a key added to
    capture would be stored and never displayed."""
    from app.services.capture import ATTRIBUTION_KEYS

    for key in ATTRIBUTION_KEYS:
        assert _attribution_of({"attribution": {key: "v"}}) == {key: "v"}, (
            f"{key} is captured but not readable"
        )


# ── The calculator snapshot: read back whole, absent as SQL NULL ─────────────

# The real thing, from the real producer. For $2,100 of rent and $15,000 saved
# with good credit the golden fixture's cross anchor says $262,451.17.
SNAPSHOT = build_snapshot({"rent": 2100, "savings": 15000, "credit": "good"}, None, lang="en")
# And the shape under the estimate floor: nulls nested inside the JSON.
FLOOR_SNAPSHOT = build_snapshot({"rent": 500, "savings": 0, "credit": "fair"}, None, lang="es")


async def _stamp(lead_id: int, snapshot: dict | None) -> None:
    """Write the column directly — see the module docstring for why."""
    async with get_bypass_session_factory()() as db:
        lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
        lead.calculator_snapshot = snapshot
        await db.commit()


async def _sql_null_count(lead_id: int) -> int:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT count(*) FROM leads WHERE id = :id AND calculator_snapshot IS NULL"),
                {"id": lead_id},
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_the_calculator_snapshot_comes_back_whole(database_url: str) -> None:
    """Whole, on both build sites: the detail screen shows it, and the list
    goes through the same `_lead_out`."""
    lead_id = await _capture(None)
    try:
        await _stamp(lead_id, SNAPSHOT)
        body = await _get(lead_id)
        assert body["calculator"]["result"]["price"] == 262451
        assert body["calculator"]["result"]["capped_by"] == "rent"
        assert body["calculator"]["inputs"] == {"rent": 2100.0, "savings": 15000.0, "credit": "good"}
        assert body["calculator"] == SNAPSHOT
        # Under the floor the nested nulls survive the round trip as nulls.
        await _stamp(lead_id, FLOOR_SNAPSHOT)
        floor = (await _get(lead_id))["calculator"]
        assert floor["result"]["capped_by"] == "floor"
        assert floor["result"]["net_5y"] is None
        assert floor["result"]["crossover_year"] is None
        assert floor["lang"] == "es"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/leads", params={"limit": 200})
        assert r.status_code == 200, r.text
        listed = next(i for i in r.json()["items"] if i["id"] == lead_id)
        assert listed["calculator"]["result"]["capped_by"] == "floor"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_without_a_calculation_is_null_in_json_and_in_sql(
    database_url: str,
) -> None:
    """`None` in the API, and SQL NULL in the table — not the JSON literal
    `null`, which `IS NULL` would not match and which a later "who used the
    calculator" query would count as a snapshot."""
    lead_id = await _capture(None)
    try:
        assert (await _get(lead_id))["calculator"] is None
        assert await _sql_null_count(lead_id) == 1
        # Writing a value and then clearing it lands back on SQL NULL.
        await _stamp(lead_id, SNAPSHOT)
        assert await _sql_null_count(lead_id) == 0
        await _stamp(lead_id, None)
        assert (await _get(lead_id))["calculator"] is None
        assert await _sql_null_count(lead_id) == 1
    finally:
        await _cleanup()

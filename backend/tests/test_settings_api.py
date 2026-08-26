"""Tests for the agency settings API — GET/PUT the AgentSettings singleton.

AgentSettings is a single global row (id=1), so each mutating test snapshots
the original config first and restores it in a `finally` to keep the suite
order-independent.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_RESTORABLE = ("agency_name", "brokerage_line", "agency_phone", "agent_persona", "greeting_template", "languages", "timezone", "business_hours")


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — settings API tests need live Postgres")


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _snapshot() -> dict:
    async with await _client() as c:
        r = await c.get("/api/v1/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    return {k: body[k] for k in _RESTORABLE}


async def _restore(snapshot: dict) -> None:
    async with await _client() as c:
        r = await c.put("/api/v1/settings", json=snapshot)
    # Asserted, not fire-and-forget: a restore that 4xx'd would leave the next
    # test running against the previous one's data, and since brokerage_line
    # lives here that dirty state now has legal consequences downstream.
    assert r.status_code == 200, f"restore failed: {r.status_code} {r.text}"


@pytest.mark.asyncio
async def test_get_settings_autocreates_with_defaults(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agency_name"]                  # non-empty default
    assert "es" in body["languages"]            # ships ES by default
    assert isinstance(body["business_hours"], dict)
    assert "{agency_name}" in body["greeting_template"] or body["agency_name"] in body["greeting_template"]


@pytest.mark.asyncio
async def test_put_updates_agency_name(_needs_db: None) -> None:
    original = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={"agency_name": "Sunset Realty Group"})
        assert r.status_code == 200, r.text
        assert r.json()["agency_name"] == "Sunset Realty Group"

        # Persisted across requests.
        async with await _client() as c:
            r2 = await c.get("/api/v1/settings")
        assert r2.json()["agency_name"] == "Sunset Realty Group"
    finally:
        await _restore(original)


@pytest.mark.asyncio
async def test_put_partial_leaves_other_fields(_needs_db: None) -> None:
    original = await _snapshot()
    try:
        async with await _client() as c:
            await c.put("/api/v1/settings", json={"agency_phone": "+1-305-555-0100"})
            r = await c.get("/api/v1/settings")
        body = r.json()
        assert body["agency_phone"] == "+1-305-555-0100"
        assert body["agent_persona"] == original["agent_persona"]  # untouched
    finally:
        await _restore(original)


@pytest.mark.asyncio
async def test_put_languages_normalized_and_deduped(_needs_db: None) -> None:
    original = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={"languages": ["EN", "es", "en", " ES "]})
        assert r.status_code == 200, r.text
        assert r.json()["languages"] == ["en", "es"]
    finally:
        await _restore(original)


@pytest.mark.asyncio
async def test_get_settings_includes_brokerage_line(_needs_db: None) -> None:
    """The publish/render gates already require this field to exist somewhere
    reachable from Settings — this is the door, so it has to be in the GET."""
    async with await _client() as c:
        r = await c.get("/api/v1/settings")
    assert "brokerage_line" in r.json()


@pytest.mark.asyncio
async def test_put_updates_brokerage_line(_needs_db: None) -> None:
    original = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put(
                "/api/v1/settings",
                json={"brokerage_line": "Natalia & Robbie · Engel & Völkers"},
            )
        assert r.status_code == 200, r.text
        assert r.json()["brokerage_line"] == "Natalia & Robbie · Engel & Völkers"

        async with await _client() as c:
            r2 = await c.get("/api/v1/settings")
        assert r2.json()["brokerage_line"] == "Natalia & Robbie · Engel & Völkers"
    finally:
        await _restore(original)


@pytest.mark.parametrize("cleared", ["", None])
@pytest.mark.asyncio
async def test_put_brokerage_line_can_be_cleared(_needs_db: None, cleared: str | None) -> None:
    """A broker must be able to blank it out again, with no special endpoint.

    Both shapes, because the two callers disagree: the Settings form sends
    `null` (`e.target.value || null`) and never `""`, while a direct API caller
    may send either. Testing only `""` would leave the path the product
    actually uses uncovered. Both gates read blank-or-missing as "not set".
    """
    original = await _snapshot()
    try:
        async with await _client() as c:
            await c.put("/api/v1/settings", json={"brokerage_line": "Some Brokerage LLC"})
            r = await c.put("/api/v1/settings", json={"brokerage_line": cleared})
        assert r.status_code == 200, r.text
        # Not asserted equal to what was sent: "" normalises to None, so that
        # a blank never renders as a filled box in Settings. What matters is
        # what the gates read, which is the point of clearing it at all.
        assert r.json()["brokerage_line"] is None
    finally:
        await _restore(original)


@pytest.mark.asyncio
async def test_put_brokerage_line_too_long_is_refused(_needs_db: None) -> None:
    """201 characters must 422 at the schema, not 500 at the column.

    `String(200)` would raise StringDataRightTruncation and surface as a 500;
    the field's max_length is what turns that into an answerable error.
    """
    async with await _client() as c:
        r = await c.put("/api/v1/settings", json={"brokerage_line": "x" * 201})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_timezone_roundtrip(_needs_db: None) -> None:
    original = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={"timezone": "America/Denver"})
        assert r.status_code == 200, r.text
        assert r.json()["timezone"] == "America/Denver"
        async with await _client() as c:
            assert (await c.get("/api/v1/settings")).json()["timezone"] == "America/Denver"
    finally:
        await _restore(original)


@pytest.mark.asyncio
async def test_put_invalid_timezone_400(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.put("/api/v1/settings", json={"timezone": "Mars/Olympus_Mons"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_empty_body_400(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.put("/api/v1/settings", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_unknown_field_422(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.put("/api/v1/settings", json={"not_a_field": "x"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_empty_languages_422(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.put("/api/v1/settings", json={"languages": []})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_whitespace_is_not_a_brokerage_line(_needs_db: None) -> None:
    """Both gates strip before deciding, so "   " means unset to them.

    If the API stored it raw, Settings would render a filled box while nothing
    rendered or published — and the help text next to that box says the
    opposite. `test_content_gate_is_absolute.py` already asserts the gate side
    of this; this is the door side.
    """
    original = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={"brokerage_line": "   "})
        assert r.status_code == 200, r.text
        assert r.json()["brokerage_line"] is None
    finally:
        await _restore(original)


@pytest.mark.asyncio
async def test_surrounding_space_is_trimmed_before_it_is_burned(_needs_db: None) -> None:
    """The value goes into the video verbatim; leading space is not a design."""
    original = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={"brokerage_line": "  E&V Aspen  "})
        assert r.json()["brokerage_line"] == "E&V Aspen"
    finally:
        await _restore(original)

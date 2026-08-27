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

# `booking_contact_email` was missing here, so any test touching it left its
# value behind for whatever ran next.
_RESTORABLE = (
    "agency_name", "brokerage_line", "agency_phone", "booking_contact_email",
    "agent_persona", "greeting_template", "languages", "timezone", "business_hours",
)


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


@pytest.mark.parametrize(
    "field",
    ["agency_name", "agent_persona", "greeting_template", "timezone"],
)
@pytest.mark.asyncio
async def test_whitespace_is_refused_for_a_column_that_cannot_be_null(
    _needs_db: None, field: str
) -> None:
    """Blank input on a NOT NULL column must 422, not 500 and not persist " ".

    Two failures live here, and only one of them is obvious. `min_length=1` ran
    BEFORE any trimming, so " " passed validation and was written verbatim —
    which is how `agency_name` came to hold "Ashly " and every greeting read
    "assistant at Ashly .". But the naive fix, one validator that returns None
    when the trimmed value is empty, is worse: the handler `setattr`s whatever
    is present, so None reaches a NOT NULL column and the request 500s.

    So the assertion is the status code, not just the stored value. 422 says
    the field is named in the response and the caller can fix it; 500 says the
    server broke.
    """
    snap = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={field: "   "})
        assert r.status_code == 422, (
            f"{field} accepted whitespace with {r.status_code}: {r.text[:200]}"
        )
        assert field in r.text, "the 422 does not name the offending field"

        async with await _client() as c:
            after = (await c.get("/api/v1/settings")).json()
        assert after[field] == snap[field], f"{field} was modified by a refused write"
    finally:
        await _restore(snap)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agency_name", "  Ashly  "),
        ("agent_persona", "  I am the assistant.  "),
        ("greeting_template", "  Hello {name}!  "),
    ],
)
@pytest.mark.asyncio
async def test_surrounding_space_is_trimmed_on_the_required_fields(
    _needs_db: None, field: str, value: str
) -> None:
    """The bug the owner actually saw: "assistant at Ashly ." in every greeting.

    Fixed for `brokerage_line` in v0.55.0 and not generalised, which is why it
    came back on the field next door.
    """
    snap = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={field: value})
        assert r.status_code == 200, r.text
        assert r.json()[field] == value.strip()

        async with await _client() as c:
            assert (await c.get("/api/v1/settings")).json()[field] == value.strip()
    finally:
        await _restore(snap)


@pytest.mark.parametrize(
    "field", ["brokerage_line", "agency_phone", "booking_contact_email"]
)
@pytest.mark.asyncio
async def test_whitespace_clears_a_nullable_field(_needs_db: None, field: str) -> None:
    """Nullable columns take the other rule: blank means "clear it".

    Sending "" is how a broker clears one of these without a special endpoint,
    and whitespace-only has to mean the same thing — otherwise the Settings box
    renders as FILLED while every downstream gate, which strips before
    deciding, treats it as empty.
    """
    snap = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={field: "  Something  "})
        assert r.status_code == 200, r.text
        assert r.json()[field] == "Something"

        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={field: "   "})
        assert r.status_code == 200, r.text
        assert r.json()[field] is None, f"{field} kept whitespace instead of clearing"
    finally:
        await _restore(snap)


@pytest.mark.parametrize(
    "field",
    # All SIX, read off the table. The first version listed four by hand and
    # missed `languages` (TypeError in the normaliser loop) and `business_hours`
    # (NotNullViolation at the setattr) — the same defect, left half-fixed
    # inside the function that fixed it. The handler now derives this set from
    # `AgentSettings.__table__`, and this list is the check on that derivation.
    ["agency_name", "agent_persona", "greeting_template", "timezone",
     "languages", "business_hours"],
)
@pytest.mark.asyncio
async def test_an_explicit_null_on_a_required_field_is_refused(
    _needs_db: None, field: str
) -> None:
    """`{"agency_name": null}` used to reach Postgres and return a 500.

    `exclude_unset` does not catch it — a null that was sent IS set, it just has
    no legal value on a NOT NULL column — so it went through the handler's blind
    `setattr` and came back as a NotNullViolationError. The caller got a stack
    trace where they needed the name of the field they had just cleared.

    Preexisting, and reproduced before fixing: the PUT really did 500.
    """
    snap = await _snapshot()
    try:
        async with await _client() as c:
            r = await c.put("/api/v1/settings", json={field: None})
        assert r.status_code == 422, (
            f"{field}=null returned {r.status_code}, not a named refusal: {r.text[:200]}"
        )
        assert field in r.text, "the refusal does not name the field"

        async with await _client() as c:
            after = (await c.get("/api/v1/settings")).json()
        assert after[field] == snap[field], f"{field} changed despite the refusal"
    finally:
        await _restore(snap)


@pytest.mark.asyncio
async def test_the_required_set_is_derived_from_the_table(_needs_db: None) -> None:
    """The guard's field list must come from the schema, not from memory.

    A tuple of column names typed out beside another tuple of column names
    typed out is the shape that drifts, and this one had drifted before it
    shipped: four of the six NOT NULL columns. If someone adds a NOT NULL
    column to `agent_settings` and exposes it on the patch schema, this fails
    unless the derivation still holds.
    """
    from app.api.v1.settings import SettingsPatch, _not_nullable_fields
    from app.models.agent_settings import AgentSettings

    expected = {
        c.name for c in AgentSettings.__table__.columns if not c.nullable
    } & set(SettingsPatch.model_fields)
    assert _not_nullable_fields() == expected
    # A canary: an empty set would make the guard a no-op and every test above
    # would still pass on the 422s that Pydantic itself produces.
    assert len(expected) >= 6, f"only {len(expected)} required fields found"



@pytest.mark.asyncio
async def test_a_timezone_that_breaks_the_lookup_is_a_400_not_a_500(
    _needs_db: None,
) -> None:
    """`"America"` is a tzdata DIRECTORY, and it is short enough to look real.

    The inline `except (ZoneInfoNotFoundError, ValueError)` here caught two of
    the three exception types `ZoneInfo` raises, so `IsADirectoryError` escaped
    the handler and Postgres never even saw the request: HTTP 500 where the 400
    beside it was already correct for `"Mars/Olympus_Mons"`.

    This is the copy `visits.py` was modelled on, so the hole was inherited
    rather than invented — which is why the knowledge now lives in
    `app.services.timezones` and not in each call site.
    """
    async with await _client() as c:
        for bad in ("America", "Etc"):
            r = await c.put("/api/v1/settings", json={"timezone": bad})
            assert r.status_code == 400, f"{bad!r} -> {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_a_bytes_field_is_trimmed_like_a_string(_needs_db: None) -> None:
    """The docstring here argued for this and the code did not do it.

    Pydantic coerces bytes to str AFTER a `mode="before"` validator runs, so
    the `isinstance(value, str)` guard handed the model back raw bytes and
    `agency_name=b"  Ashly  "` was stored with its spaces — the exact value
    this validator exists to stop, described by its own docstring as the thing
    it prevented. Not reachable over JSON; reachable by any Python caller.
    """
    from app.api.v1.settings import SettingsPatch

    assert SettingsPatch(agency_name=b"  Ashly  ").agency_name == "Ashly"
    assert SettingsPatch(brokerage_line=b"   ").brokerage_line is None

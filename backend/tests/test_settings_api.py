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

_RESTORABLE = ("agency_name", "agency_phone", "agent_persona", "greeting_template", "languages", "business_hours")


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
        await c.put("/api/v1/settings", json=snapshot)


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

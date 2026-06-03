"""Calendar tab API — GET /visits (all), POST /visits (manual event), GET /visits/agenda.

Needs live Postgres. Each test cleans up the rows it creates so the suite stays
order-independent.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Visit


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — calendar API tests need live Postgres")
    return url


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _delete_visit(database_url: str, visit_id: int) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            v = (await s.execute(select(Visit).where(Visit.id == visit_id))).scalar_one_or_none()
            if v is not None:
                await s.delete(v)
                await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_manual_event_no_lead(database_url: str) -> None:
    title = f"Open house {uuid.uuid4().hex[:6]}"
    when = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    visit_id = None
    try:
        async with await _client() as c:
            r = await c.post(
                "/api/v1/visits",
                json={"title": title, "scheduled_at": when, "duration_minutes": 60},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        visit_id = body["id"]
        assert body["lead_id"] is None
        assert body["title"] == title
        assert body["calendar_provider"] == "manual"

        # Appears in the global list + the agenda.
        async with await _client() as c:
            all_ids = [v["id"] for v in (await c.get("/api/v1/visits")).json()]
            agenda = (await c.get("/api/v1/visits/agenda?days=30")).json()
        assert visit_id in all_ids
        agenda_item = next((i for i in agenda["items"] if i["kind"] == "event" and i["id"] == visit_id), None)
        assert agenda_item is not None
        assert agenda_item["title"] == title
    finally:
        if visit_id:
            await _delete_visit(database_url, visit_id)


@pytest.mark.asyncio
async def test_create_manual_event_validation(database_url: str) -> None:
    async with await _client() as c:
        # Missing title → 422.
        r = await c.post("/api/v1/visits", json={"scheduled_at": datetime.now(UTC).isoformat()})
        assert r.status_code == 422
        # Non-existent lead → 404.
        r2 = await c.post(
            "/api/v1/visits",
            json={"title": "x", "scheduled_at": datetime.now(UTC).isoformat(), "lead_id": 999999999},
        )
        assert r2.status_code == 404


@pytest.mark.asyncio
async def test_manual_event_uses_office_timezone(database_url: str) -> None:
    """When no tz is given, the event inherits the office timezone (not UTC)."""
    # Set office tz, create an event without a tz, assert it inherited it.
    visit_id = None
    snapshot = None
    try:
        async with await _client() as c:
            snapshot = (await c.get("/api/v1/settings")).json()["timezone"]
            await c.put("/api/v1/settings", json={"timezone": "America/Denver"})
            r = await c.post(
                "/api/v1/visits",
                json={"title": "tz test", "scheduled_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
            )
        assert r.status_code == 201, r.text
        visit_id = r.json()["id"]
        assert r.json()["timezone"] == "America/Denver"
    finally:
        if visit_id:
            await _delete_visit(database_url, visit_id)
        if snapshot:
            async with await _client() as c:
                await c.put("/api/v1/settings", json={"timezone": snapshot})

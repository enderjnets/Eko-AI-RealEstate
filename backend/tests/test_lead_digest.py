"""Tests for lead intelligence over the API — rescore-all, digest, score sort."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead, LeadIntent, LeadStatus


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — digest tests need live Postgres")
    return url


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert(database_url: str, **kw) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(**kw)
            s.add(lead)
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _delete(database_url: str, lead_id: int) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            row = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rescore_then_digest_ranks_and_excludes(database_url: str) -> None:
    sfx = uuid.uuid4().hex[:8].upper()
    now = datetime.now(UTC)
    hot = await _insert(
        database_url, phone=f"+1HOT{sfx}", name=f"Hot {sfx}",
        status=LeadStatus.QUALIFIED, intent=LeadIntent.BUY,
        budget_min=Decimal("600000"), budget_max=Decimal("850000"),
        zone="Brickell", property_type="condo", urgency="high", last_message_at=now,
    )
    lost = await _insert(
        database_url, phone=f"+1LOST{sfx}", name=f"Lost {sfx}",
        status=LeadStatus.LOST, intent=LeadIntent.BUY,
        budget_min=Decimal("600000"), budget_max=Decimal("850000"),
        zone="Brickell", property_type="condo", urgency="high", last_message_at=now,
    )
    try:
        async with await _client() as c:
            r = await c.post("/api/v1/leads/rescore-all")
            assert r.status_code == 200, r.text
            assert r.json()["rescored"] >= 2

            # The hot lead got a real score; the lost one was zeroed.
            hot_row = (await c.get(f"/api/v1/leads/{hot}")).json()
            lost_row = (await c.get(f"/api/v1/leads/{lost}")).json()
        assert hot_row["score"] >= 67
        assert hot_row["score_breakdown"]["tier"] == "hot"
        assert lost_row["score"] == 0

        async with await _client() as c:
            digest = (await c.get("/api/v1/leads/digest?limit=20")).json()
        ids = [d["id"] for d in digest]
        assert hot in ids
        assert lost not in ids  # closed leads never appear
        # Digest is sorted by score desc.
        scores = [d["score"] for d in digest]
        assert scores == sorted(scores, reverse=True)
    finally:
        await _delete(database_url, hot)
        await _delete(database_url, lost)


@pytest.mark.asyncio
async def test_list_default_sort_is_score(database_url: str) -> None:
    async with await _client() as c:
        await c.post("/api/v1/leads/rescore-all")
        body = (await c.get("/api/v1/leads?limit=100")).json()
    scores = [it["score"] for it in body["items"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_lead_out_has_score_fields(database_url: str) -> None:
    async with await _client() as c:
        body = (await c.get("/api/v1/leads?limit=1")).json()
    if body["items"]:
        it = body["items"][0]
        assert "score" in it
        assert "score_breakdown" in it

"""Tests for the analytics endpoint — envelope shape + invariants."""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — analytics needs live Postgres")


@pytest.mark.asyncio
async def test_analytics_envelope(_needs_db: None) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/analytics")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "total_leads", "funnel", "conversion_rate", "by_channel",
        "by_score_tier", "leads_per_day", "avg_first_response_seconds",
    ):
        assert key in body, key
    # Funnel has all 7 statuses; conversion is a ratio; tiers present.
    assert set(body["funnel"]) == {"new", "qualified", "visiting", "post_visit", "won", "lost", "paused"}
    assert 0.0 <= body["conversion_rate"] <= 1.0
    assert set(body["by_score_tier"]) == {"hot", "warm", "cold"}
    assert isinstance(body["leads_per_day"], list)

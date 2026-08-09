"""Tests for the properties API — sync, list/filter, detail, per-lead matches.

Needs live Postgres. Sync seeds the curated SIMULATED listings (idempotent), so
these tests also assert upsert behavior. Created leads are cleaned up.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead, LeadIntent


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — properties API tests need live Postgres")
    return url


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@asynccontextmanager
async def _operator_client() -> AsyncIterator[AsyncClient]:
    """A platform-operator session.

    `POST /properties/sync` drives the shared REcolorado feed — one licence
    quota and one cursor that every agency depends on — so it is operator-only
    rather than "any authenticated member". The routes refuse outright when
    AUTH_ENABLED is false, because the signing key in that mode is a constant
    published in this repository, so these settings are the configuration the
    endpoint actually requires.
    """
    from unittest.mock import patch as _patch

    from app.api.v1.auth import COOKIE_NAME
    from app.config import get_settings
    from app.models.organization import DEFAULT_ORG_ID
    from app.services.auth import make_token

    s = get_settings()
    with _patch.object(s, "AUTH_ENABLED", True), \
         _patch.object(s, "AUTH_SECRET", "properties-test-signing-secret"), \
         _patch.object(s, "PLATFORM_ADMIN_EMAILS", "operator@eko.com"):
        token = make_token(
            email="operator@eko.com", role="admin", org_id=DEFAULT_ORG_ID,
            superuser=True,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={COOKIE_NAME: token},
        ) as client:
            yield client



async def _insert_lead(database_url: str, **kw) -> int:
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


async def _delete_lead(database_url: str, lead_id: int) -> None:
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
async def test_sync_status_is_not_parsed_as_a_property_id(database_url: str) -> None:
    """Declared before /{property_id}; if the order ever flips this 422s or 404s.
    Null body is valid — the RESO feed may not have run yet."""
    async with await _client() as c:
        r = await c.get("/api/v1/properties/sync-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body is None or body["source"] == "reso"


@pytest.mark.asyncio
async def test_sync_is_idempotent(database_url: str) -> None:
    """First sync may create; a second sync creates nothing (all updates)."""
    async with _operator_client() as c:
        r1 = await c.post("/api/v1/properties/sync")
        assert r1.status_code == 200, r1.text
        r2 = await c.post("/api/v1/properties/sync")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["created"] == 0
    assert body2["total"] >= 5


@pytest.mark.asyncio
async def test_list_properties_envelope_and_filters(database_url: str) -> None:
    async with await _client() as c:
        await c.post("/api/v1/properties/sync")
        r = await c.get("/api/v1/properties?city=Miami&status=active&limit=100")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert all(it["status"] == "active" for it in body["items"])
    assert all("miami" in (it["city"] or "").lower() for it in body["items"])


@pytest.mark.asyncio
async def test_list_price_filter(database_url: str) -> None:
    async with await _client() as c:
        await c.post("/api/v1/properties/sync")
        r = await c.get("/api/v1/properties?max_price=5000&limit=100")
    assert r.status_code == 200, r.text
    # Only rentals (monthly) fall under 5000.
    for it in r.json()["items"]:
        if it["price"] is not None:
            assert float(it["price"]) <= 5000


@pytest.mark.asyncio
async def test_get_property_404(database_url: str) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/properties/999999999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_matches_404_for_missing_lead() -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/leads/999999999/matches")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_matches_buy_lead_brickell(database_url: str) -> None:
    """A Brickell buyer with an 850k budget gets Brickell SALE listings (no rentals)."""
    suffix = uuid.uuid4().hex[:8].upper()
    lead_id = await _insert_lead(
        database_url,
        phone=f"+1305MATCH{suffix}",
        name="Match Buyer",
        intent=LeadIntent.BUY,
        zone="Brickell",
        budget_max=850000,
    )
    try:
        async with await _client() as c:
            await c.post("/api/v1/properties/sync")
            r = await c.get(f"/api/v1/leads/{lead_id}/matches")
        assert r.status_code == 200, r.text
        matches = r.json()
        assert len(matches) >= 1
        for m in matches:
            assert "brickell" in (m["zone"] or "").lower()
            assert m["price"] is None or float(m["price"]) <= 850000 * 1.10
    finally:
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_matches_rent_lead_gets_only_rentals(database_url: str) -> None:
    """A Doral renter gets rental listings, never the for-sale ones."""
    suffix = uuid.uuid4().hex[:8].upper()
    lead_id = await _insert_lead(
        database_url,
        phone=f"+1305RENT{suffix}",
        name="Match Renter",
        intent=LeadIntent.RENT,
        zone="Doral",
        budget_max=2900,
    )
    try:
        async with await _client() as c:
            await c.post("/api/v1/properties/sync")
            r = await c.get(f"/api/v1/leads/{lead_id}/matches")
        assert r.status_code == 200, r.text
        matches = r.json()
        assert len(matches) >= 1
        for m in matches:
            # Rentals are cheap (monthly); a 700k sale price would mean a leak.
            assert float(m["price"]) <= 2900 * 1.10
    finally:
        await _delete_lead(database_url, lead_id)

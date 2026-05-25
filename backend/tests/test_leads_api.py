"""Tests for the leads API — list, detail, PATCH (Phase 2 dashboard ops)."""
from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead, LeadStatus


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — leads API tests need live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert_lead(database_url: str, phone: str) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Test Lead PATCH")
            s.add(lead)
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _delete_lead(database_url: str, phone: str) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            row = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_leads_returns_envelope() -> None:
    """Even an empty list returns the {total, items} envelope shape."""
    async with await _http_client() as client:
        resp = await client.get("/api/v1/leads?limit=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total" in body
    assert "items" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_get_lead_404_when_missing() -> None:
    async with await _http_client() as client:
        resp = await client.get("/api/v1/leads/999999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_lead_takeover_toggle(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666PATCH{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.patch(f"/api/v1/leads/{lead_id}", json={"human_takeover": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["human_takeover"] is True
        assert body["id"] == lead_id

        # Toggle back off
        async with await _http_client() as client:
            r2 = await client.patch(f"/api/v1/leads/{lead_id}", json={"human_takeover": False})
        assert r2.json()["human_takeover"] is False
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_patch_lead_status_and_zone_partial_update(database_url: str) -> None:
    """Only fields in the body are written; everything else is untouched."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666STAT{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.patch(
                f"/api/v1/leads/{lead_id}",
                json={"status": "won", "zone": "Salamanca"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "won"
        assert body["zone"] == "Salamanca"
        assert body["name"] == "Test Lead PATCH"  # unchanged
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_patch_empty_body_400(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666EMP{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.patch(f"/api/v1/leads/{lead_id}", json={})
        assert r.status_code == 400
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_patch_unknown_field_422() -> None:
    """`extra='forbid'` on the schema rejects unknown fields."""
    async with await _http_client() as client:
        r = await client.patch(
            "/api/v1/leads/1", json={"unknown_field": "x"}
        )
    # Pydantic returns 422 for schema violations, before our 404 check runs.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_invalid_status_422() -> None:
    async with await _http_client() as client:
        r = await client.patch("/api/v1/leads/1", json={"status": "not_a_real_status"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_lead_404_when_missing() -> None:
    async with await _http_client() as client:
        r = await client.patch("/api/v1/leads/999999999", json={"human_takeover": True})
    assert r.status_code == 404

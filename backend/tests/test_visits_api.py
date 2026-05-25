"""Visits API E2E — slots / book / list / cancel (against live DB, simulated Cal.com)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead, Visit, VisitStatus


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — visits API needs live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert_lead(database_url: str, phone: str) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Visit Test")
            s.add(lead)
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _cleanup_lead(database_url: str, phone: str) -> None:
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
async def test_slots_endpoint_returns_weekday_slots(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SLT{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.get(f"/api/v1/leads/{lead_id}/calendar/slots?days=7")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["days"] == 7
        assert len(body["slots"]) > 0
        # All returned starts must be on weekdays (Mon-Fri).
        for slot in body["slots"]:
            d = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
            assert d.weekday() < 5
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_slots_lead_not_found_returns_404() -> None:
    async with await _http_client() as client:
        r = await client.get("/api/v1/leads/999999999/calendar/slots?days=3")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_book_creates_visit_persists_with_calcom_sim_id(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666BOK{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    start_time = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        async with await _http_client() as client:
            r = await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={
                    "start_time": start_time.isoformat(),
                    "duration_minutes": 30,
                    "property_address": "Calle Fuencarral 100, Madrid",
                    "notes": "primera visita",
                    "timezone": "Europe/Madrid",
                },
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["lead_id"] == lead_id
        assert body["calendar_provider"] == "calcom"
        assert body["external_booking_id"].startswith("calcom-sim-")
        assert body["status"] == "scheduled"
        assert body["duration_minutes"] == 30
        assert body["property_address"] == "Calle Fuencarral 100, Madrid"
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_list_visits_returns_inserted_one(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666LST{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    start_time = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        async with await _http_client() as client:
            await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={"start_time": start_time.isoformat(), "timezone": "Europe/Madrid"},
            )
            r = await client.get(f"/api/v1/leads/{lead_id}/visits")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["lead_id"] == lead_id
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_cancel_visit_flips_status_to_cancelled(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CXL{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    start_time = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        async with await _http_client() as client:
            book = await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={"start_time": start_time.isoformat()},
            )
            visit_id = book.json()["id"]
            cancel = await client.post(
                f"/api/v1/visits/{visit_id}/cancel",
                json={"reason": "cliente reagendó"},
            )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "cancelled"

        # Cancelling again returns 400 (terminal status).
        async with await _http_client() as client:
            second_cancel = await client.post(f"/api/v1/visits/{visit_id}/cancel", json={})
        assert second_cancel.status_code == 400
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_slots_excludes_already_booked_starts(database_url: str) -> None:
    """If lead has a SCHEDULED visit at T, /slots must not return T again."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666BSY{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    # Pick the next weekday 10 AM UTC for predictability.
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    target = (now + timedelta(days=1)).replace(hour=10)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    try:
        async with await _http_client() as client:
            await client.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={"start_time": target.isoformat(), "timezone": "UTC"},
            )
            r = await client.get(f"/api/v1/leads/{lead_id}/calendar/slots?days=7&timezone=UTC")
        body = r.json()
        slot_starts = {
            datetime.fromisoformat(s["start"].replace("Z", "+00:00")) for s in body["slots"]
        }
        assert target not in slot_starts
    finally:
        await _cleanup_lead(database_url, phone)

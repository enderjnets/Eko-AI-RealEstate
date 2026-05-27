"""Tests for discovery — SIMULATED search + import upsert."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Lead
from app.services.discovery import (
    BusinessDTO,
    discover,
    import_business_leads,
    lead_identifier,
    sanitize_email,
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — discovery import test needs live Postgres")
    return url


# ── SIMULATED search (pure) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_simulated_search_returns_businesses() -> None:
    res = await discover(query="mortgage", city="Denver", sources=["google_maps", "yelp"])
    assert len(res) >= 1
    assert all(isinstance(b, BusinessDTO) for b in res)
    assert all(b.source in ("google_maps", "yelp") for b in res)


@pytest.mark.asyncio
async def test_simulated_source_filtering() -> None:
    only_sos = await discover(query="LLC", city="Denver", sources=["colorado_sos"])
    assert only_sos
    assert all(b.source == "colorado_sos" for b in only_sos)


@pytest.mark.asyncio
async def test_simulated_max_results_cap() -> None:
    res = await discover(query="", city="", max_results=2, sources=list(("google_maps", "yelp", "linkedin", "colorado_sos")))
    assert len(res) <= 2


def test_sanitize_email() -> None:
    assert sanitize_email("Info@Example2.com") == "info@example2.com"
    assert sanitize_email("bad@example.com") is None      # placeholder domain
    assert sanitize_email("not-an-email") is None
    assert sanitize_email(None) is None


def test_lead_identifier_fallback() -> None:
    # phone wins, then email, then website
    assert lead_identifier(BusinessDTO("A", "yelp", phone="+13035550000", email="a@b.com")) == "+13035550000"
    assert lead_identifier(BusinessDTO("A", "yelp", email="a@b.com", website="https://x")) == "a@b.com"
    assert lead_identifier(BusinessDTO("A", "linkedin", website="https://linkedin.com/in/a")) == "https://linkedin.com/in/a"
    # no contact at all → stable synthetic key (so it still imports + dedupes)
    syn = lead_identifier(BusinessDTO("Cherry Creek Renovations LLC", "colorado_sos", city="Denver"))
    assert syn == "discovery:colorado_sos:cherry-creek-renovations-llc:denver"
    # deterministic
    assert syn == lead_identifier(BusinessDTO("Cherry Creek Renovations LLC", "colorado_sos", city="Denver"))


# ── Import (live DB) ───────────────────────────────────────────────────────


async def _delete_lead(url: str, phone: str) -> None:
    engine = create_async_engine(url, echo=False, future=True)
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
async def test_import_creates_and_dedupes(database_url: str) -> None:
    phone = f"+1303DISC{uuid.uuid4().hex[:6].upper()}"
    dto = BusinessDTO(business_name="Disc Test Co", source="google_maps", phone=phone,
                      category="Mortgage broker", city="Denver", state="CO")
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            r1 = await import_business_leads([dto], s)
            assert r1["created"] == 1
            assert len(r1["lead_ids"]) == 1  # IDs returned so the caller can enrich
            # Re-import the same identifier → skipped (dedupe by unique phone).
            r2 = await import_business_leads([dto], s)
            assert r2["created"] == 0 and r2["skipped"] == 1
            assert r2["lead_ids"] == []
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            assert lead.name == "Disc Test Co"
            assert lead.meta.get("source") == "google_maps"
            assert lead.meta.get("discovery") is True
    finally:
        await engine.dispose()
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_import_no_contact_creates_synthetic_id(database_url: str) -> None:
    # Colorado SOS / LinkedIn carry no phone/email — these MUST still import
    # (was the bug: they were silently skipped and never reached /leads).
    name = f"No Contact LLC {uuid.uuid4().hex[:6]}"
    dto = BusinessDTO(business_name=name, source="colorado_sos", city="Denver", category="LLC")
    ident = lead_identifier(dto)
    assert ident.startswith("discovery:colorado_sos:")
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            r = await import_business_leads([dto], s)
            assert r["created"] == 1 and len(r["lead_ids"]) == 1
            lead = (await s.execute(select(Lead).where(Lead.phone == ident))).scalar_one()
            assert lead.name == name
            assert lead.meta.get("synthetic_identifier") is True
            # re-import dedupes on the synthetic key
            r2 = await import_business_leads([dto], s)
            assert r2["created"] == 0 and r2["skipped"] == 1
    finally:
        await engine.dispose()
        await _delete_lead(database_url, ident)

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


# ── SIMULATED search by real-estate category (pure) ───────────────────────


@pytest.mark.asyncio
async def test_simulated_category_returns_realestate_leads() -> None:
    res = await discover(category="fsbo", city="Denver")
    assert len(res) >= 1
    assert all(isinstance(b, BusinessDTO) for b in res)
    assert all(b.source == "fsbo" for b in res)        # category tagged on source
    assert all(b.motivation for b in res)              # real-estate motivation present


@pytest.mark.asyncio
async def test_simulated_category_filtering() -> None:
    expired = await discover(category="expired", city="Denver")
    assert expired and all(b.source == "expired" for b in expired)
    # a different category yields different leads
    fsbo = await discover(category="fsbo", city="Denver")
    assert {b.business_name for b in expired}.isdisjoint({b.business_name for b in fsbo})


@pytest.mark.asyncio
async def test_simulated_unknown_category_defaults() -> None:
    res = await discover(category="not_a_category", city="Denver")
    assert all(b.source == "fsbo" for b in res)        # defaults to fsbo


@pytest.mark.asyncio
async def test_simulated_max_results_cap() -> None:
    res = await discover(category="fsbo", city="", max_results=1)
    assert len(res) <= 1


@pytest.mark.asyncio
async def test_real_mode_falls_back_to_simulated_when_no_provider(monkeypatch) -> None:
    # In real mode, a category with no wired provider (fsbo) must still return the
    # curated leads so every category stays demoable.
    from app.services import discovery as disc

    class _S:
        DISCOVERY_SIMULATED = False
        ATTOM_API_KEY = ""
        YELP_API_KEY = ""
        SERPAPI_API_KEY = ""
        OUTSCRAPER_API_KEY = ""

    monkeypatch.setattr(disc, "get_settings", lambda: _S())
    res = await disc.discover(category="fsbo", city="Denver")
    assert res and all(b.source == "fsbo" for b in res)


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

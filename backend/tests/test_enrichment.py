"""Tests for lead enrichment — pure coercion + LLM enrichment (mocked) over a live lead."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Lead, LeadIntent, LeadStatus
from app.services.enrichment import _coerce, discovery_score, enrich_lead
from app.services.llm import LLMResult, LLMUnavailable


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — enrichment test needs live Postgres")
    return url


def _reply(text: str) -> LLMResult:
    return LLMResult(text=text, provider="kimi", model="kimi-for-coding", input_tokens=10, output_tokens=10)


# ── Pure coercion ──────────────────────────────────────────────────────────


def test_coerce_clamps_partner_type_and_tags() -> None:
    e = _coerce({"partner_type": "BANANA", "tags": "single", "business_type": "Mortgage broker"})
    assert e.partner_type == "other"  # unknown → other
    assert e.tags == ["single"]       # string → list
    assert e.business_type == "Mortgage broker"


def test_coerce_clamps_intent_and_relevance() -> None:
    assert _coerce({"intent": "BUY"}).intent == "buy"           # normalized
    assert _coerce({"intent": "nonsense"}).intent == "other"    # invalid → other
    assert _coerce({"relevance": 99}).relevance == 10           # clamped 0-10
    assert _coerce({"relevance": "bad"}).relevance == 5         # non-int → default


def test_discovery_score_tiers() -> None:
    # referral partner + high relevance + real contact + website → hot
    hot, b = discovery_score("referral_partner", 10, has_contact=True, has_website=True)
    assert hot >= 67 and b["tier"] == "hot"
    assert b["source"] == "discovery_enrichment"
    # other + low relevance + no contact → cold
    cold, b2 = discovery_score("other", 0, has_contact=False, has_website=False)
    assert cold < 34 and b2["tier"] == "cold"


def test_coerce_keeps_valid_partner_type_and_caps_tags() -> None:
    e = _coerce({"partner_type": "Referral_Partner", "tags": ["a", "b", "c", "d", "e", ""]})
    assert e.partner_type == "referral_partner"  # normalized lowercase
    assert e.tags == ["a", "b", "c", "d"]        # capped at 4, empties dropped


# ── enrich_lead (live DB, mocked LLM) ───────────────────────────────────────


async def _delete(url: str, phone: str) -> None:
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


async def _make_lead(url: str, phone: str, meta: dict) -> int:
    engine = create_async_engine(url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Mile High Mortgage", status=LeadStatus.NEW, zone="Denver", meta=meta)
            s.add(lead)
            await s.commit()
            await s.refresh(lead)
            return lead.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_enrich_lead_happy_path(database_url: str) -> None:
    phone = f"discovery:colorado_sos:enrich-ok-{uuid.uuid4().hex[:6]}"
    await _make_lead(database_url, phone, {"source": "colorado_sos", "category": "LLC", "synthetic_identifier": True})
    payload = ('{"business_type":"Mortgage broker","partner_type":"referral_partner","intent":"buy",'
               '"relevance":9,"summary":"Local mortgage shop","outreach_angle":"Offer co-marketing",'
               '"tags":["mortgage","partner"]}')
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            with patch("app.services.enrichment.generate_reply", AsyncMock(return_value=_reply(payload))):
                out = await enrich_lead(lead, s)
            assert out["status"] == "ok"
            assert out["partner_type"] == "referral_partner"
            assert out["contact_missing"] is True  # synthetic id → no real contact
            assert out["score"] > 0 and out["tier"] in ("hot", "warm", "cold")
            assert "enriched_at" in out
            # classification + score persisted to the lead (drives the badges)
            refreshed = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            assert refreshed.meta["enrichment"]["business_type"] == "Mortgage broker"
            assert refreshed.intent == LeadIntent.BUY
            assert refreshed.score > 0
            assert refreshed.score_breakdown["source"] == "discovery_enrichment"
    finally:
        await engine.dispose()
        await _delete(database_url, phone)


@pytest.mark.asyncio
async def test_enrich_lead_graceful_on_llm_failure(database_url: str) -> None:
    phone = f"+1303ENR{uuid.uuid4().hex[:6].upper()}"
    await _make_lead(database_url, phone, {"source": "yelp", "phone": phone})
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            with patch("app.services.enrichment.generate_reply", AsyncMock(side_effect=LLMUnavailable("down"))):
                out = await enrich_lead(lead, s)
            assert out["status"] == "failed"      # never raises
            assert out["contact_missing"] is False  # had a real phone
    finally:
        await engine.dispose()
        await _delete(database_url, phone)


@pytest.mark.asyncio
async def test_enrich_lead_graceful_on_bad_json(database_url: str) -> None:
    phone = f"+1303BAD{uuid.uuid4().hex[:6].upper()}"
    await _make_lead(database_url, phone, {"source": "yelp", "phone": phone})
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            with patch("app.services.enrichment.generate_reply", AsyncMock(return_value=_reply("sorry no json"))):
                out = await enrich_lead(lead, s)
            assert out["status"] == "failed"
    finally:
        await engine.dispose()
        await _delete(database_url, phone)

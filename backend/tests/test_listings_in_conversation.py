"""The agent offers REAL matched listings in-conversation (Phase 10)."""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead, Property, PropertySource, PropertyStatus
from app.services.classifier import IntentEntities, IntentResult
from app.services.llm import LLMResult


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — needs live Postgres")
    return url


async def _cleanup(url: str, phone: str) -> None:
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
async def test_agent_gets_real_listings_in_system_prompt(database_url: str) -> None:
    sfx = uuid.uuid4().hex[:8].upper()
    phone = f"+1305LST{sfx[:4]}"
    form = {
        "MessageSid": f"SM{sfx}",
        "From": phone,
        "To": "+13055559999",
        "Body": "Do you have any 2-bed condos in Brickell under 850k?",
    }
    fake_intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.9,
        entities=IntentEntities(zone="Brickell", budget_max=850000, property_type="condo"),
    )
    captured: dict[str, str] = {}

    async def _capture(*, messages, system, **kw):  # noqa: ANN001
        captured["system"] = system
        return LLMResult(text="Sure! I have a couple of Brickell condos.", provider="kimi",
                         model="kimi-for-coding", input_tokens=50, output_tokens=20)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/v1/properties/sync")  # ensure listings exist
            with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
                with patch("app.services.conversation.generate_reply", side_effect=_capture):
                    r = await c.post("/api/v1/webhooks/sms", data=form)
        assert r.status_code == 200, r.text
        assert "system" in captured, "generate_reply was not called"
        sys_prompt = captured["system"]
        assert "LISTINGS DISPONIBLES" in sys_prompt
        assert "Brickell" in sys_prompt  # a real matched listing was injected
    finally:
        await _cleanup(database_url, phone)


@pytest.mark.asyncio
async def test_idx_broker_attribution_injected(database_url: str) -> None:
    """A listing shown to a lead must credit the listing broker (IDX rule). The
    office name (captured from the RESO feed into raw.list_office_name) appears as
    'Cortesía de …' in the system prompt."""
    sfx = uuid.uuid4().hex[:8].upper()
    phone = f"+1305ATT{sfx[:4]}"
    zone = f"Testville{sfx}"
    office = "REcolorado Partner Realty"

    engine = create_async_engine(database_url, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with Session() as s:
        s.add(
            Property(
                source=PropertySource.MANUAL,
                external_id=f"ATTR-{sfx}",
                status=PropertyStatus.ACTIVE,
                title=f"Casa en {zone}",
                property_type="house",
                zone=zone,
                price=Decimal("500000"),
                bedrooms=3,
                raw={"listing_type": "sale", "list_office_name": office},
            )
        )
        await s.commit()

    form = {
        "MessageSid": f"SM{sfx}",
        "From": phone,
        "To": "+13055559999",
        "Body": f"Any houses in {zone} around 600k?",
    }
    fake_intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.9,
        entities=IntentEntities(zone=zone, budget_max=850000, property_type="house"),
    )
    captured: dict[str, str] = {}

    async def _capture(*, messages, system, **kw):  # noqa: ANN001
        captured["system"] = system
        return LLMResult(
            text="Tengo una opción.", provider="kimi", model="kimi-for-coding",
            input_tokens=50, output_tokens=20,
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with patch(
                "app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)
            ):
                with patch("app.services.conversation.generate_reply", side_effect=_capture):
                    r = await c.post("/api/v1/webhooks/sms", data=form)
        assert r.status_code == 200, r.text
        assert "system" in captured, "generate_reply was not called"
        assert f"Cortesía de {office}" in captured["system"]
    finally:
        await _cleanup(database_url, phone)
        async with Session() as s:
            row = (
                await s.execute(
                    select(Property).where(Property.external_id == f"ATTR-{sfx}")
                )
            ).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
        await engine.dispose()

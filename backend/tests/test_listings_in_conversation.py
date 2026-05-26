"""The agent offers REAL matched listings in-conversation (Phase 10)."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Lead
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

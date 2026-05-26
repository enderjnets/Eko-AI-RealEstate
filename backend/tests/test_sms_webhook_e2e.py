"""End-to-end test for the SMS webhook: Twilio form POST → orchestrator → DB."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Conversation, Lead, Message, MessageDirection
from app.services.classifier import IntentEntities, IntentResult
from app.services.llm import LLMResult


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — SMS E2E needs live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _cleanup(database_url: str, phone: str) -> None:
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
async def test_inbound_sms_creates_lead_and_replies(database_url: str) -> None:
    """SIMULATED mode skips signature validation (dev path)."""
    sfx = uuid.uuid4().hex[:8].upper()
    phone = f"+1305555{sfx[:4]}"
    sid = f"SM{sfx}"
    form = {
        "MessageSid": sid,
        "From": phone,
        "To": "+13055559999",
        "Body": "Hi, looking for a 2BR condo in Brickell under 800k",
    }

    fake_intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.9,
        entities=IntentEntities(zone="Brickell", budget_max=800000, property_type="condo"),
    )
    fake_reply = LLMResult(
        text="Hi! Great, I have a couple of Brickell condos in that range.",
        provider="kimi", model="kimi-for-coding", input_tokens=70, output_tokens=30,
    )

    try:
        with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
            with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
                async with await _http_client() as client:
                    resp = await client.post("/api/v1/webhooks/sms", data=form)

        assert resp.status_code == 200, resp.text
        assert "Response" in resp.text  # empty TwiML

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            assert lead.intent is not None and lead.intent.value == "buy"
            assert lead.zone == "Brickell"

            conv = (
                await s.execute(select(Conversation).where(Conversation.lead_id == lead.id))
            ).scalar_one()
            assert conv.channel == "sms"
            msgs = (
                await s.execute(
                    select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
                )
            ).scalars().all()
            assert len(msgs) == 2
            inbound = next(m for m in msgs if m.direction == MessageDirection.INBOUND)
            outbound = next(m for m in msgs if m.direction == MessageDirection.OUTBOUND)
            assert inbound.external_id == sid
            assert outbound.external_id.startswith("SM_SIMULATED_")
            assert outbound.delivery_status.value == "sent"
        await engine.dispose()
    finally:
        await _cleanup(database_url, phone)


@pytest.mark.asyncio
async def test_inbound_sms_idempotent(database_url: str) -> None:
    """Twilio retries the same MessageSid → second POST must not duplicate."""
    sfx = uuid.uuid4().hex[:8].upper()
    phone = f"+1305556{sfx[:4]}"
    sid = f"SM{sfx}"
    form = {"MessageSid": sid, "From": phone, "To": "+13055559999", "Body": "hola"}

    fake_intent = IntentResult(intent="other", confidence=0.2, entities=IntentEntities())  # type: ignore[arg-type]
    fake_reply = LLMResult(text="¡Hola!", provider="kimi", model="kimi-for-coding", input_tokens=5, output_tokens=3)

    try:
        with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
            with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
                async with await _http_client() as client:
                    await client.post("/api/v1/webhooks/sms", data=form)
                    await client.post("/api/v1/webhooks/sms", data=form)  # retry

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            conv = (
                await s.execute(select(Conversation).where(Conversation.lead_id == lead.id))
            ).scalar_one()
            inbound = (
                await s.execute(
                    select(Message).where(
                        Message.conversation_id == conv.id,
                        Message.direction == MessageDirection.INBOUND,
                    )
                )
            ).scalars().all()
        await engine.dispose()
        assert len(inbound) == 1  # the retry was deduped on external_id
    finally:
        await _cleanup(database_url, phone)

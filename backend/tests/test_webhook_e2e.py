"""End-to-end webhook tests.

GET handshake: pure HTTP, no DB. POST inbound flow: mocks the LLM (no real API
calls), uses the real live DB (cleanup with unique phone suffixes), verifies
that Lead + Conversation + 2 Messages (1 in / 1 out) land correctly.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.main import app
from app.models import (
    Conversation,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.services.classifier import IntentEntities, IntentResult
from app.services.llm import LLMResult


FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp_payloads"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — webhook E2E requires live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── GET handshake ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_handshake_accepts_correct_token() -> None:
    # Read the live env value rather than hardcoding; the dev .env on the ROG
    # sets a longer token than the config.py default.
    token = get_settings().WHATSAPP_VERIFY_TOKEN
    async with await _http_client() as client:
        resp = await client.get(
            "/api/v1/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": token,
                "hub.challenge": "12345",
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.text == "12345"


@pytest.mark.asyncio
async def test_verify_handshake_rejects_wrong_token() -> None:
    async with await _http_client() as client:
        resp = await client.get(
            "/api/v1/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token-xyz",
                "hub.challenge": "12345",
            },
        )
    assert resp.status_code == 403


# ── POST inbound flow ──────────────────────────────────────────────────


def _load_text_payload(test_phone: str, test_msg_id: str) -> dict:
    """Load the canonical inbound_text.json fixture and inject unique IDs."""
    payload = json.loads((FIXTURES / "inbound_text.json").read_text())
    value = payload["entry"][0]["changes"][0]["value"]
    value["contacts"][0]["wa_id"] = test_phone
    value["messages"][0]["from"] = test_phone
    value["messages"][0]["id"] = test_msg_id
    return payload


@pytest.mark.asyncio
async def test_inbound_text_creates_lead_and_replies(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:10].upper()
    test_phone = f"34666E2E{suffix}"
    test_msg_id = f"wamid.E2E_TEXT_{suffix}"

    payload = _load_text_payload(test_phone, test_msg_id)

    fake_intent = IntentResult(
        intent="rent",  # type: ignore[arg-type] — Pydantic coerces from string
        confidence=0.95,
        entities=IntentEntities(zone="Malasaña", budget_max=1200, property_type="apartment", urgency="weeks"),
    )
    fake_reply = LLMResult(
        text="¡Hola! Tenemos opciones en Malasaña dentro de tu presupuesto. ¿Cuándo te vendría bien una visita?",
        provider="kimi",
        model="kimi-for-coding",
        input_tokens=120,
        output_tokens=45,
    )

    try:
        with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
            with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
                async with await _http_client() as client:
                    resp = await client.post("/api/v1/webhooks/whatsapp", json=payload)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["processed"] == 1
        result = body["results"][0]
        assert result["status"] == "ok"
        assert result["is_new_lead"] is True
        assert result["llm_provider"] == "kimi"
        # In simulated mode the send succeeds with a fake wamid.
        assert result["outbound_status"] == "sent"
        lead_id = result["lead_id"]

        # ── Verify DB state ─────────────────────────────────────────
        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            assert lead.phone == test_phone
            assert lead.name == "Juan García"
            assert lead.zone == "Malasaña"
            assert lead.budget_max == 1200
            assert lead.intent is not None and lead.intent.value == "rent"

            conv = (await s.execute(select(Conversation).where(Conversation.lead_id == lead_id))).scalar_one()
            msgs = (
                await s.execute(
                    select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
                )
            ).scalars().all()
            assert len(msgs) == 2
            assert msgs[0].direction == MessageDirection.INBOUND
            assert msgs[0].sender == MessageSender.LEAD
            assert msgs[0].wa_message_id == test_msg_id
            assert msgs[1].direction == MessageDirection.OUTBOUND
            assert msgs[1].sender == MessageSender.AGENT
            assert msgs[1].wa_status == MessageStatus.SENT
            assert msgs[1].llm_provider == "kimi"
            assert msgs[1].wa_message_id is not None
            assert msgs[1].wa_message_id.startswith("wamid.SIMULATED_")
        await engine.dispose()
    finally:
        await _cleanup_lead(database_url, test_phone)


@pytest.mark.asyncio
async def test_inbound_same_message_id_is_idempotent(database_url: str) -> None:
    """Meta retries on non-200; we must not double-process the same wa_message_id."""
    suffix = uuid.uuid4().hex[:10].upper()
    test_phone = f"34666IDM{suffix}"
    test_msg_id = f"wamid.IDM_{suffix}"

    payload = _load_text_payload(test_phone, test_msg_id)

    fake_intent = IntentResult(intent="other", confidence=0.5, entities=IntentEntities())  # type: ignore[arg-type]
    fake_reply = LLMResult(text="Hola, ¿en qué te ayudo?", provider="kimi", model="kimi-for-coding", input_tokens=10, output_tokens=8)

    try:
        with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
            with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
                async with await _http_client() as client:
                    r1 = await client.post("/api/v1/webhooks/whatsapp", json=payload)
                    r2 = await client.post("/api/v1/webhooks/whatsapp", json=payload)

        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        body1 = r1.json()
        body2 = r2.json()
        assert body1["results"][0]["status"] == "ok", f"first POST not ok: {body1}"
        assert body2["results"][0]["status"] == "duplicate", f"second POST not duplicate: {body2}"

        # Verify only ONE inbound message + ONE outbound message exist.
        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == test_phone))).scalar_one()
            conv = (await s.execute(select(Conversation).where(Conversation.lead_id == lead.id))).scalar_one()
            msgs = (await s.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
            assert len(msgs) == 2  # 1 inbound + 1 outbound only (NOT 4)
        await engine.dispose()
    finally:
        await _cleanup_lead(database_url, test_phone)


async def _cleanup_lead(database_url: str, phone: str) -> None:
    """Delete a test lead (cascade removes conv + messages)."""
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with Session() as s:
        lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one_or_none()
        if lead is not None:
            await s.delete(lead)
            await s.commit()
    await engine.dispose()

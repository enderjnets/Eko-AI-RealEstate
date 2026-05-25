"""Phase 4 — composer endpoints: POST /messages + POST /suggestions."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import (
    Conversation,
    ConversationStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.services.llm import LLMResult


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — composer tests need live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert_lead_with_whatsapp_conv(database_url: str, phone: str) -> int:
    """Create a Lead + active WhatsApp Conversation + 1 inbound Message."""
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Compose Test")
            s.add(lead)
            await s.flush()
            conv = Conversation(lead_id=lead.id, channel="whatsapp", status=ConversationStatus.ACTIVE)
            s.add(conv)
            await s.flush()
            s.add(Message(
                conversation_id=conv.id,
                direction=MessageDirection.INBOUND,
                sender=MessageSender.LEAD,
                content="Hola, busco piso en Madrid",
                external_id=f"wamid.compose_in_{uuid.uuid4().hex[:8]}",
                delivery_status=MessageStatus.DELIVERED,
            ))
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


# ── POST /messages (human send) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_human_send_whatsapp_routes_via_simulated_dispatch(database_url: str) -> None:
    """SIMULATED whatsapp send → returns synthetic wamid → outbound persists SENT."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SEND{suffix}"
    lead_id = await _insert_lead_with_whatsapp_conv(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.post(
                f"/api/v1/leads/{lead_id}/messages",
                json={"text": "Hola Juan, te paso opciones en breve."},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["channel"] == "whatsapp"
        assert body["outbound_status"] == "sent"
        assert body["outbound_id"] is not None

        # Verify the persisted Message is HUMAN-sender + OUTBOUND.
        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            msg = (await s.execute(select(Message).where(Message.id == body["outbound_id"]))).scalar_one()
            assert msg.sender == MessageSender.HUMAN
            assert msg.direction == MessageDirection.OUTBOUND
            assert msg.content == "Hola Juan, te paso opciones en breve."
            assert msg.delivery_status == MessageStatus.SENT
            assert msg.external_id is not None and msg.external_id.startswith("wamid.SIMULATED_")
        await engine.dispose()
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_human_send_lead_not_found_returns_error_payload() -> None:
    async with await _http_client() as client:
        r = await client.post("/api/v1/leads/999999999/messages", json={"text": "hi"})
    assert r.status_code == 200, r.text  # contract: 200 + error in body
    body = r.json()
    assert body["status"] == "error"
    assert body["error"] == "lead_not_found"


@pytest.mark.asyncio
async def test_human_send_empty_text_rejects_400() -> None:
    async with await _http_client() as client:
        r = await client.post("/api/v1/leads/1/messages", json={"text": "   "})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_human_send_lead_without_conversation_returns_error(database_url: str) -> None:
    """Bare Lead (no Conversation) → no_active_conversation error."""
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666NOCV{suffix}"
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="No conv")
            s.add(lead)
            await s.commit()
            lead_id = lead.id
        async with await _http_client() as client:
            r = await client.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "hola"})
        assert r.status_code == 200, r.text
        assert r.json()["error"] == "no_active_conversation"
    finally:
        await engine.dispose()
        await _cleanup_lead(database_url, phone)


# ── POST /suggestions ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suggestions_happy_path(database_url: str) -> None:
    """LLM returns a valid JSON array → 3 trimmed suggestions returned."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SUG{suffix}"
    lead_id = await _insert_lead_with_whatsapp_conv(database_url, phone)
    fake_reply = LLMResult(
        text='["¡Hola! ¿Qué presupuesto manejas?", "Encantado, te paso opciones esta tarde.", "Perfecto, ¿prefieres alquiler o compra?"]',
        provider="kimi", model="kimi-for-coding", input_tokens=120, output_tokens=80,
    )
    try:
        with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
            async with await _http_client() as client:
                r = await client.post(f"/api/v1/leads/{lead_id}/suggestions", json={"count": 3})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["suggestions"]) == 3
        assert body["suggestions"][0].startswith("¡Hola!")
        assert body["provider"] == "kimi"
        assert body["error"] is None
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_suggestions_with_prose_around_json_extracts_array(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SGP{suffix}"
    lead_id = await _insert_lead_with_whatsapp_conv(database_url, phone)
    fake_reply = LLMResult(
        text='Aquí tienes las opciones:\n\n["opción A", "opción B"]\n\nEspero te sirvan.',
        provider="kimi", model="kimi-for-coding", input_tokens=80, output_tokens=20,
    )
    try:
        with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
            async with await _http_client() as client:
                r = await client.post(f"/api/v1/leads/{lead_id}/suggestions", json={"count": 2})
        body = r.json()
        assert body["suggestions"] == ["opción A", "opción B"]
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_suggestions_invalid_json_returns_empty_with_error(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SGE{suffix}"
    lead_id = await _insert_lead_with_whatsapp_conv(database_url, phone)
    fake_reply = LLMResult(
        text="No JSON here, just prose that confuses the parser.",
        provider="kimi", model="kimi-for-coding", input_tokens=50, output_tokens=12,
    )
    try:
        with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
            async with await _http_client() as client:
                r = await client.post(f"/api/v1/leads/{lead_id}/suggestions", json={"count": 3})
        body = r.json()
        assert body["suggestions"] == []
        assert body["error"] is not None
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_suggestions_lead_not_found_returns_empty() -> None:
    async with await _http_client() as client:
        r = await client.post("/api/v1/leads/999999999/suggestions", json={"count": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["suggestions"] == []
    assert body["error"] == "lead_not_found"


@pytest.mark.asyncio
async def test_suggestions_count_clamps_to_5_max(database_url: str) -> None:
    """Schema clamps count to [1, 5] inside the endpoint."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666SGM{suffix}"
    lead_id = await _insert_lead_with_whatsapp_conv(database_url, phone)
    fake_reply = LLMResult(
        text='["a","b","c","d","e","f","g"]',
        provider="kimi", model="kimi-for-coding", input_tokens=50, output_tokens=20,
    )
    try:
        with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
            async with await _http_client() as client:
                r = await client.post(f"/api/v1/leads/{lead_id}/suggestions", json={"count": 99})
        body = r.json()
        # endpoint clamps requested count to 5, then list is trimmed.
        assert len(body["suggestions"]) == 5
    finally:
        await _cleanup_lead(database_url, phone)

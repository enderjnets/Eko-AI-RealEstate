"""End-to-end test for the email webhook: POST → orchestrator → DB rows."""
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
        pytest.skip("DATABASE_URL not set — email E2E needs live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _cleanup_lead(database_url: str, identifier: str) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            row = (await s.execute(select(Lead).where(Lead.phone == identifier))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inbound_email_creates_lead_and_replies(database_url: str) -> None:
    """SIMULATED mode lets us skip the Svix signature check (dev path)."""
    suffix = uuid.uuid4().hex[:8].upper()
    identifier = f"juan.test+{suffix}@example.com"
    msg_id = f"<msg-{suffix}@example.com>"

    payload = {
        "type": "email.received",
        "data": {
            "id": f"resend_{suffix}",
            "from": identifier,
            "from_name": "Juan E2E",
            "to": ["info@realtor-demo.com"],
            "subject": "Consulta — piso en Salamanca",
            "text": "Hola, busco piso de 3 habitaciones en Salamanca, presupuesto 1800€",
            "headers": {"message-id": msg_id},
        },
    }

    fake_intent = IntentResult(
        intent="rent",  # type: ignore[arg-type]
        confidence=0.9,
        entities=IntentEntities(zone="Salamanca", budget_max=1800, property_type="apartment"),
    )
    fake_reply = LLMResult(
        text="¡Hola Juan! Gracias por escribirnos. Tenemos opciones en Salamanca dentro de tu presupuesto.",
        provider="kimi",
        model="kimi-for-coding",
        input_tokens=80,
        output_tokens=40,
    )

    try:
        with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
            with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
                async with await _http_client() as client:
                    resp = await client.post("/api/v1/webhooks/email", json=payload)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        result = body["results"][0]
        assert result["status"] == "ok"
        assert result["channel"] == "email"
        assert result["is_new_lead"] is True
        lead_id = result["lead_id"]

        # Verify DB shape
        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            # Case-folded on the way in: providers do not distinguish
            # Nat@x.com from nat@x.com, and treating them as two people is how
            # one human becomes two leads and an opt-out on one protects
            # neither.
            assert lead.phone == identifier.lower()  # email lives in the phone column
            assert lead.zone == "Salamanca"
            assert lead.budget_max == 1800
            assert lead.intent is not None and lead.intent.value == "rent"

            conv = (
                await s.execute(
                    select(Conversation).where(Conversation.lead_id == lead_id)
                )
            ).scalar_one()
            assert conv.channel == "email"
            msgs = (
                await s.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.created_at)
                )
            ).scalars().all()
            assert len(msgs) == 2
            inbound = next(m for m in msgs if m.direction == MessageDirection.INBOUND)
            outbound = next(m for m in msgs if m.direction == MessageDirection.OUTBOUND)
            assert inbound.subject == "Consulta — piso en Salamanca"
            assert inbound.external_id == msg_id
            assert outbound.subject is not None and outbound.subject.lower().startswith("re:")
            assert outbound.external_id.startswith("resend.SIMULATED_")
            assert outbound.delivery_status.value == "sent"
        await engine.dispose()
    finally:
        await _cleanup_lead(database_url, identifier)


@pytest.mark.asyncio
async def test_inbound_from_own_address_is_ignored(database_url: str) -> None:
    """Self-loop guard: an inbound whose `from` is our own sending address (a reply
    addressed back to noreply@…) is dropped — no lead, no reply, no infinite loop."""
    own = "noreply@realtors.ekoaiautomation.com"  # matches default RESEND_FROM
    suffix = uuid.uuid4().hex[:8].upper()
    payload = {
        "type": "email.received",
        "data": {
            "id": f"resend_self_{suffix}",
            "from": own,
            "from_name": "Eko AI Realtors",
            "to": ["someone@realtors.ekoaiautomation.com"],
            "subject": "Re: self loop",
            "text": "this should never trigger a reply",
            "headers": {"message-id": f"<self-{suffix}@realtors.ekoaiautomation.com>"},
        },
    }
    try:
        async with await _http_client() as client:
            resp = await client.post("/api/v1/webhooks/email", json=payload)
        assert resp.status_code == 200, resp.text
        assert resp.json()["results"][0]["status"] == "ignored_self_loop"

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            assert (await s.execute(select(Lead).where(Lead.phone == own))).scalar_one_or_none() is None
        await engine.dispose()
    finally:
        await _cleanup_lead(database_url, own)

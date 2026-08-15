"""Tests for the leads API — list, detail, PATCH (Phase 2 dashboard ops) +
manual create (Add Lead)."""
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
    Lead,
    Message,
    MessageDirection,
    MessageSender,
)
from app.services.classifier import IntentEntities, IntentResult
from app.services.llm import LLMResult


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — leads API tests need live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert_lead(database_url: str, phone: str) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Test Lead PATCH")
            s.add(lead)
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _delete_lead(database_url: str, phone: str) -> None:
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
async def test_list_leads_returns_envelope() -> None:
    """Even an empty list returns the {total, items} envelope shape."""
    async with await _http_client() as client:
        resp = await client.get("/api/v1/leads?limit=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total" in body
    assert "items" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_get_lead_404_when_missing() -> None:
    async with await _http_client() as client:
        resp = await client.get("/api/v1/leads/999999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_lead_takeover_toggle(database_url: str) -> None:
    suffix = f"{uuid.uuid4().int % 10**8:08d}"
    phone = f"+34666{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.patch(f"/api/v1/leads/{lead_id}", json={"human_takeover": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["human_takeover"] is True
        assert body["id"] == lead_id

        # Toggle back off
        async with await _http_client() as client:
            r2 = await client.patch(f"/api/v1/leads/{lead_id}", json={"human_takeover": False})
        assert r2.json()["human_takeover"] is False
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_patch_lead_status_and_zone_partial_update(database_url: str) -> None:
    """Only fields in the body are written; everything else is untouched."""
    suffix = f"{uuid.uuid4().int % 10**8:08d}"
    phone = f"+34666{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.patch(
                f"/api/v1/leads/{lead_id}",
                json={"status": "won", "zone": "Salamanca"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "won"
        assert body["zone"] == "Salamanca"
        assert body["name"] == "Test Lead PATCH"  # unchanged
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_patch_empty_body_400(database_url: str) -> None:
    suffix = f"{uuid.uuid4().int % 10**8:08d}"
    phone = f"+34666{suffix}"
    lead_id = await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.patch(f"/api/v1/leads/{lead_id}", json={})
        assert r.status_code == 400
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_patch_unknown_field_422() -> None:
    """`extra='forbid'` on the schema rejects unknown fields."""
    async with await _http_client() as client:
        r = await client.patch(
            "/api/v1/leads/1", json={"unknown_field": "x"}
        )
    # Pydantic returns 422 for schema violations, before our 404 check runs.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_invalid_status_422() -> None:
    async with await _http_client() as client:
        r = await client.patch("/api/v1/leads/1", json={"status": "not_a_real_status"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_lead_404_when_missing() -> None:
    async with await _http_client() as client:
        r = await client.patch("/api/v1/leads/999999999", json={"human_takeover": True})
    assert r.status_code == 404


# ── POST /leads — manual Add Lead ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_lead_without_first_message(database_url: str) -> None:
    """A bare manual lead is created, scored, marked source=manual, no conversation."""
    suffix = f"{uuid.uuid4().int % 10**10:010d}"
    phone = f"+34666{suffix}"
    try:
        async with await _http_client() as client:
            r = await client.post(
                "/api/v1/leads",
                json={"phone": phone, "name": "Walk-in Referral", "intent": "buy", "zone": "Brickell"},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["phone"] == phone
        assert body["intent"] == "buy"
        assert body["zone"] == "Brickell"

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            assert lead.meta.get("source") == "manual"
            assert "demo" not in lead.meta  # first-class lead, not a demo throwaway
            assert lead.score > 0  # intent + zone produce a non-zero score
            convs = (
                await s.execute(select(Conversation).where(Conversation.lead_id == lead.id))
            ).scalars().all()
            assert convs == []  # no first_message → no conversation
        await engine.dispose()
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_create_lead_with_first_message_kicks_off_ai(database_url: str) -> None:
    """A first_message is injected as inbound → AI classifies + replies (LLM mocked)."""
    suffix = f"{uuid.uuid4().int % 10**10:010d}"
    phone = f"+34666{suffix}"

    fake_intent = IntentResult(
        intent="rent",  # type: ignore[arg-type]
        confidence=0.95,
        entities=IntentEntities(zone="Wynwood", budget_max=2500),
    )
    fake_reply = LLMResult(
        text="¡Hola! Tengo opciones en Wynwood. ¿Cuándo te gustaría visitarlas?",
        provider="kimi",
        model="kimi-for-coding",
        input_tokens=80,
        output_tokens=30,
    )
    try:
        with patch("app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)):
            with patch("app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)):
                async with await _http_client() as client:
                    r = await client.post(
                        "/api/v1/leads",
                        json={
                            "phone": phone,
                            "name": "Demo Realtor",
                            "channel": "sms",
                            "first_message": "Hola, busco algo en alquiler en Wynwood",
                        },
                    )
        assert r.status_code == 201, r.text
        lead_id = r.json()["id"]

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            conv = (
                await s.execute(select(Conversation).where(Conversation.lead_id == lead_id))
            ).scalar_one()
            assert conv.channel == "sms"
            msgs = (
                await s.execute(
                    select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
                )
            ).scalars().all()
            assert len(msgs) == 2
            assert msgs[0].direction == MessageDirection.INBOUND
            assert msgs[0].sender == MessageSender.LEAD
            assert msgs[1].direction == MessageDirection.OUTBOUND
            assert msgs[1].sender == MessageSender.AGENT
        await engine.dispose()
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_create_lead_duplicate_contact_409(database_url: str) -> None:
    suffix = f"{uuid.uuid4().int % 10**10:010d}"
    phone = f"+34666{suffix}"
    await _insert_lead(database_url, phone)
    try:
        async with await _http_client() as client:
            r = await client.post("/api/v1/leads", json={"phone": phone})
        assert r.status_code == 409, r.text
    finally:
        await _delete_lead(database_url, phone)


@pytest.mark.asyncio
async def test_create_lead_missing_phone_422() -> None:
    async with await _http_client() as client:
        r = await client.post("/api/v1/leads", json={"name": "No contact"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_lead_unknown_field_422() -> None:
    """`extra='forbid'` on LeadCreate rejects unknown fields."""
    async with await _http_client() as client:
        r = await client.post("/api/v1/leads", json={"phone": "+34600000000", "bogus": "x"})
    assert r.status_code == 422


async def _seed_lead_with_last_message(database_url: str, phone: str, last_dir: MessageDirection) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="NR Lead")
            s.add(lead)
            await s.flush()
            conv = Conversation(lead_id=lead.id, channel="sms")
            s.add(conv)
            await s.flush()
            sender = MessageSender.LEAD if last_dir == MessageDirection.INBOUND else MessageSender.AGENT
            s.add(Message(
                conversation_id=conv.id, direction=last_dir, sender=sender,
                content="hi", external_id=f"nr_{uuid.uuid4().hex[:10]}",
            ))
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_leads_needs_response_flag(database_url: str) -> None:
    """needs_response is True when the lead's last message is inbound, else False."""
    pin = uuid.uuid4().hex[:8]
    inbound_phone, outbound_phone = f"+3460{pin}1", f"+3460{pin}2"
    inbound_id = await _seed_lead_with_last_message(database_url, inbound_phone, MessageDirection.INBOUND)
    outbound_id = await _seed_lead_with_last_message(database_url, outbound_phone, MessageDirection.OUTBOUND)
    try:
        async with await _http_client() as client:
            body = (await client.get("/api/v1/leads?limit=200")).json()
        by_id = {it["id"]: it for it in body["items"]}
        assert by_id[inbound_id]["needs_response"] is True
        assert by_id[outbound_id]["needs_response"] is False
    finally:
        await _delete_lead(database_url, inbound_phone)
        await _delete_lead(database_url, outbound_phone)

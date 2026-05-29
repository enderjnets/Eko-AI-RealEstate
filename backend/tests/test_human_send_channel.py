"""Composer channel selection — POST /leads/{id}/messages with explicit `channel`.

Omitting channel keeps the legacy auto-pick; an explicit channel reuses that
channel's conversation (or creates it); voice is rejected.
"""
from __future__ import annotations

import os
import uuid

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
from app.services import conversation as conv_svc


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — channel-select tests need live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _insert_lead_with_channels(database_url: str, phone: str, channels: list[str]) -> int:
    """Create a Lead + one active Conversation per channel (with 1 inbound each)."""
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Channel Test")
            s.add(lead)
            await s.flush()
            for ch in channels:
                conv = Conversation(lead_id=lead.id, channel=ch, status=ConversationStatus.ACTIVE)
                s.add(conv)
                await s.flush()
                s.add(Message(
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content=f"inbound on {ch}",
                    external_id=f"{ch}_in_{uuid.uuid4().hex[:8]}",
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


async def _convs_for(database_url: str, lead_id: int) -> list[Conversation]:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            return list(
                (await s.execute(select(Conversation).where(Conversation.lead_id == lead_id)))
                .scalars().all()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_channel_reuses_existing_conversation(database_url: str) -> None:
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CHR{suffix}"
    lead_id = await _insert_lead_with_channels(database_url, phone, ["sms", "whatsapp"])
    try:
        async with await _http_client() as client:
            r = await client.post(
                f"/api/v1/leads/{lead_id}/messages",
                json={"text": "Reply on SMS please", "channel": "sms"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["channel"] == "sms"
        # No NEW conversation created — still just the two we seeded.
        convs = await _convs_for(database_url, lead_id)
        assert len(convs) == 2
        sms_conv = next(c for c in convs if c.channel == "sms")
        # The outbound landed on the existing sms conversation.
        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            out = (await s.execute(select(Message).where(Message.id == body["outbound_id"]))).scalar_one()
            assert out.conversation_id == sms_conv.id
            assert out.sender == MessageSender.HUMAN
        await engine.dispose()
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_explicit_channel_creates_conversation_when_missing(database_url: str) -> None:
    """Lead used WhatsApp (phone); realtor sends SMS (same phone) → new sms conversation."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CHC{suffix}"
    lead_id = await _insert_lead_with_channels(database_url, phone, ["whatsapp"])
    try:
        async with await _http_client() as client:
            r = await client.post(
                f"/api/v1/leads/{lead_id}/messages",
                json={"text": "Texting you instead", "channel": "sms"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["channel"] == "sms"
        convs = await _convs_for(database_url, lead_id)
        channels = sorted(c.channel for c in convs)
        assert channels == ["sms", "whatsapp"]  # a new sms conversation now exists
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_explicit_channel_rejected_on_identifier_mismatch(database_url: str) -> None:
    """Phone-only lead + channel=email → mismatch error; no email conversation created."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CHM{suffix}"
    lead_id = await _insert_lead_with_channels(database_url, phone, ["sms"])
    try:
        async with await _http_client() as client:
            r = await client.post(
                f"/api/v1/leads/{lead_id}/messages",
                json={"text": "trying email", "channel": "email"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "error"
        assert body["error"] == "channel_identifier_mismatch"
        # No undeliverable email conversation was created.
        convs = await _convs_for(database_url, lead_id)
        assert [c.channel for c in convs] == ["sms"]
    finally:
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_voice_channel_rejected_422() -> None:
    """Schema Literal excludes voice → 422 before touching the DB."""
    async with await _http_client() as client:
        r = await client.post(
            "/api/v1/leads/1/messages",
            json={"text": "hola", "channel": "voice"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_service_rejects_unsupported_channel(database_url: str) -> None:
    """Service-level guard: a junk channel returns unsupported_channel (defense in depth)."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CHV{suffix}"
    lead_id = await _insert_lead_with_channels(database_url, phone, ["sms"])
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            result = await conv_svc.send_human_message(lead_id, "hi", s, channel="voice")
        assert result["status"] == "error"
        assert result["error"] == "unsupported_channel"
    finally:
        await engine.dispose()
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_no_channel_preserves_autopick(database_url: str) -> None:
    """Omitting channel keeps legacy behavior: most-recently-active conv wins."""
    suffix = uuid.uuid4().hex[:8].upper()
    phone = f"+34666CHA{suffix}"
    lead_id = await _insert_lead_with_channels(database_url, phone, ["whatsapp"])
    try:
        async with await _http_client() as client:
            r = await client.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "auto"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["channel"] == "whatsapp"
        convs = await _convs_for(database_url, lead_id)
        assert len(convs) == 1  # no new conversation
    finally:
        await _cleanup_lead(database_url, phone)

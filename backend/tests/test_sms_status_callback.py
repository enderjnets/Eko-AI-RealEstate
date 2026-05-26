"""Tests for the Twilio delivery status callback → Message.delivery_status."""
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


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — status callback test needs live Postgres")
    return url


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_outbound(database_url: str, phone: str, sid: str) -> int:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Status Test")
            s.add(lead)
            await s.flush()
            conv = Conversation(lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE)
            s.add(conv)
            await s.flush()
            s.add(
                Message(
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="reply",
                    external_id=sid,
                    delivery_status=MessageStatus.SENT,
                )
            )
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _delete_lead(database_url: str, lead_id: int) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            row = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()


async def _status_of(database_url: str, sid: str) -> str:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            msg = (await s.execute(select(Message).where(Message.external_id == sid))).scalar_one()
            return msg.delivery_status.value
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_status_callback_marks_delivered(database_url: str) -> None:
    sfx = uuid.uuid4().hex[:8].upper()
    phone, sid = f"+1305STA{sfx}", f"SM{sfx}DELIV"
    lead_id = await _seed_outbound(database_url, phone, sid)
    try:
        async with await _client() as c:
            r = await c.post(
                "/api/v1/webhooks/sms/status",
                data={"MessageSid": sid, "MessageStatus": "delivered", "ErrorCode": "0"},
            )
        assert r.status_code == 200, r.text
        assert await _status_of(database_url, sid) == "delivered"
    finally:
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_status_callback_marks_undelivered_failed(database_url: str) -> None:
    sfx = uuid.uuid4().hex[:8].upper()
    phone, sid = f"+1305STU{sfx}", f"SM{sfx}UNDEL"
    lead_id = await _seed_outbound(database_url, phone, sid)
    try:
        async with await _client() as c:
            # 30034 = A2P 10DLC unregistered (the real-world case we hit).
            r = await c.post(
                "/api/v1/webhooks/sms/status",
                data={"MessageSid": sid, "MessageStatus": "undelivered", "ErrorCode": "30034"},
            )
        assert r.status_code == 200, r.text
        assert await _status_of(database_url, sid) == "failed"
    finally:
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_status_callback_unknown_sid_is_ok(database_url: str) -> None:
    async with await _client() as c:
        r = await c.post(
            "/api/v1/webhooks/sms/status",
            data={"MessageSid": "SMnonexistent999", "MessageStatus": "delivered"},
        )
    assert r.status_code == 200  # no-op, never errors

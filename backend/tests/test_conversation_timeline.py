"""Unified per-lead timeline — GET /api/v1/conversations/{lead_id}/timeline.

Merges messages across ALL of a lead's conversations (every channel) into one
time-ordered list, each message carrying its own channel.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

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
        pytest.skip("DATABASE_URL not set — timeline tests need live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _msg(conv_id: int, content: str, *, direction: MessageDirection, sender: MessageSender,
         created_at: datetime, ext: str) -> Message:
    return Message(
        conversation_id=conv_id,
        direction=direction,
        sender=sender,
        content=content,
        external_id=ext,
        delivery_status=MessageStatus.DELIVERED,
        created_at=created_at,
    )


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


@pytest.mark.asyncio
async def test_timeline_merges_two_channels_time_ordered(database_url: str) -> None:
    """A lead with sms + email conversations → one list ordered by time, each
    message tagged with its own channel; channels + primary reflect recency."""
    suffix = uuid.uuid4().hex[:8]
    phone = f"+34666TL{suffix}"
    t0 = datetime(2026, 5, 28, 10, 0, 0, tzinfo=UTC)
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Timeline Test")
            s.add(lead)
            await s.flush()
            sms = Conversation(lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE,
                               last_at=t0 + timedelta(minutes=2))
            email = Conversation(lead_id=lead.id, channel="email", status=ConversationStatus.ACTIVE,
                                 last_at=t0 + timedelta(minutes=10))
            s.add_all([sms, email])
            await s.flush()
            s.add_all([
                _msg(sms.id, "sms-1", direction=MessageDirection.INBOUND,
                     sender=MessageSender.LEAD, created_at=t0, ext=f"sms_{suffix}_1"),
                _msg(email.id, "email-1", direction=MessageDirection.INBOUND,
                     sender=MessageSender.LEAD, created_at=t0 + timedelta(minutes=5),
                     ext=f"email_{suffix}_1"),
                _msg(sms.id, "sms-2", direction=MessageDirection.OUTBOUND,
                     sender=MessageSender.AGENT, created_at=t0 + timedelta(minutes=8),
                     ext=f"sms_{suffix}_2"),
            ])
            await s.commit()
            lead_id = lead.id

        async with await _http_client() as client:
            r = await client.get(f"/api/v1/conversations/{lead_id}/timeline")
        assert r.status_code == 200, r.text
        body = r.json()
        contents = [(m["content"], m["channel"]) for m in body["messages"]]
        assert contents == [("sms-1", "sms"), ("email-1", "email"), ("sms-2", "sms")]
        assert set(body["channels"]) == {"sms", "email"}
        # email conv is the most-recently-active (last_at later) → primary.
        assert body["primary_channel"] == "email"
        assert len(body["conversations"]) == 2
        counts = {c["channel"]: c["message_count"] for c in body["conversations"]}
        assert counts == {"sms": 2, "email": 1}
    finally:
        await engine.dispose()
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_timeline_tiebreak_on_id(database_url: str) -> None:
    """Two messages with identical created_at order deterministically by id."""
    suffix = uuid.uuid4().hex[:8]
    phone = f"+34666TB{suffix}"
    t0 = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Tiebreak")
            s.add(lead)
            await s.flush()
            a = Conversation(lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE)
            b = Conversation(lead_id=lead.id, channel="email", status=ConversationStatus.ACTIVE)
            s.add_all([a, b])
            await s.flush()
            first = _msg(a.id, "first", direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD, created_at=t0, ext=f"tb_{suffix}_1")
            s.add(first)
            await s.flush()
            second = _msg(b.id, "second", direction=MessageDirection.INBOUND,
                         sender=MessageSender.LEAD, created_at=t0, ext=f"tb_{suffix}_2")
            s.add(second)
            await s.commit()
            lead_id = lead.id

        async with await _http_client() as client:
            r = await client.get(f"/api/v1/conversations/{lead_id}/timeline")
        body = r.json()
        assert [m["content"] for m in body["messages"]] == ["first", "second"]
    finally:
        await engine.dispose()
        await _cleanup_lead(database_url, phone)


@pytest.mark.asyncio
async def test_timeline_empty_returns_200(database_url: str) -> None:
    """A lead with no conversations → 200 with empty arrays + null primary."""
    suffix = uuid.uuid4().hex[:8]
    phone = f"+34666TE{suffix}"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead = Lead(phone=phone, name="Empty")
            s.add(lead)
            await s.commit()
            lead_id = lead.id

        async with await _http_client() as client:
            r = await client.get(f"/api/v1/conversations/{lead_id}/timeline")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["messages"] == []
        assert body["conversations"] == []
        assert body["channels"] == []
        assert body["primary_channel"] is None
        assert body["primary_conversation_id"] is None
    finally:
        await engine.dispose()
        await _cleanup_lead(database_url, phone)

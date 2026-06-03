"""End-to-end test for the voice webhook: VAPI server message → DB.

Voice ingest does NOT call the LLM (the conversation already happened live in the
call), so unlike the SMS/email e2e there is nothing to mock. Needs live Postgres.
Booking assertions need CALENDAR_SIMULATED=true (the default).
"""
from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import Conversation, Lead, Message, MessageDirection, Visit


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — voice E2E needs live Postgres")
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
                await s.delete(row)  # cascades to conversations/messages/visits
                await s.commit()
    finally:
        await engine.dispose()


def _eocr(call_id: str, phone: str) -> dict:
    return {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": call_id, "customer": {"number": phone}},
            "artifact": {
                "messages": [
                    {"role": "bot", "message": "Are you looking to buy, rent, or sell?"},
                    {"role": "user", "message": "Buy a 3BR in Aurora under 600k"},
                    {"role": "bot", "message": "Great, I can help with that."},
                ]
            },
            "analysis": {
                "summary": "Caller wants to buy in Aurora.",
                "structuredData": {"intent": "buy", "zone": "Aurora", "budget_max": 600000},
            },
        }
    }


@pytest.mark.asyncio
async def test_end_of_call_report_creates_voice_lead(database_url: str) -> None:
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    call_id = f"call_{sfx}"

    try:
        async with await _http_client() as client:
            resp = await client.post("/api/v1/webhooks/voice", json=_eocr(call_id, phone))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            assert lead.intent is not None and lead.intent.value == "buy"
            assert lead.zone == "Aurora"
            assert lead.budget_max == 600000
            assert lead.score > 0  # rescored after ingest

            conv = (
                await s.execute(select(Conversation).where(Conversation.lead_id == lead.id))
            ).scalar_one()
            assert conv.channel == "voice"
            assert conv.external_thread_id == call_id

            msgs = (
                await s.execute(
                    select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)
                )
            ).scalars().all()
            assert len(msgs) == 3
            assert sum(1 for m in msgs if m.direction == MessageDirection.INBOUND) == 1
            assert sum(1 for m in msgs if m.direction == MessageDirection.OUTBOUND) == 2
            assert msgs[0].external_id == f"{call_id}#0"
        await engine.dispose()
    finally:
        await _cleanup(database_url, phone)


@pytest.mark.asyncio
async def test_end_of_call_report_idempotent(database_url: str) -> None:
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303556{sfx[:4]}"
    call_id = f"call_{sfx}"

    try:
        async with await _http_client() as client:
            await client.post("/api/v1/webhooks/voice", json=_eocr(call_id, phone))
            resp2 = await client.post("/api/v1/webhooks/voice", json=_eocr(call_id, phone))
        assert resp2.json()["result"]["status"] == "duplicate"

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            conv = (
                await s.execute(select(Conversation).where(Conversation.lead_id == lead.id))
            ).scalar_one()
            msgs = (
                await s.execute(select(Message).where(Message.conversation_id == conv.id))
            ).scalars().all()
            assert len(msgs) == 3  # the retry did not duplicate the transcript
        await engine.dispose()
    finally:
        await _cleanup(database_url, phone)


@pytest.mark.asyncio
async def test_tool_call_book_visit_creates_visit(database_url: str) -> None:
    """Needs CALENDAR_SIMULATED=true (default) so create_booking returns a sim id."""
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303557{sfx[:4]}"
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": f"call_{sfx}", "customer": {"number": phone}},
            "toolCalls": [
                {
                    "id": "tc_1",
                    "function": {
                        "name": "book_visit",
                        "arguments": {
                            "datetime": "2027-01-15T15:00:00Z",
                            "property_address": "123 Main St, Aurora CO",
                        },
                    },
                }
            ],
        }
    }

    try:
        async with await _http_client() as client:
            resp = await client.post("/api/v1/webhooks/voice", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["results"][0]["toolCallId"] == "tc_1"
        assert "booked" in body["results"][0]["result"].lower()

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one()
            visits = (
                await s.execute(select(Visit).where(Visit.lead_id == lead.id))
            ).scalars().all()
            assert len(visits) == 1
            assert visits[0].property_address == "123 Main St, Aurora CO"
        await engine.dispose()
    finally:
        await _cleanup(database_url, phone)

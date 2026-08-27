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
async def test_tool_call_book_visit_keys_on_caller_id(database_url: str) -> None:
    """The visit must land on the CALLER ID lead (same as the transcript), even when
    the caller dictates a DIFFERENT callback number — which is kept as a note.
    Needs CALENDAR_SIMULATED=true (default) so create_booking returns a sim id."""
    sfx = uuid.uuid4().hex[:8]
    caller_id = f"+1303557{sfx[:4]}"
    dictated = f"+1720555{sfx[:4]}"  # different from the caller id
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": f"call_{sfx}", "customer": {"number": caller_id}},
            "toolCalls": [
                {
                    "id": "tc_1",
                    "function": {
                        "name": "book_visit",
                        "arguments": {
                            # A Friday at 15:00 OFFICE-LOCAL — `_parse_dt`
                            # discards the Z and reads the wall clock in the
                            # agency's timezone, and 15:00 is one of the
                            # simulated slot hours. This failed on every fresh
                            # database (CI included) while passing locally,
                            # because slot generation ignored the timezone and
                            # always produced UTC hours: an office in Denver
                            # asking for 3 PM was told nothing was free all
                            # day, since 3 PM Denver is 22:00 UTC.
                            "datetime": "2027-01-15T15:00:00Z",
                            "property_address": "123 Main St, Aurora CO",
                            "phone": dictated,
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
            # lead keyed on the caller id, NOT the dictated number
            lead = (await s.execute(select(Lead).where(Lead.phone == caller_id))).scalar_one()
            assert (
                await s.execute(select(Lead).where(Lead.phone == dictated))
            ).scalar_one_or_none() is None
            visits = (
                await s.execute(select(Visit).where(Visit.lead_id == lead.id))
            ).scalars().all()
            assert len(visits) == 1
            assert visits[0].property_address == "123 Main St, Aurora CO"
            assert dictated in (visits[0].notes or "")  # callback note
        await engine.dispose()
    finally:
        await _cleanup(database_url, caller_id)


@pytest.mark.asyncio
async def test_a_broken_office_timezone_stops_the_booking_not_just_the_log() -> None:
    """The same six-hour bug as `visits.py`, on the lane that talks out loud.

    `_office_zone` used to fall back to UTC with a `log.warning`. Every hour the
    assistant quoted and every appointment it booked then landed in the wrong
    zone — in Denver, six hours off. A caller told "Tuesday at 2 PM" finds the
    door locked at 8 AM, and the only trace is a warning line nobody reads
    during a phone call.

    None rather than an exception, because the tool handler promises never to
    raise: a thrown handler stalls the assistant mid-call. The spoken apology
    is the honest answer — we cannot offer a time we cannot compute.
    """
    from app.services.voice import _office_zone

    assert _office_zone("America/Denver") is not None
    assert _office_zone("") is not None, "blank still means UTC, as documented"
    assert _office_zone("Invented/Zone") is None, (
        "an unusable zone still resolves, so times will be quoted in the wrong one"
    )

    # And the promise has to hold for EVERY way the lookup fails, not just the
    # two exception types the first version happened to catch. `"America"` is a
    # tzdata directory: it raised `IsADirectoryError` from a call sited outside
    # `handle_tool_call`'s own `try`, straight past a docstring saying it never
    # raises. A handler that stalls mid-call is exactly what None was for.
    for unusable in ("America", "Etc", "A" * 300):
        assert _office_zone(unusable) is None, f"{unusable[:12]!r} must not resolve"


@pytest.mark.asyncio
async def test_the_assistant_apologises_instead_of_quoting_a_wrong_hour(
    monkeypatch,
) -> None:
    """And the refusal reaches the caller as speech, not as a stall or a stack trace."""
    from app.services import voice

    async def _bad_tz(db: object) -> str:
        return "Invented/Zone"

    monkeypatch.setattr(voice, "_office_tz_name", _bad_tz)

    spoken = await voice.handle_tool_call(
        "check_availability", {}, customer_number="+13035550000", db=None
    )

    assert isinstance(spoken, str) and spoken, "the handler must always speak"
    assert "call you back" in spoken.lower(), spoken
    # And nothing that looks like a time was offered.
    assert "AM" not in spoken and "PM" not in spoken, spoken

"""Three gates on the door that opened on 2026-09-19.

The email channel went live that morning and `hello@denverhomestory.com` became
reachable by anyone. By that evening the paths a stranger could walk were:

  1. Unbounded inbound — two LLM calls and a lead row per message, forever.
  2. Unbounded notices to the realtor — `origin="qualified"` fires for any lead
     naming a neighbourhood and a figure, so fifty emails are fifty mails in her
     inbox, and each one she acts on is an MLS search against a 500-listing
     ceiling whose penalty is $15,000 and suspension of her access.
  3. A reply she is legally answerable for, written by a model, sent to whoever
     asked for it — including someone who crafted the message to draw a
     discriminatory sentence out of it.

Each gate has a test here and each was seen red with the gate removed.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import Conversation, Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.classifier import IntentEntities, IntentResult
from app.services.inbound_limits import (
    DOMAIN_LIMIT,
    GLOBAL_LIMIT,
    SENDER_LIMIT,
    over_budget,
    reset_inbound_limits,
)
from app.services.llm import LLMResult

ORG = 1
ADDRESS = "123 Test Ave Ste 1, Denver, CO 80200"


@pytest.fixture(autouse=True)
def _clean_limits() -> None:
    reset_inbound_limits()
    yield
    reset_inbound_limits()


# ──────────────────────────────────────────────────────────────────────────
# Gate 1 — the inbound budget. Pure; no database.
# ──────────────────────────────────────────────────────────────────────────


def test_one_sender_cannot_loop_forever() -> None:
    for i in range(SENDER_LIMIT):
        assert over_budget("someone@example.com", now=100.0) is None, f"message {i}"
    assert over_budget("someone@example.com", now=100.0) == "sender"


def test_rotating_the_address_is_caught_by_the_domain() -> None:
    """The tier that exists because a `From:` header costs nothing to change.

    We read no SPF or DKIM verdict, so the sender bucket stops a naive loop and
    nothing more. One fresh address per message walks straight through it — and
    into this.
    """
    refusals = [
        over_budget(f"burner{i}@attacker.test", now=100.0)
        for i in range(DOMAIN_LIMIT + 5)
    ]
    assert refusals[:DOMAIN_LIMIT] == [None] * DOMAIN_LIMIT
    assert set(refusals[DOMAIN_LIMIT:]) == {"domain"}


def test_a_refused_message_does_not_spend_the_shared_budget() -> None:
    """The lesson `public.py` paid for, in a different file.

    Charging the global budget first turned it into a kill switch anyone could
    hold down: sixty refused posts each spent a slot and lead capture went down
    for every agency. So a message turned away by a cheaper tier must leave the
    shared budget untouched — which this proves by exhausting one sender and
    then showing the global budget still has its full room.
    """
    for _ in range(SENDER_LIMIT + 50):
        over_budget("noisy@example.com", now=100.0)

    survivors = 0
    for i in range(GLOBAL_LIMIT):
        # A fresh domain each time, so neither cheap tier interferes.
        if over_budget(f"a@d{i}.test", now=100.0) is None:
            survivors += 1
    assert survivors == GLOBAL_LIMIT - SENDER_LIMIT, (
        "only the messages that got PAST the cheap tiers may have spent the "
        "shared budget"
    )


def test_a_message_with_no_sender_is_metered_not_waved_through() -> None:
    """An empty `From:` is the cheapest forgery there is."""
    for _ in range(SENDER_LIMIT):
        assert over_budget("", now=100.0) is None
    assert over_budget(None, now=100.0) == "sender"


# ──────────────────────────────────────────────────────────────────────────
# Gates 2 and 3 — these need live Postgres.
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def agency_mailbox(database_url: str):  # noqa: ANN201
    from app.models.agent_settings import AgentSettings
    from app.services.tenant_context import org_scope

    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            created = row is None
            if created:
                row = AgentSettings(org_id=ORG)
                db.add(row)
            previous = row.booking_contact_email
            row.booking_contact_email = "door-probe@example.com"
            await db.commit()
    yield
    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            if row is not None:
                if created:
                    await db.delete(row)
                else:
                    row.booking_contact_email = previous
                await db.commit()


async def _seed_lead(email: str) -> tuple[int, int]:
    async with get_bypass_session_factory()() as db:
        lead = Lead(org_id=ORG, phone=email, email=email)
        db.add(lead)
        await db.flush()
        conv = Conversation(org_id=ORG, lead_id=lead.id, channel="email")
        db.add(conv)
        await db.flush()
        msg = Message(
            org_id=ORG,
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            sender=MessageSender.LEAD,
            content="Hello, I would like to buy in Denver.",
            delivery_status=MessageStatus.DELIVERED,
        )
        db.add(msg)
        await db.commit()
        return int(lead.id), int(msg.id)


async def _fill_notice_budget(conversation_id: int, how_many: int) -> None:
    """`how_many` internal traces, which is what the budget counts."""
    async with get_bypass_session_factory()() as db:
        for _ in range(how_many):
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="(previous notice)",
                    delivery_status=MessageStatus.SENT,
                    internal=True,
                )
            )
        await db.commit()


async def _cleanup(pattern: str) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE email LIKE :p"), {"p": pattern})
        await db.commit()


@pytest.mark.asyncio
async def test_a_stranger_cannot_fill_the_realtors_inbox(
    database_url: str, agency_mailbox: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.services.lead_notify import send_new_lead_notice
    from app.services.tenant_context import set_org_id

    monkeypatch.setenv("AGENCY_NOTICE_DAILY_CAP", "3")
    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id, msg_id = await _seed_lead("flood@door.test")
    try:
        async with get_bypass_session_factory()() as db:
            conv_id = (
                await db.execute(select(Conversation.id).where(Conversation.lead_id == lead_id))
            ).scalar_one()
        await _fill_notice_budget(conv_id, 4)  # already past a cap of 3

        sender = AsyncMock(return_value={"id": "resend.x", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(lead_id, msg_id, origin="qualified")
        sender.assert_not_awaited()
    finally:
        await _cleanup("%@door.test")


@pytest.mark.asyncio
async def test_the_form_is_never_silenced_by_someone_elses_flood(
    database_url: str, agency_mailbox: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The funnel's only conversion point cannot be turned off from outside.

    This is the property, not a nicety: a budget that untrusted traffic can
    exhaust on behalf of trusted traffic is a kill switch, which is exactly what
    `public.py` shipped once and had to undo.
    """
    from app.config import get_settings
    from app.services.lead_notify import send_new_lead_notice
    from app.services.tenant_context import set_org_id

    monkeypatch.setenv("AGENCY_NOTICE_DAILY_CAP", "3")
    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id, msg_id = await _seed_lead("form@door.test")
    try:
        async with get_bypass_session_factory()() as db:
            conv_id = (
                await db.execute(select(Conversation.id).where(Conversation.lead_id == lead_id))
            ).scalar_one()
        await _fill_notice_budget(conv_id, 40)

        sender = AsyncMock(return_value={"id": "resend.y", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(lead_id, msg_id, origin="form")
        sender.assert_awaited()
    finally:
        await _cleanup("%@door.test")


@pytest.mark.asyncio
async def test_a_flagged_reply_is_not_sent_and_the_sweep_will_not_send_it_later(
    database_url: str,
) -> None:
    """Both halves, because either passes alone.

    Refusing to send is worth nothing if `delivery.py`'s retry sweep picks the
    row up an hour later and delivers the very text we refused.
    """
    from datetime import UTC, datetime

    from app.services.delivery import _still_owed

    suffix = uuid.uuid4().hex[:8]
    identifier = f"fh+{suffix}@door.test"
    payload = {
        "type": "email.received",
        "data": {
            "id": f"resend_fh_{suffix}",
            "from": identifier,
            "from_name": "Probe",
            "to": ["info@realtor-demo.com"],
            "subject": "A question",
            "text": "Tell me about the neighbourhood.",
            "headers": {"message-id": f"<fh-{suffix}@door.test>"},
        },
    }
    fake_intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.9,
        entities=IntentEntities(zone="Wash Park"),
    )
    fake_reply = LLMResult(
        text="It is a safe neighborhood with good schools.",
        provider="minimax",
        model="MiniMax-M3",
        input_tokens=10,
        output_tokens=10,
    )
    flag = [{"category": "familial_status", "phrase": "good schools"}]
    try:
        with patch(
            "app.services.conversation.classify_intent", AsyncMock(return_value=fake_intent)
        ), patch(
            "app.services.conversation.generate_reply", AsyncMock(return_value=fake_reply)
        ), patch(
            "app.services.conversation.find_violations", return_value=flag
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/webhooks/email", json=payload)

        assert resp.status_code == 200, resp.text
        result = resp.json()["results"][0]
        assert result["status"] == "blocked_fair_housing"

        engine = create_async_engine(database_url, echo=False, future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with Session() as s:
            row = (
                await s.execute(select(Message).where(Message.id == result["outbound_id"]))
            ).scalar_one()
            assert row.delivery_status == MessageStatus.FAILED
            assert row.external_id is None
            assert row.fair_housing_flags == flag

            owed = (
                await s.execute(select(Message.id).where(_still_owed(datetime.now(UTC))))
            ).scalars().all()
            assert row.id not in owed, "the retry sweep must not resurrect it"
        await engine.dispose()
    finally:
        await _cleanup("%@door.test")

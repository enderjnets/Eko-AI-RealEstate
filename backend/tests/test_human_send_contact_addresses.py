"""A web lead's email remains reachable when its identifier is a phone number."""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.conversation import send_human_message
from app.services.tenant_context import org_scope

PHONE = "+13035550123"
EMAIL = "buyer@contact-addresses.test"
REPLY = "We received your inquiry. Which day would you like to speak?"
PROVIDER_ID = "provider.contact-address-test"


@pytest.fixture
async def agency() -> AsyncIterator[int]:
    slug = f"contact-addresses-{uuid4().hex}"
    async with get_bypass_session_factory()() as db:
        org_id = (
            await db.execute(
                text(
                    "INSERT INTO organizations (name, slug, status, plan) "
                    "VALUES ('Contact Addresses Test', :slug, 'active', 'pilot') RETURNING id"
                ),
                {"slug": slug},
            )
        ).scalar_one()
        await db.commit()
    try:
        async with get_session_factory()() as db:
            role = (
                await db.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                )
            ).one()
            assert not role.rolsuper and not role.rolbypassrls, "tests must exercise the app role"
        yield org_id
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM organizations WHERE id = :id AND slug = :slug"),
                {"id": org_id, "slug": slug},
            )
            await db.commit()


@pytest.fixture
def dispatch() -> Iterator[AsyncMock]:
    with patch(
        "app.services.conversation._dispatch_send",
        new_callable=AsyncMock,
        return_value=(PROVIDER_ID, None),
    ) as transport:
        yield transport


async def _web_lead(
    phone: str,
    email: str | None,
    *,
    existing_email_thread: bool = False,
    opted_out: bool = False,
) -> tuple[int, dict[str, int]]:
    now = datetime.now(UTC)
    async with get_session_factory()() as db:
        lead = Lead(phone=phone, email=email, name="Contact Addresses Test")
        if opted_out:
            lead.opted_out_at = now
            lead.opted_out_keyword = "STOP"
        db.add(lead)
        await db.flush()
        threads: dict[str, int] = {}
        for channel in (["email", "web"] if existing_email_thread else ["web"]):
            conversation = Conversation(
                lead_id=lead.id,
                channel=channel,
                last_at=now - timedelta(minutes=5) if channel == "email" else now,
            )
            db.add(conversation)
            await db.flush()
            threads[channel] = conversation.id
            db.add(
                Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content="I am looking to buy in Denver.",
                    subject="Buying in Denver" if channel == "email" else None,
                    external_id="inbound.contact-address-test" if channel == "email" else None,
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
        await db.commit()
        return lead.id, threads


async def _send(lead_id: int, channel: str | None = None) -> dict[str, object]:
    async with get_session_factory()() as db:
        return await send_human_message(lead_id, REPLY, db, channel=channel)


async def _threads_and_replies(lead_id: int) -> tuple[list[Conversation], list[Message]]:
    async with get_session_factory()() as db:
        conversations = (
            await db.execute(select(Conversation).where(Conversation.lead_id == lead_id))
        ).scalars().all()
        replies = (
            await db.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.lead_id == lead_id,
                    Message.direction == MessageDirection.OUTBOUND,
                )
            )
        ).scalars().all()
        return list(conversations), list(replies)


def _sent_reply(
    result: dict[str, object], replies: list[Message], channel: str, conversation_id: int
) -> None:
    assert result["status"] == "ok", result
    assert result["channel"] == channel
    assert result["outbound_status"] == "sent"
    assert len(replies) == 1
    reply = replies[0]
    assert reply.id == result["outbound_id"]
    assert reply.conversation_id == conversation_id
    assert reply.content == REPLY
    assert reply.sender == MessageSender.HUMAN
    assert reply.delivery_status == MessageStatus.SENT
    assert reply.external_id == PROVIDER_ID
    assert reply.internal is False


@pytest.mark.asyncio
async def test_a_web_lead_with_phone_and_email_receives_the_reply_at_its_email(
    agency: int, dispatch: AsyncMock
) -> None:
    with org_scope(agency):
        lead_id, initial = await _web_lead(PHONE, EMAIL)
        result = await _send(lead_id, "email")
        assert result["status"] == "ok", result
        conversations, replies = await _threads_and_replies(lead_id)

    dispatch.assert_awaited_once_with(
        "email", to=EMAIL, text=REPLY, subject="Tu consulta", in_reply_to=None
    )
    assert {c.channel for c in conversations} == {"web", "email"}
    assert next(c.id for c in conversations if c.channel == "web") == initial["web"]
    email_id = next(c.id for c in conversations if c.channel == "email")
    _sent_reply(result, replies, "email", email_id)


@pytest.mark.asyncio
async def test_a_legacy_email_identifier_still_receives_email(
    agency: int, dispatch: AsyncMock
) -> None:
    with org_scope(agency):
        lead_id, _ = await _web_lead(EMAIL, None)
        result = await _send(lead_id, "email")
        assert result["status"] == "ok", result
        conversations, replies = await _threads_and_replies(lead_id)

    dispatch.assert_awaited_once_with(
        "email", to=EMAIL, text=REPLY, subject="Tu consulta", in_reply_to=None
    )
    email_id = next(c.id for c in conversations if c.channel == "email")
    _sent_reply(result, replies, "email", email_id)


@pytest.mark.asyncio
async def test_a_phone_only_lead_cannot_create_an_undeliverable_email_reply(
    agency: int, dispatch: AsyncMock
) -> None:
    with org_scope(agency):
        lead_id, initial = await _web_lead(PHONE, None)
        result = await _send(lead_id, "email")
        conversations, replies = await _threads_and_replies(lead_id)

    assert result == {"status": "error", "error": "channel_identifier_mismatch"}
    dispatch.assert_not_awaited()
    assert [(c.id, c.channel) for c in conversations] == [(initial["web"], "web")]
    assert replies == []


@pytest.mark.asyncio
async def test_sms_uses_the_phone_when_an_email_address_is_also_available(
    agency: int, dispatch: AsyncMock
) -> None:
    with org_scope(agency):
        lead_id, _ = await _web_lead(PHONE, EMAIL)
        result = await _send(lead_id, "sms")
        assert result["status"] == "ok", result
        conversations, replies = await _threads_and_replies(lead_id)

    dispatch.assert_awaited_once_with(
        "sms", to=PHONE, text=REPLY, subject=None, in_reply_to=None
    )
    sms_id = next(c.id for c in conversations if c.channel == "sms")
    _sent_reply(result, replies, "sms", sms_id)


@pytest.mark.asyncio
async def test_an_available_email_does_not_override_an_opt_out(
    agency: int, dispatch: AsyncMock
) -> None:
    with org_scope(agency):
        lead_id, initial = await _web_lead(PHONE, EMAIL, opted_out=True)
        result = await _send(lead_id, "email")
        conversations, replies = await _threads_and_replies(lead_id)

    assert result["status"] == "error"
    assert result["error"] == "lead_opted_out"
    dispatch.assert_not_awaited()
    assert [(c.id, c.channel) for c in conversations] == [(initial["web"], "web")]
    assert replies == []


@pytest.mark.asyncio
async def test_auto_pick_reuses_the_email_thread_for_a_lead_with_both_contacts(
    agency: int, dispatch: AsyncMock
) -> None:
    with org_scope(agency):
        lead_id, initial = await _web_lead(PHONE, EMAIL, existing_email_thread=True)
        result = await _send(lead_id)
        assert result["status"] == "ok", result
        conversations, replies = await _threads_and_replies(lead_id)

    dispatch.assert_awaited_once_with(
        "email",
        to=EMAIL,
        text=REPLY,
        subject="Re: Buying in Denver",
        in_reply_to="inbound.contact-address-test",
    )
    assert {c.channel: c.id for c in conversations} == initial
    _sent_reply(result, replies, "email", initial["email"])

"""A reply that did not land the first time.

Every channel adapter is one HTTP POST followed by `raise_for_status()`. A Meta
503, a Twilio 429 or a Resend timeout stamped the message FAILED and that was
the end of it — no retry, and nothing anywhere that queried for messages left
PENDING or FAILED. The AI's answer to a lead who wrote at midnight was lost,
with a status column nobody watches as the only trace.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services import tenant_resolver
from app.services.delivery import (
    MAX_ATTEMPTS,
    backoff_for,
    retry_pending_sends,
    schedule_retry,
)
from app.services.tenant_context import org_scope

ORG = 940


async def _agency() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) VALUES "
                "(:i, 'Retry Agency', 'retry-agency', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": ORG},
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        for table in ("messages", "conversations", "leads"):
            await db.execute(text(f"DELETE FROM {table} WHERE org_id = :i"), {"i": ORG})
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": ORG})
        await db.commit()
    tenant_resolver.reset_cache()


def test_the_backoff_gives_up_instead_of_retrying_forever() -> None:
    message = Message(
        conversation_id=1,
        direction=MessageDirection.OUTBOUND,
        sender=MessageSender.AGENT,
        content="hello",
    )
    message.send_attempts = 0
    for _ in range(MAX_ATTEMPTS - 1):
        schedule_retry(message, "provider said 503")
        assert message.next_attempt_at is not None
    schedule_retry(message, "provider said 503")
    assert message.next_attempt_at is None, (
        "a permanently broken message would be retried on every tick forever"
    )
    assert message.last_error == "provider said 503"
    # And the waits grow rather than hammering an outage.
    assert backoff_for(1) < backoff_for(3)


@pytest.mark.asyncio
async def test_a_reply_lost_to_a_provider_blip_is_sent_again() -> None:
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = Lead(phone="+13035558888")
                db.add(lead)
                await db.flush()
                conversation = Conversation(lead_id=lead.id, channel="whatsapp")
                db.add(conversation)
                await db.flush()
                stuck = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Yes, we have three in that zone.",
                    delivery_status=MessageStatus.FAILED,
                )
                stuck.send_attempts = 1
                stuck.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                db.add(stuck)
                await db.commit()
                stuck_id = stuck.id

            sent_to: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                sent_to.append(to)
                return "wamid.resent", None

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _ok):
                    result = await retry_pending_sends(db)
            assert result == {"sent": 1, "failed": 0}
            assert sent_to == ["+13035558888"]

            async with get_session_factory()() as db:
                again = (
                    await db.execute(select(Message).where(Message.id == stuck_id))
                ).scalar_one()
                assert again.delivery_status is MessageStatus.SENT
                assert again.external_id == "wamid.resent"
                assert again.next_attempt_at is None, (
                    "still due, so the next tick would send it a second time"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_reply_that_already_reached_the_provider_is_not_sent_twice() -> None:
    """`external_id` set means the provider took it. Whatever the status column
    says, re-sending would put the same answer in front of the lead again."""
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = Lead(phone="+13035557777")
                db.add(lead)
                await db.flush()
                conversation = Conversation(lead_id=lead.id, channel="whatsapp")
                db.add(conversation)
                await db.flush()
                delivered = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Already went out.",
                    delivery_status=MessageStatus.FAILED,
                    external_id="wamid.already",
                )
                delivered.send_attempts = 1
                delivered.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                db.add(delivered)
                await db.commit()

            async def _boom(*a: object, **k: object) -> tuple[str, None]:
                raise AssertionError("re-sent a message the provider already had")

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    assert await retry_pending_sends(db) == {"sent": 0, "failed": 0}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_turn_itself_marks_a_failed_send_as_retryable() -> None:
    """The sweep can only find what the send path leaves for it.

    Stamping FAILED and nothing else — which is what the code did — leaves
    `next_attempt_at` null, and the sweep's query requires it. The message sits
    there looking handled, forever.
    """
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult

    await _agency()
    try:
        with org_scope(ORG):
            async def _reply(**kwargs: object) -> LLMResult:
                return LLMResult(
                    text="Sure, I can help with that.",
                    provider="kimi",
                    model="k2",
                    input_tokens=1,
                    output_tokens=1,
                )

            async def _send_fails(*a: object, **k: object) -> tuple[str, None]:
                raise RuntimeError("Meta said 503")

            parsed = ParsedMessage(
                channel="whatsapp",
                external_id="wamid.inbound-1",
                from_identifier="+13035556666",
                from_name="A Lead",
                content="Do you have anything in Aurora?",
            )
            async with get_session_factory()() as db:
                with patch(
                    "app.services.conversation.generate_reply", _reply
                ), patch("app.services.conversation._dispatch_send", _send_fails):
                    await handle_inbound_message(parsed, db)

            async with get_session_factory()() as db:
                outbound = (
                    await db.execute(
                        select(Message).where(
                            Message.direction == MessageDirection.OUTBOUND
                        )
                    )
                ).scalars().first()
            assert outbound is not None
            assert outbound.delivery_status is MessageStatus.FAILED
            assert outbound.next_attempt_at is not None, (
                "the sweep will never pick this up; the reply is lost"
            )
            assert outbound.send_attempts == 1
    finally:
        await _cleanup()

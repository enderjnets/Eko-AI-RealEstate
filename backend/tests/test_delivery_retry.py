"""A reply that did not land the first time.

Every channel adapter is one HTTP POST followed by `raise_for_status()`. A Meta
503, a Twilio 429 or a Resend timeout stamped the message FAILED and that was
the end of it — no retry, and nothing anywhere that queried for messages left
PENDING or FAILED. The AI's answer to a lead who wrote at midnight was lost,
with a status column nobody watches as the only trace.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import LeadIntent
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
                # The inbound that started the thread. An agent reply can only
                # exist because one arrived — `handle_inbound_message` is the
                # sole producer of MessageSender.AGENT — and the dispatch gate
                # reads it as the permission to answer on this channel.
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="do you have anything in that zone?",
                        delivery_status=MessageStatus.DELIVERED,
                    )
                )
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
            assert result == {"sent": 1, "failed": 0, "dropped": 0}
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
                # The inbound that started the thread. An agent reply can only
                # exist because one arrived — `handle_inbound_message` is the
                # sole producer of MessageSender.AGENT — and the dispatch gate
                # reads it as the permission to answer on this channel.
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="do you have anything in that zone?",
                        delivery_status=MessageStatus.DELIVERED,
                    )
                )
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
                    assert await retry_pending_sends(db) == {"sent": 0, "failed": 0, "dropped": 0}
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


@pytest.mark.asyncio
async def test_a_message_abandoned_mid_send_is_picked_up() -> None:
    """The scenario the sweep exists for, and the one it could not see.

    `next_attempt_at` is only ever written by `schedule_retry`, which runs when
    a send *fails*. A worker killed between the insert and the POST leaves a row
    PENDING with nothing scheduled — so requiring a schedule excluded exactly
    the crash the module docstring names.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = Lead(phone="+13035553333")
                db.add(lead)
                await db.flush()
                conversation = Conversation(lead_id=lead.id, channel="whatsapp")
                db.add(conversation)
                await db.flush()
                # The inbound that started the thread. An agent reply can only
                # exist because one arrived — `handle_inbound_message` is the
                # sole producer of MessageSender.AGENT — and the dispatch gate
                # reads it as the permission to answer on this channel.
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="do you have anything in that zone?",
                        delivery_status=MessageStatus.DELIVERED,
                    )
                )
                await db.flush()
                abandoned = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Never left the building.",
                    delivery_status=MessageStatus.PENDING,
                )
                db.add(abandoned)
                await db.flush()
                # Older than the in-flight grace period.
                abandoned.created_at = datetime.now(UTC) - timedelta(minutes=30)
                await db.commit()

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                return "wamid.rescued", None

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _ok):
                    assert await retry_pending_sends(db) == {"sent": 1, "failed": 0, "dropped": 0}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_message_still_in_flight_is_left_alone() -> None:
    """The other side of it: a PENDING row seconds old is a send in progress,
    not an abandoned one. Picking it up would race the live turn and deliver
    the same reply twice."""
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = Lead(phone="+13035552222")
                db.add(lead)
                await db.flush()
                conversation = Conversation(lead_id=lead.id, channel="whatsapp")
                db.add(conversation)
                await db.flush()
                # The inbound that started the thread. An agent reply can only
                # exist because one arrived — `handle_inbound_message` is the
                # sole producer of MessageSender.AGENT — and the dispatch gate
                # reads it as the permission to answer on this channel.
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="do you have anything in that zone?",
                        delivery_status=MessageStatus.DELIVERED,
                    )
                )
                await db.flush()
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.OUTBOUND,
                        sender=MessageSender.AGENT,
                        content="Going out right now.",
                        delivery_status=MessageStatus.PENDING,
                    )
                )
                await db.commit()

            async def _boom(*a: object, **k: object) -> tuple[str, None]:
                raise AssertionError("raced a send that was still in flight")

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    assert await retry_pending_sends(db) == {"sent": 0, "failed": 0, "dropped": 0}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_message_with_nowhere_to_go_backs_off_and_then_stops() -> None:
    """Clearing the schedule used to remove a row from the sweep. Once PENDING
    rows with no schedule became eligible — the fix for the crash case — an
    undeliverable one re-qualified on every tick, silently holding a slot in
    every batch forever. Retiring it on the spot fixed that and broke something
    worse: a transient empty read deleted a real pending reply. It backs off
    like any other failure and gives up after the same cap."""
    from app.models.message import MessageStatus as Status
    from app.services.delivery import MAX_ATTEMPTS as CAP

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # An email conversation for a lead with no address at all.
                lead = Lead(phone="+13035551212")
                db.add(lead)
                await db.flush()
                conversation = Conversation(lead_id=lead.id, channel="email")
                db.add(conversation)
                await db.flush()
                # The inbound that started the thread. An agent reply can only
                # exist because one arrived — `handle_inbound_message` is the
                # sole producer of MessageSender.AGENT — and the dispatch gate
                # reads it as the permission to answer on this channel.
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="do you have anything in that zone?",
                        delivery_status=MessageStatus.DELIVERED,
                    )
                )
                await db.flush()
                orphan = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Nowhere to send this.",
                    delivery_status=Status.PENDING,
                )
                db.add(orphan)
                await db.flush()
                orphan.created_at = datetime.now(UTC) - timedelta(minutes=30)
                await db.commit()
                orphan_id = orphan.id

            # One tick costs one attempt, not the message: `_recipient_of` also
            # comes back empty when the lead is momentarily invisible, and
            # retiring on the spot deleted a pending reply for a transient read.
            async with get_session_factory()() as db:
                assert await retry_pending_sends(db) == {"sent": 0, "failed": 1, "dropped": 0}

            async with get_session_factory()() as db:
                after = (
                    await db.execute(select(Message).where(Message.id == orphan_id))
                ).scalar_one()
                assert after.send_attempts == 1
                assert after.delivery_status is Status.FAILED
                assert after.next_attempt_at is not None

            # It backs off rather than spinning: nothing is due yet.
            async with get_session_factory()() as db:
                assert await retry_pending_sends(db) == {"sent": 0, "failed": 0, "dropped": 0}

            # And after CAP attempts it stops for good.
            async with get_session_factory()() as db:
                due = (
                    await db.execute(select(Message).where(Message.id == orphan_id))
                ).scalar_one()
                due.send_attempts = CAP - 1
                due.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                await db.commit()
            async with get_session_factory()() as db:
                assert await retry_pending_sends(db) == {"sent": 0, "failed": 1, "dropped": 0}
            async with get_session_factory()() as db:
                assert await retry_pending_sends(db) == {"sent": 0, "failed": 0, "dropped": 0}
                final = (
                    await db.execute(select(Message).where(Message.id == orphan_id))
                ).scalar_one()
                assert final.next_attempt_at is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_two_workers_cannot_send_the_same_message() -> None:
    """The sweep runs in every replica. Locking the whole batch and committing
    per message released the locks on every row still waiting, so a second
    worker picked them up and the lead got the same answer twice — caused by
    the commit added to stop a cancellation replaying the batch."""
    import asyncio

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = Lead(phone="+13035559999")
                db.add(lead)
                await db.flush()
                conversation = Conversation(lead_id=lead.id, channel="whatsapp")
                db.add(conversation)
                await db.flush()
                # The inbound that started the thread. An agent reply can only
                # exist because one arrived — `handle_inbound_message` is the
                # sole producer of MessageSender.AGENT — and the dispatch gate
                # reads it as the permission to answer on this channel.
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="do you have anything in that zone?",
                        delivery_status=MessageStatus.DELIVERED,
                    )
                )
                await db.flush()
                one = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Exactly once, please.",
                    delivery_status=MessageStatus.FAILED,
                )
                one.send_attempts = 1
                one.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                db.add(one)
                await db.commit()

            deliveries: list[str] = []
            started = asyncio.Event()

            async def _slow_send(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                deliveries.append(to)
                started.set()
                # Long enough that the second worker is inside its SELECT while
                # the first still holds the row.
                await asyncio.sleep(0.4)
                return f"wamid.{len(deliveries)}", None

            async def _worker() -> dict[str, int]:
                async with get_session_factory()() as db:
                    with patch("app.services.conversation._dispatch_send", _slow_send):
                        return await retry_pending_sends(db)

            first, second = await asyncio.gather(_worker(), _worker())
        assert len(deliveries) == 1, (
            f"delivered {len(deliveries)} times; the lead sees the same reply twice"
        )
        assert (first["sent"], second["sent"]) in ((1, 0), (0, 1))
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_queued_message_is_held_back_when_nothing_permits_sending_it() -> None:
    """The other half of the dispatch gate.

    The block above it honours a revocation; this covers the case where
    permission never existed. An automated message can sit in the queue while
    the lead turns out to have neither consent on record nor a message they
    sent us first — the producer's gate having been the only one, and having
    run before the row existed.

    It became reachable a second way with the call console: telling an advisor
    "phone me, don't text me" cancels the follow-ups but cannot cancel a text
    that is already queued.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = Lead(phone="+13035554141")
                db.add(lead)
                await db.flush()
                # No inbound anywhere, and no consent on record: nothing
                # permits an automated SMS to this person.
                conversation = Conversation(lead_id=lead.id, channel="sms")
                db.add(conversation)
                await db.flush()
                queued = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="a few options I thought you'd like",
                    delivery_status=MessageStatus.PENDING,
                )
                queued.next_attempt_at = datetime.now(UTC) - timedelta(minutes=5)
                db.add(queued)
                await db.commit()
                queued_id = queued.id

            sent_to: list[str] = []

            async def _record(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                sent_to.append(to)
                return "should-not-happen", None

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _record):
                    result = await retry_pending_sends(db)

            assert sent_to == [], "sent a message nothing permitted"
            assert result["sent"] == 0

            async with get_session_factory()() as db:
                row = (
                    await db.execute(select(Message).where(Message.id == queued_id))
                ).scalar_one()
                assert "no permission" in (row.last_error or "")
                # Backed off, not retired. Unlike an opt-out this answer can
                # turn into a yes — they consent, or they write to us on this
                # channel — and killing the row would discard a message the
                # very next reply would have permitted. It still reaches the
                # attempt cap on its own if nothing changes.
                assert row.next_attempt_at is not None, "retired a recoverable message"
                assert row.send_attempts == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_impossible_budget_does_not_cost_us_the_message() -> None:
    """A regression I caused, and the worst kind.

    Adding CHECK constraints to `leads` closed a silent data problem — a range
    the wrong way round matches no house at all — but the classifier reads free
    text with a language model and was bounded nowhere. A negative extraction
    reached the constraint, the constraint aborted the transaction, and the
    transaction was the one storing the customer's message. Deterministic, so
    the provider's retries failed identically: the message was gone, and the
    lead with it. One missing field is a far cheaper failure than that.
    """
    from app.services._common import ParsedMessage
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult

    await _agency()
    try:
        with org_scope(ORG):
            async def _reply(**kwargs: object) -> LLMResult:
                return LLMResult(
                    text="Happy to help.", provider="kimi", model="k2",
                    input_tokens=1, output_tokens=1,
                )

            async def _classify(*a: object, **k: object) -> IntentResult:
                # What a model actually does with "I don't want to go under
                # 100k" — it reads the sign and hands back a negative.
                return IntentResult(
                    intent=LeadIntent.BUY,
                    confidence=0.9,
                    entities=IntentEntities.model_construct(
                        budget_min=-50_000.0, budget_max=None, zone="Brickell"
                    ),
                )

            async def _sent(*a: object, **k: object) -> tuple[str, None]:
                return ("sent", None)

            parsed = ParsedMessage(
                channel="whatsapp",
                external_id="wamid.budget-regression",
                from_identifier="+13035557777",
                from_name="A Lead",
                content="Looking in Brickell, nothing under 100k",
            )
            async with get_session_factory()() as db:
                with patch(
                    "app.services.conversation.generate_reply", _reply
                ), patch(
                    "app.services.conversation.classify_intent", _classify
                ), patch("app.services.conversation._dispatch_send", _sent):
                    await handle_inbound_message(parsed, db)

            async with get_session_factory()() as db:
                stored = (
                    await db.execute(
                        select(Message).where(
                            Message.external_id == "wamid.budget-regression"
                        )
                    )
                ).scalar_one_or_none()
                assert stored is not None, "the customer's message was destroyed"

                lead = (
                    await db.execute(select(Lead).where(Lead.org_id == ORG))
                ).scalars().first()
                assert lead is not None, "the lead was lost with the message"
                assert lead.budget_min is None, "an unstorable budget was written anyway"
                assert lead.zone == "Brickell", "the usable half of the extraction was dropped"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_impossible_voice_payload_does_not_cost_us_the_call() -> None:
    """The same failure as the chat path, on the route the fix did not visit.

    `structuredData` is a voice agent's reading of a phone call — as much a
    guess as the chat classifier's — and it is applied inside the transaction
    that stores the caller's transcript. A value the table refuses does not
    lose a field, it loses the record of the call, and VAPI redelivers the same
    payload so every retry fails identically.

    Six of the seven payloads below used to destroy that transaction; the
    seventh raised `OverflowError` before reaching the database, which nothing
    caught either.
    """
    from app.services.conversation import ingest_voice_call
    from app.services.voice import VoiceCallReport

    hostile = [
        {"budget_min": -50_000},
        {"budget_min": 900_000, "budget_max": 100_000},
        {"budget_max": 1e13},
        {"budget_max": float("inf")},
        {"budget_max": float("nan")},
        {"zone": "z" * 400},
        {"urgency": "as soon as possible, ideally within the next thirty days"},
    ]

    await _agency()
    try:
        with org_scope(ORG):
            for i, structured in enumerate(hostile):
                report = VoiceCallReport(
                    call_id=f"call-hostile-{i}",
                    from_identifier=f"+1303555{i:04d}",
                    from_name="A Caller",
                    summary="They asked about Brickell.",
                    turns=[("user", "I'm looking for a condo"), ("agent", "Of course.")],
                    structured=structured,
                )
                async with get_session_factory()() as db:
                    await ingest_voice_call(report, db)

            async with get_session_factory()() as db:
                stored = (
                    await db.execute(
                        select(Message).where(
                            Message.content.like("%looking for a condo%")
                        )
                    )
                ).scalars().all()
                assert len(stored) == len(hostile), (
                    f"{len(hostile) - len(stored)} call transcripts were destroyed"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_redelivered_call_does_not_undo_a_hand_correction() -> None:
    """A regression I introduced, of a different kind to the message loss.

    The voice applier used to write a budget only into an empty field. Routing
    it through `merge_budget` let a complete extracted range win — and this
    function runs on every delivery of a report, redeliveries included. So the
    realtor listens to the call, corrects 100k-900k to 300k-400k, VAPI resends
    the identical payload, and their correction is gone with nothing to show it
    ever happened.
    """
    from app.services.conversation import ingest_voice_call
    from app.services.voice import VoiceCallReport

    report = VoiceCallReport(
        call_id="call-redelivery",
        from_identifier="+13035558888",
        from_name="A Caller",
        summary="Asked about condos.",
        turns=[("user", "Somewhere between one and nine hundred"), ("agent", "Noted.")],
        structured={"budget_min": 100_000, "budget_max": 900_000},
    )

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await ingest_voice_call(report, db)

            # The realtor was on the call and knows better.
            async with get_session_factory()() as db:
                lead = (
                    await db.execute(
                        select(Lead).where(Lead.phone == "+13035558888")
                    )
                ).scalar_one()
                lead.budget_min = Decimal("300000")
                lead.budget_max = Decimal("400000")
                await db.commit()

            # VAPI resends the same report.
            async with get_session_factory()() as db:
                await ingest_voice_call(report, db)

            async with get_session_factory()() as db:
                lead = (
                    await db.execute(
                        select(Lead).where(Lead.phone == "+13035558888")
                    )
                ).scalar_one()
                assert lead.budget_min == Decimal("300000.00"), (
                    "a redelivered call overwrote the realtor's correction"
                )
                assert lead.budget_max == Decimal("400000.00")
    finally:
        await _cleanup()

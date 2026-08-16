"""A send that failed must not be able to look like a send that worked.

Three surfaces told the same lie from one root: the outbound row was marked
FAILED and handed to nobody. `next_attempt_at` stayed NULL, which matches
neither branch of the retry sweep's query, so the message sat in the database
forever — while the composer cleared its box and the inbox stopped counting the
lead as waiting. The realtor believed they had answered; the client never heard
from them; nothing anywhere said otherwise.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.conversation import Conversation
from app.models.follow_up import FollowUp, FollowUpKind, FollowUpStatus
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services import tenant_resolver
from app.services.conversation import send_human_message
from app.services.delivery import retry_pending_sends
from app.services.followups import process_due_followups
from app.services.inbox import gather_inbox
from app.services.tenant_context import org_scope

ORG = 941


async def _agency() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) VALUES "
                "(:i, 'Stranded Agency', 'stranded-agency', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": ORG},
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        for table in ("follow_ups", "messages", "conversations", "leads"):
            await db.execute(text(f"DELETE FROM {table} WHERE org_id = :i"), {"i": ORG})
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": ORG})
        await db.commit()
    tenant_resolver.reset_cache()


async def _lead_with_thread(
    db, phone: str, *, with_inbound: bool = True
) -> tuple[int, int]:
    """A lead and an sms conversation. The inbound is what gives consent."""
    lead = Lead(phone=phone)
    db.add(lead)
    await db.flush()
    conversation = Conversation(lead_id=lead.id, channel="sms")
    db.add(conversation)
    await db.flush()
    if with_inbound:
        db.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.INBOUND,
                sender=MessageSender.LEAD,
                content="is the Highlands place still available?",
                delivery_status=MessageStatus.DELIVERED,
            )
        )
        await db.flush()
    await db.commit()
    return lead.id, conversation.id


async def _boom(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
    raise RuntimeError("provider returned 503")


@pytest.mark.asyncio
async def test_a_human_reply_the_provider_refused_is_queued_not_stranded() -> None:
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557001")

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    result = await send_human_message(lead_id, "On my way over.", db)

            assert result["outbound_status"] == "failed"

            async with get_session_factory()() as db:
                row = (
                    await db.execute(
                        select(Message).where(
                            Message.id == result["outbound_id"]  # type: ignore[arg-type]
                        )
                    )
                ).scalar_one()
                assert row.delivery_status == MessageStatus.FAILED
                assert row.send_attempts == 1
                # The whole point. NULL here is the stranding.
                assert row.next_attempt_at is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_queue_does_not_judge_a_human_reply_by_automated_consent() -> None:
    """No consent, no inbound — an automated message may not go, a human's may.

    `send_human_message` already made that call at the door: it checks the
    opt-out and deliberately not the automated-consent gate. Applying the gate
    on the way out of the queue would take a reply the product permitted and
    hold it until it died of attempts.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                _, conversation_id = await _lead_with_thread(
                    db, "+13035557002", with_inbound=False
                )
                stranded = Message(
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.HUMAN,
                    content="Following up on the showing.",
                    delivery_status=MessageStatus.FAILED,
                )
                stranded.send_attempts = 1
                stranded.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                db.add(stranded)
                await db.commit()

            sent_to: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                sent_to.append(to)
                return "sm.resent", None

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _ok):
                    result = await retry_pending_sends(db)

            assert result["sent"] == 1, result
            assert result["dropped"] == 0, result
            assert sent_to == ["+13035557002"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_queue_still_refuses_an_automated_message_without_consent() -> None:
    """The other half of the same rule — the gate that protects the licence stays."""
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                _, conversation_id = await _lead_with_thread(
                    db, "+13035557003", with_inbound=False
                )
                nurture = Message(
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Just checking in about your search!",
                    delivery_status=MessageStatus.FAILED,
                )
                nurture.send_attempts = 1
                nurture.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                db.add(nurture)
                await db.commit()

            sent_to: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                sent_to.append(to)
                return "sm.nope", None

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _ok):
                    result = await retry_pending_sends(db)

            assert result["sent"] == 0, result
            assert sent_to == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_queue_still_refuses_a_human_reply_to_someone_who_opted_out() -> None:
    """Opt-out is absolute and outranks the human/automated distinction."""
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, conversation_id = await _lead_with_thread(db, "+13035557004")
                lead = await db.get(Lead, lead_id)
                lead.opted_out_at = datetime.now(UTC)
                lead.opted_out_keyword = "STOP"
                stranded = Message(
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.HUMAN,
                    content="One more listing for you.",
                    delivery_status=MessageStatus.FAILED,
                )
                stranded.send_attempts = 1
                stranded.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
                db.add(stranded)
                await db.commit()

            sent_to: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                sent_to.append(to)
                return "sm.never", None

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _ok):
                    result = await retry_pending_sends(db)

            assert sent_to == []
            assert result["dropped"] == 1, result
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_follow_up_the_provider_refused_is_queued_not_stranded() -> None:
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557006")
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
                    )
                )
                await db.commit()

            async with get_session_factory()() as db:
                # Patched where it is used, not where it is defined: followups
                # imported the name into its own module at import time.
                with patch("app.services.followups._dispatch_send", _boom):
                    result = await process_due_followups(db)
            assert result["failed"] == 1, result

            async with get_session_factory()() as db:
                outbound = (
                    await db.execute(
                        select(Message).where(
                            Message.direction == MessageDirection.OUTBOUND
                        )
                    )
                ).scalars().all()
                assert len(outbound) == 1
                assert outbound[0].next_attempt_at is not None, (
                    "the nurture message was marked failed and handed to nobody"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_bad_lead_does_not_resend_the_message_the_last_one_received() -> None:
    """The batch committed once, at the end. A raise after a successful dispatch
    threw away the row saying it had been sent — so the next tick sent it again,
    to somebody who already had it, at TCPA exposure per message."""
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                first_id, _ = await _lead_with_thread(db, "+13035557007")
                second_id, _ = await _lead_with_thread(db, "+13035557008")
                db.add(
                    FollowUp(
                        lead_id=first_id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=10),
                    )
                )
                db.add(
                    FollowUp(
                        lead_id=second_id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
                    )
                )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(to)
                return "sm.nurture", None

            real_gate = None

            async def _gate_explodes(lead, channel, db):  # noqa: ANN001, ANN202
                if lead.id == second_id:
                    raise RuntimeError("consent lookup blew up")
                return await real_gate(lead, channel, db)

            from app.services import followups as followups_module

            real_gate = followups_module.may_send_automated

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    with patch.object(
                        followups_module, "may_send_automated", _gate_explodes
                    ):
                        await process_due_followups(db)

            assert delivered == ["+13035557007"]

            # Read from a session that never saw the batch: the SENT row has to
            # be on disk, not merely in the identity map of a session that was
            # about to be rolled back.
            async with get_session_factory()() as db:
                first_fu = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == first_id)
                    )
                ).scalar_one()
                assert first_fu.status == FollowUpStatus.SENT, (
                    "a delivered message lost its record and will be sent again"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_worker_killed_mid_batch_keeps_what_it_already_delivered() -> None:
    """The case `except Exception` cannot save: a restart or a deploy.

    A cancelled task unwinds straight past every handler in the loop, so with a
    single commit at the end the batch died holding the only record that a
    message had gone out — and the next tick sent it again.
    """
    import asyncio

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                first_id, _ = await _lead_with_thread(db, "+13035557009")
                second_id, _ = await _lead_with_thread(db, "+13035557010")
                for lead_id, minutes in ((first_id, 10), (second_id, 5)):
                    db.add(
                        FollowUp(
                            lead_id=lead_id,
                            kind=FollowUpKind.POST_VISIT_24H,
                            status=FollowUpStatus.PENDING,
                            scheduled_for=datetime.now(UTC) - timedelta(minutes=minutes),
                        )
                    )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(to)
                return "sm.nurture", None

            from app.services import followups as followups_module

            real_gate = followups_module.may_send_automated

            async def _cancelled_on_the_second(lead, channel, db):  # noqa: ANN001, ANN202
                if lead.id == second_id:
                    raise asyncio.CancelledError()
                return await real_gate(lead, channel, db)

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    with patch.object(
                        followups_module, "may_send_automated", _cancelled_on_the_second
                    ):
                        with pytest.raises(asyncio.CancelledError):
                            await process_due_followups(db)

            assert delivered == ["+13035557009"]

            async with get_session_factory()() as db:
                first_fu = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == first_id)
                    )
                ).scalar_one()
                assert first_fu.status == FollowUpStatus.SENT, (
                    "the batch was killed still holding the only record of a "
                    "message that had already gone out"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_reply_that_never_sent_leaves_the_lead_waiting_in_the_inbox() -> None:
    """Composing is not answering. The failed outbound became the newest message
    and the lead dropped out of Pending — hiding the person still waiting from
    the one screen where somebody would have noticed."""
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557005")

            async with get_session_factory()() as db:
                items = await gather_inbox(db)
                before = next(i for i in items if i.lead.id == lead_id)
                assert before.needs_response is True

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    await send_human_message(lead_id, "Sorry for the delay!", db)

            async with get_session_factory()() as db:
                items = await gather_inbox(db)
                after = next(i for i in items if i.lead.id == lead_id)
                assert after.needs_response is True, (
                    "a reply that never reached anybody marked the lead answered"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_back_dated_visit_does_not_fire_its_whole_sequence_at_once() -> None:
    """Three nurture messages seconds apart is not a nurture sequence.

    The reminder has always been scheduled only if it is still in the future.
    The three post-visit messages were scheduled unconditionally, so a visit
    entered with a past date arrived already overdue on all three and the next
    sweep sent them together.
    """
    from app.models.visit import Visit, VisitStatus
    from app.services.followups import enqueue_for_visit

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557011")
                long_past = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-backdated-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=30),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(long_past)
                await db.commit()
                created = await enqueue_for_visit(long_past, db)
                assert created == 0, (
                    f"{created} follow-ups queued for a visit 30 days in the past"
                )

            # Two days ago: the 24h message is already moot, the 72h and 7d
            # ones are still ahead and should survive.
            async with get_session_factory()() as db:
                second_lead, _ = await _lead_with_thread(db, "+13035557012")
                recent = Visit(
                    lead_id=second_lead,
                    calendar_provider="manual",
                    external_booking_id="manual-backdated-2",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=2),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(recent)
                await db.commit()
                assert await enqueue_for_visit(recent, db) == 2

            async with get_session_factory()() as db:
                kinds = {
                    fu.kind
                    for fu in (
                        await db.execute(
                            select(FollowUp).where(FollowUp.lead_id == second_lead)
                        )
                    ).scalars().all()
                }
                assert kinds == {FollowUpKind.POST_VISIT_72H, FollowUpKind.POST_VISIT_7D}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_whose_only_message_failed_is_still_in_the_inbox() -> None:
    """Demoting the row is not the same as removing it.

    The first version of the inbox fix filtered failed outbounds out of the
    query. `gather_inbox` builds its lead set from that query's keys, so a lead
    whose only message is a failed first outreach lost every row and vanished
    from the inbox entirely — every tab, not just Pending. That is the defect
    this was meant to fix, made worse: the client the realtor could not reach
    disappeared from the screen where they would have noticed.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # No inbound at all: a discovery import, or a number typed in.
                lead_id, _ = await _lead_with_thread(
                    db, "+13035557013", with_inbound=False
                )

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    await send_human_message(lead_id, "Hi — saw you were looking.", db)

            async with get_session_factory()() as db:
                items = await gather_inbox(db)
                assert any(i.lead.id == lead_id for i in items), (
                    "the lead vanished from the inbox after the outreach failed"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_inbox_and_the_leads_list_agree_on_who_is_waiting() -> None:
    """Two screens, one rule. They drifted the first time it changed."""
    from app.api.v1.leads import _needs_response_map

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557014")

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    await send_human_message(lead_id, "Sorry for the delay!", db)

            async with get_session_factory()() as db:
                inbox_says = next(
                    i.needs_response for i in await gather_inbox(db) if i.lead.id == lead_id
                )
                leads_says = (await _needs_response_map(db, [lead_id])).get(lead_id, False)
            assert inbox_says == leads_says is True, (
                f"inbox={inbox_says} leads={leads_says} — the two screens disagree "
                "about the same lead"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_database_error_on_one_follow_up_does_not_starve_the_queue() -> None:
    """The failure class the handler names, which its first version could not survive.

    Without a rollback the transaction stays aborted, so the next item's query
    raises outside every handler and the batch dies — and the attempts counter
    meant to bound the bad row is written into the doomed transaction and lost,
    so it can never give up. The row stays PENDING and due, sorts first by
    `scheduled_for`, and starves that tenant's whole nurture queue on every tick.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                bad_lead, _ = await _lead_with_thread(db, "+13035557015")
                good_lead, _ = await _lead_with_thread(db, "+13035557016")
                for lead_id, minutes in ((bad_lead, 20), (good_lead, 10)):
                    db.add(
                        FollowUp(
                            lead_id=lead_id,
                            kind=FollowUpKind.POST_VISIT_24H,
                            status=FollowUpStatus.PENDING,
                            scheduled_for=datetime.now(UTC) - timedelta(minutes=minutes),
                        )
                    )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(to)
                return "sm.nurture", None

            from app.services import followups as followups_module

            real_gate = followups_module.may_send_automated

            async def _breaks_the_session(lead, channel, db):  # noqa: ANN001, ANN202
                if lead.id == bad_lead:
                    # A real database error, not a bare exception: this is what
                    # leaves the transaction aborted.
                    await db.execute(text("SELECT no_such_column_at_all"))
                return await real_gate(lead, channel, db)

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    with patch.object(
                        followups_module, "may_send_automated", _breaks_the_session
                    ):
                        await process_due_followups(db)

            # The healthy lead behind the bad row still got its message.
            assert delivered == ["+13035557016"], delivered

            async with get_session_factory()() as db:
                bad_fu = (
                    await db.execute(select(FollowUp).where(FollowUp.lead_id == bad_lead))
                ).scalar_one()
                assert bad_fu.attempts == 1, (
                    "the give-up counter was rolled back with the failed "
                    "transaction, so the bad row can never be given up on"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_come_back_confirmation_is_retried() -> None:
    """Someone who replies START consented by definition and is waiting for it.

    The opt-OUT confirmation is deliberately never retried — a failed goodbye
    must not leave a door open. The same handler covered the opt-IN branch,
    where that reasoning is backwards: it left the person believing they had
    resubscribed to silence.
    """
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557017")
                lead = await db.get(Lead, lead_id)
                lead.opted_out_at = datetime.now(UTC)
                lead.opted_out_keyword = "STOP"
                await db.commit()

            async with get_session_factory()() as db:
                with patch("app.services.conversation._dispatch_send", _boom):
                    await handle_inbound_message(
                        ParsedMessage(
                            channel="sms",
                            from_identifier="+13035557017",
                            from_name="Restart Tester",
                            content="START",
                            external_id="sms-restart-1",
                        ),
                        db,
                    )

            async with get_session_factory()() as db:
                lead = await db.get(Lead, lead_id)
                assert lead.opted_out_at is None, "START did not resubscribe them"
                ack = (
                    await db.execute(
                        select(Message)
                        .where(Message.direction == MessageDirection.OUTBOUND)
                        .order_by(Message.id.desc())
                        .limit(1)
                    )
                ).scalar_one()
                assert ack.next_attempt_at is not None, (
                    "the confirmation they asked for was dropped, not queued"
                )
    finally:
        await _cleanup()

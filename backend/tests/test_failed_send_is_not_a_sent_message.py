"""A send that failed must not be able to look like a send that worked.

Three surfaces told the same lie from one root: the outbound row was marked
FAILED and handed to nobody. `next_attempt_at` stayed NULL, which matches
neither branch of the retry sweep's query, so the message sat in the database
forever — while the composer cleared its box and the inbox stopped counting the
lead as waiting. The realtor believed they had answered; the client never heard
from them; nothing anywhere said otherwise.
"""
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

import app.services.followups
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.conversation import Conversation
from app.models.follow_up import FollowUp, FollowUpKind, FollowUpStatus
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.models.visit import Visit, VisitStatus
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


@pytest.mark.asyncio
async def test_one_items_rollback_does_not_undo_the_previous_items_work() -> None:
    """The rollback that stopped the batch dying was throwing away its neighbours.

    The skip, cancel and hold branches never committed — they relied on the one
    commit at the end. So when a later item errored and rolled back, a terminal
    SKIPPED reverted to PENDING and, worse, a held follow-up lost both its
    incremented counter and its one-day delay: it could never advance toward
    giving up and stayed at the head of every tick's queue. Exactly the
    starvation the rollback was added to prevent, moved onto the neighbours.
    """
    from app.services import followups as followups_module

    await _agency()

    async def run(with_raiser: bool) -> dict[str, tuple[str, int]]:
        async with get_session_factory()() as db:
            for table in ("follow_ups", "messages", "conversations", "leads"):
                await db.execute(text(f"DELETE FROM {table} WHERE org_id = {ORG}"))
            await db.commit()

        async with get_session_factory()() as db:
            # Handled first (oldest): human takeover, a terminal SKIPPED.
            skipped_lead, _ = await _lead_with_thread(db, "+13035557018")
            lead = await db.get(Lead, skipped_lead)
            lead.human_takeover = True
            # Then a lead with no consent at all: the HOLD path.
            held_lead, _ = await _lead_with_thread(db, "+13035557019", with_inbound=False)
            # Last: the one that raises.
            raiser_lead, _ = await _lead_with_thread(db, "+13035557020")
            for lead_id, minutes in (
                (skipped_lead, 90), (held_lead, 60), (raiser_lead, 30)
            ):
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=minutes),
                    )
                )
            await db.commit()

        real = followups_module.reachable_active_conversations

        async def maybe_boom(lead_id, phone, db):  # noqa: ANN001, ANN202
            if with_raiser and lead_id == raiser_lead:
                raise RuntimeError("simulated failure choosing a channel")
            return await real(lead_id, phone, db)

        async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
            return "sm.x", None

        async with get_session_factory()() as db:
            with patch("app.services.followups._dispatch_send", _ok):
                with patch.object(
                    followups_module, "reachable_active_conversations", maybe_boom
                ):
                    await process_due_followups(db)

        async with get_session_factory()() as db:
            out = {}
            for fu in (await db.execute(select(FollowUp))).scalars().all():
                lead_row = await db.get(Lead, fu.lead_id)
                out[lead_row.phone] = (fu.status.value, fu.attempts)
            # The raiser itself is expected to differ between the two runs —
            # that is the whole setup. Only its neighbours are under test.
            out.pop("+13035557020", None)
            return out

    try:
        with org_scope(ORG):
            control = await run(with_raiser=False)
            with_error = await run(with_raiser=True)

        assert control == with_error, (
            f"a later item's rollback changed its neighbours' outcomes: "
            f"{control} became {with_error}"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_send_that_just_failed_is_still_the_newest_thing_shown() -> None:
    """Ranking the failed row out of the *display* hid the attempt entirely.

    The lead has an older delivered message and a send that failed a moment ago.
    What the realtor must see is the failed attempt, at its own time — otherwise
    the inbox shows a day-old conversation and the lead falls out of the recent
    activity window, which is where somebody would have caught it.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, conversation_id = await _lead_with_thread(db, "+13035557021")
                old = (
                    await db.execute(
                        select(Message).where(
                            Message.conversation_id == conversation_id
                        )
                    )
                ).scalar_one()
                old.created_at = datetime.now(UTC) - timedelta(hours=30)
                failed = Message(
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.HUMAN,
                    content="Trying to reach you about the showing.",
                    delivery_status=MessageStatus.FAILED,
                )
                failed.created_at = datetime.now(UTC) - timedelta(hours=1)
                db.add(failed)
                await db.commit()
                failed_at = failed.created_at

            async with get_session_factory()() as db:
                item = next(i for i in await gather_inbox(db) if i.lead.id == lead_id)

            assert item.last_message_at == failed_at, (
                "the inbox showed the previous message instead of the failed send"
            )
            assert item.last_direction == "outbound"
            # And the lead is still owed an answer: the newest message that
            # actually reached anybody is their inbound.
            assert item.needs_response is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_leads_list_honours_handled_too() -> None:
    """The other half of the rule the docstring claimed to mirror."""
    from app.api.v1.leads import _needs_response_map
    from app.services.inbox import set_handled

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557022")

            async with get_session_factory()() as db:
                assert (await _needs_response_map(db, [lead_id]))[lead_id] is True
                set_handled(await db.get(Lead, lead_id), datetime.now(UTC))
                await db.commit()

            async with get_session_factory()() as db:
                inbox_says = next(
                    i.needs_response for i in await gather_inbox(db) if i.lead.id == lead_id
                )
                leads_says = (await _needs_response_map(db, [lead_id])).get(lead_id, False)
            assert inbox_says is False and leads_says is False, (
                f"handled lead: inbox={inbox_says} leads={leads_says}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_outage_does_not_release_the_whole_sequence_at_once() -> None:
    """The grace window guards creation; a worker outage bypasses creation.

    These rows were scheduled correctly, days apart. Nobody ran the worker for a
    week, so all three came due on their own — and the first tick back would
    have sent "how did it go?", the nudge and "new listings" seconds apart. The
    same staleness rule has to hold at send time, not only at enqueue time.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557023")
                for kind, days in (
                    (FollowUpKind.POST_VISIT_24H, 8),
                    (FollowUpKind.POST_VISIT_72H, 7),
                    (FollowUpKind.POST_VISIT_7D, 3),
                ):
                    db.add(
                        FollowUp(
                            lead_id=lead_id,
                            kind=kind,
                            status=FollowUpStatus.PENDING,
                            scheduled_for=datetime.now(UTC) - timedelta(days=days),
                        )
                    )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:20])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert len(delivered) <= 1, (
                f"the backlog fired {len(delivered)} messages in one sweep: {delivered}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_outage_does_not_cancel_a_sequence_that_was_being_held() -> None:
    """The staleness rule must not eat the rows the hold exists to protect.

    A follow-up with no consented channel is deferred a day at a time, for up to
    two weeks, and its `scheduled_for` moves with each hold. Judging staleness by
    that moving date meant one worker outage longer than a day cancelled every
    held sequence in the system — throwing away the grace it was waiting on.
    An outage is exactly the case where nobody touched the row: attempts is 0.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # No inbound: nothing may be sent to this lead automatically.
                lead_id, _ = await _lead_with_thread(db, "+13035557024", with_inbound=False)
                held = FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.POST_VISIT_24H,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=30),
                )
                # A held row says so: since migration 032 the deferral lives in
                # its own column, and 033 backfilled the ones that predate it.
                held.postponed_until = datetime.now(UTC) - timedelta(minutes=1)
                held.consent_holds = 3
                db.add(held)
                await db.commit()
                held_id = held.id

            async with get_session_factory()() as db:
                await process_due_followups(db)

            async with get_session_factory()() as db:
                row = await db.get(FollowUp, held_id)
                assert row.status != FollowUpStatus.CANCELLED, (
                    "an outage cancelled a sequence that was being held for consent"
                )
                assert row.consent_holds == 4, "it should have been held once more"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_sequence_held_past_the_give_up_is_not_released_later() -> None:
    """What actually bounds a held sequence, now that `scheduled_for` is honest.

    An earlier version guarded this with an absolute lateness bound computed
    from constants, because a hold overwrote `scheduled_for` and there was no
    other way to tell "deferred yesterday" from "abandoned a month ago". That
    guess was sized for one visit and cancelled the "how did it go?" message
    for a lead with three visits the same day.

    With the deferral in its own column the guess is unnecessary: a held row is
    bounded by the give-up counter, and a row nobody ever touched is bounded by
    its own untouched `scheduled_for`. This checks the first half — held past
    the fortnight, it is given up rather than released weeks later.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557025", with_inbound=False)
                exhausted = FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.POST_VISIT_24H,
                    status=FollowUpStatus.PENDING,
                    # Inside `_MAX_LATENESS`, so the give-up counter is what
                    # decides here and not the lateness ceiling in front of it.
                    scheduled_for=datetime.now(UTC) - timedelta(days=20),
                )
                exhausted.postponed_until = datetime.now(UTC) - timedelta(minutes=1)
                exhausted.consent_holds = 15  # one past the fortnight of daily holds
                db.add(exhausted)
                await db.commit()
                fu_id = exhausted.id

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:18])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert delivered == [], f"a sequence held out of time still sent: {delivered}"
            async with get_session_factory()() as db:
                assert (await db.get(FollowUp, fu_id)).status == FollowUpStatus.SKIPPED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_only_one_post_visit_message_reaches_a_lead_per_sweep() -> None:
    """The cap that does not depend on getting the dates right.

    The consent hold pushes every due row to the same tomorrow, so a fortnight
    of holds collapses the 24h/72h/7d cadence onto one tick and consent arriving
    releases all three together — a route neither grace can see, because both
    reason about when a row is due rather than about what the lead receives.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557026")
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-burst-2",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=2),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                for kind in (
                    FollowUpKind.POST_VISIT_24H,
                    FollowUpKind.POST_VISIT_72H,
                    FollowUpKind.POST_VISIT_7D,
                ):
                    db.add(
                        FollowUp(
                            lead_id=lead_id,
                            visit_id=visit.id,
                            kind=kind,
                            status=FollowUpStatus.PENDING,
                            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                        )
                    )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:60])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert len(delivered) == 1, (
                f"the lead received {len(delivered)} messages in one sweep: {delivered}"
            )
            # And it is the RIGHT one. Asserting only the count let the cadence
            # invert unnoticed: the tie-break that orders these is `id`, which
            # is only the cadence because `_POST_VISIT_OFFSETS` happens to be
            # written 24h/72h/7d — reordering those three lines is a cosmetic
            # edit no reviewer would stop, and it would silently send "new
            # listings similar to what you saw" before "how did it go?".
            assert "how did the visit go" in delivered[0].lower(), (
                f"the sequence started with the wrong message: {delivered[0]!r}"
            )
    finally:
        await _cleanup()


def test_two_untouched_post_visit_messages_cannot_be_overdue_at_once() -> None:
    """The invariant behind the grace window, checked against the real numbers.

    A comment used to assert this and got the reason wrong — it said the window
    was the smallest gap between offsets when it is the smallest offset. Both
    happen to be safe today, so the prose stayed true while the property it
    claimed to guarantee would have broken the moment somebody added a fourth
    message closer than the window to its neighbour.

    Checked against `_SEND_STALE_AFTER`, which is the window that actually
    decides whether a row is still sendable — the first version of this test
    guarded `_POST_VISIT_GRACE`, an hour narrower, and so had the very defect
    its own docstring is about.

    Scope, because the name used to over-promise: this constrains the *untouched*
    path only. A row that has been held is judged by the give-up counter, not by
    this window, and what stops a burst there is the one-per-lead-per-sweep cap
    — see `test_only_one_post_visit_message_reaches_a_lead_per_sweep`.
    """
    from app.services.followups import _POST_VISIT_OFFSETS, _SEND_STALE_AFTER

    offsets = sorted(_POST_VISIT_OFFSETS.values())
    gaps = [b - a for a, b in zip(offsets, offsets[1:], strict=False)]
    assert gaps, "there should be more than one post-visit message"
    assert min(gaps) > _SEND_STALE_AFTER, (
        f"two of these can be overdue together: smallest gap {min(gaps)} is not "
        f"wider than the {_SEND_STALE_AFTER} window that decides sendability"
    )


@pytest.mark.asyncio
async def test_no_amount_of_holding_makes_a_row_look_stale() -> None:
    """The invariant six rounds of patches were working around.

    `scheduled_for` used to mean two things — when the message was for, and when
    to look again — and the hold overwrote the first with the second. Every
    staleness rule after that needed a slack term guessed from constants to
    compensate, and each guess was wrong for some shape of data: sized for one
    visit, it cancelled the "how did it go?" message for a lead with three
    visits on the same day.

    With the deferral in its own column the property is structural: hold a row
    as many times as you like and the date it is judged by does not move.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # No inbound: no consent, so every sweep takes the hold path.
                lead_id, _ = await _lead_with_thread(db, "+13035557027", with_inbound=False)
                fu = FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.POST_VISIT_24H,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                )
                db.add(fu)
                await db.commit()
                fu_id = fu.id
                originally_for = fu.scheduled_for

            for day in range(1, 11):
                async with get_session_factory()() as db:
                    await process_due_followups(
                        db, now=datetime.now(UTC) + timedelta(days=day)
                    )
                async with get_session_factory()() as db:
                    row = await db.get(FollowUp, fu_id)
                    assert row.status == FollowUpStatus.PENDING, (
                        f"day {day}: a held row became {row.status}"
                    )
                    assert row.scheduled_for == originally_for, (
                        f"day {day}: the date it is judged by moved to "
                        f"{row.scheduled_for}"
                    )
                    assert row.postponed_until is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_call_follow_up_from_four_months_ago_is_not_sent_now() -> None:
    """The staleness rule used to be gated on the visit-derived kinds only.

    The call nudge was added later and nobody re-checked the guard, so one
    scheduled before an outage went out on the first sweep back — asking
    whether anything had changed since a conversation four months old.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557028")
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        kind=FollowUpKind.CALL_FOLLOW_UP,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(days=119),
                    )
                )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:18])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert delivered == [], f"a four-month-old call nudge went out: {delivered}"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_cadence_survives_rows_created_out_of_order() -> None:
    """The tie-break is `id`, and `id` is only the cadence by convention.

    Once a lead's sequence has been held every row carries the same deferral, so
    the sort falls through to id — which matches the cadence solely because
    `enqueue_for_visit` iterates `_POST_VISIT_OFFSETS` in the order that dict
    literal happens to be written. Nothing enforced that, and reordering three
    lines is the kind of edit that passes review on sight.

    So the ordering is stated where it belongs: by the offset each message is
    for, not by the order its row was inserted.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557029")
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-order-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=2),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                # Inserted latest-cadence-first, and all on the identical
                # timestamp — which is what a common hold produces, and the only
                # situation where the tie-break decides anything. Computing the
                # time inside the loop gave each row its own microsecond and the
                # first sort key silently did the work.
                due = datetime.now(UTC) - timedelta(minutes=1)
                for kind in (
                    FollowUpKind.POST_VISIT_7D,
                    FollowUpKind.POST_VISIT_72H,
                    FollowUpKind.POST_VISIT_24H,
                ):
                    db.add(
                        FollowUp(
                            lead_id=lead_id,
                            visit_id=visit.id,
                            kind=kind,
                            status=FollowUpStatus.PENDING,
                            scheduled_for=due,
                        )
                    )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:60])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert len(delivered) == 1, delivered
            assert "how did the visit go" in delivered[0].lower(), (
                f"insertion order decided the cadence, not the cadence: {delivered[0]!r}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_later_message_waits_for_the_earlier_one_about_the_same_visit() -> None:
    """The cadence stated as an invariant, not as a sort key.

    Ordering the batch could not express it: the due date sorts ahead of the
    cadence rank and the dates never tie, because a hold stamps "tomorrow plus
    the tick lag" on an already-due row while its sibling keeps its exact time.
    So the rank was never reached and the client was asked "just checking in on
    the property you saw" before "how did the visit go?".

    Here the 24h message is held for want of consent and the 72h one is due and
    sendable. Nothing may go out until the first one is settled.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557030")
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-cadence-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=4),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                # The 24h row deferred to tomorrow-ish; the 72h row plainly due.
                first = FollowUp(
                    lead_id=lead_id,
                    visit_id=visit.id,
                    kind=FollowUpKind.POST_VISIT_24H,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(days=3),
                )
                first.postponed_until = datetime.now(UTC) + timedelta(hours=20)
                db.add(first)
                db.add(
                    FollowUp(
                        # 7D, not 72H. `_lead_with_thread` seeds an inbound
                        # dated now, and the re-engagement rule
                        # (`followups.py:475`) applies to 72H alone — so with
                        # 72H this row was SKIPPED a hundred lines before the
                        # cadence invariant was reached, and the assertion
                        # below held with the invariant deleted entirely.
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=FollowUpKind.POST_VISIT_7D,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:60])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert delivered == [], (
                f"the later message overtook the one still owed: {delivered}"
            )

            # An empty `delivered` is what EVERY skip rule in the module
            # produces, which is why this assertion alone stayed green with the
            # invariant deleted outright. The invariant leaves a signature no
            # other rule leaves: the row is still PENDING — it is owed, not
            # refused — and carries a stamp to look again tomorrow.
            async with get_session_factory()() as db:
                held = (
                    await db.execute(
                        select(FollowUp).where(
                            FollowUp.lead_id == lead_id,
                            FollowUp.kind == FollowUpKind.POST_VISIT_7D,
                        )
                    )
                ).scalar_one()
                assert held.status is FollowUpStatus.PENDING, (
                    f"the later message was settled as {held.status}, so some "
                    "other rule handled it and this test is not watching the "
                    "cadence invariant at all"
                )
                assert held.postponed_until is not None, (
                    "held without a retry stamp: nothing will ever look at "
                    "this row again"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_sequence_that_gives_up_takes_the_rest_of_the_sequence_with_it() -> None:
    """One hold clock per sequence, not one per message.

    A consent hold retries daily and gives up after a fortnight. Dropping only
    the row that ran out let the cadence invariant release its sibling, which
    started a fresh fortnight, and the third a third: three serial clocks that
    outlast the staleness ceiling. The 7-day message was then cancelled unsent
    with holds to spare — and when consent did arrive late, the lead got a lone
    "how did the visit go?" a month after the visit, its two earlier messages
    never sent. The sequence has one fate, so it settles together.
    """
    from app.services.followups import _HOLD_GIVE_UP_AFTER_HOLDS

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # No inbound: nothing has given consent, so every channel is
                # refused and the hold path is the one under test.
                lead_id, _ = await _lead_with_thread(
                    db, "+13035557031", with_inbound=False
                )
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-giveup-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=15),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(days=14),
                        # One short of the limit: this sweep's hold is the last.
                        consent_holds=_HOLD_GIVE_UP_AFTER_HOLDS,
                        # A row with holds on it always carries the stamp the
                        # hold path wrote. Without one it is not a held row, it
                        # is an abandoned one, and the staleness rule cancels it
                        # long before the give-up path is reached.
                        postponed_until=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=FollowUpKind.POST_VISIT_72H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(days=12),
                        # Held behind the 24h row by the cadence invariant,
                        # which stamps the same way.
                        postponed_until=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                db.add(
                    FollowUp(
                        # Not due yet, so it is not even in the batch. It has to
                        # be reached through the database, not through the rows
                        # this sweep happens to be holding.
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=FollowUpKind.POST_VISIT_7D,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) + timedelta(days=2),
                    )
                )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:60])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    counts = await process_due_followups(db)

            assert delivered == [], (
                f"nothing has consent, so nothing may go out: {delivered}"
            )

            # Three rows were settled, so the sweep has to say three. The two
            # taken down with the give-up are settled outside the loop's own
            # accounting and then skipped by the guard at the top when it
            # reaches them, so they are invisible unless counted here — and a
            # consent-hold wave is exactly when this number gets reconciled.
            assert counts["skipped"] == 3, (
                f"settled three follow-ups and reported {counts['skipped']}: "
                f"{counts}"
            )

            async with get_session_factory()() as db:
                rows = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == lead_id)
                    )
                ).scalars().all()
                by_kind = {r.kind: r.status for r in rows}
                assert by_kind == {
                    FollowUpKind.POST_VISIT_24H: FollowUpStatus.SKIPPED,
                    FollowUpKind.POST_VISIT_72H: FollowUpStatus.SKIPPED,
                    FollowUpKind.POST_VISIT_7D: FollowUpStatus.SKIPPED,
                }, (
                    "the sequence outlived the hold clock that ran out: "
                    f"{by_kind}"
                )

                # The 72h row was settled by the row before it in this same
                # batch, and the loop reaches it afterwards through the identity
                # map. A settled message must not go on accumulating holds: a
                # SKIPPED row carrying a fresh "retry tomorrow" stamp and a
                # bumped counter is a record that contradicts itself, and the
                # operator console reads both of those columns.
                settled = next(
                    r for r in rows if r.kind is FollowUpKind.POST_VISIT_72H
                )
                assert settled.attempts == 0, (
                    "a message already given up on was put back through the "
                    f"send rules and took another hold: attempts={settled.attempts}"
                )
                assert settled.postponed_until < datetime.now(UTC), (
                    "a settled message was stamped to be retried tomorrow: "
                    f"{settled.postponed_until}"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_staleness_ceiling_is_derived_and_it_bites() -> None:
    """Past the ceiling a message is cancelled, not sent — and the ceiling is
    tied to the longest wait the module can legitimately produce.

    The relationship is the point. Written as a flat 30 days it silently
    cancelled work that the hold clock had not finished with; anyone raising
    `_HOLD_GIVE_UP_AFTER_HOLDS` past the literal would have reintroduced that,
    and nothing would have gone red.
    """
    from app.services.followups import (
        _HOLD_GIVE_UP_AFTER_HOLDS,
        _HOLD_RETRY_AFTER,
        _MAX_LATENESS,
    )

    # Pinned to the number we told customers, because everything else in this
    # test moves with the constant: the row below is seeded at
    # `now - _MAX_LATENESS - 1 day`, so it proves the clause FIRES and says
    # nothing about the clause being right. The ceiling went from 30 days to
    # 114 in the working tree and all 27 tests in this file stayed green.
    #
    # A customer-visible delay is a published promise. Changing it means
    # changing this number and the CHANGELOG in the same commit — which is the
    # whole point of it being here.
    assert _MAX_LATENESS == timedelta(days=30), (
        f"the staleness ceiling is {_MAX_LATENESS}, but CHANGELOG.md 0.51.0 "
        'tells customers "el plazo real no cambia: siguen siendo 30 días". '
        "One of the two is wrong. If the new value is deliberate, change this "
        "assertion and correct the changelog entry in the same commit"
    )

    assert _MAX_LATENESS > _HOLD_GIVE_UP_AFTER_HOLDS * _HOLD_RETRY_AFTER, (
        "the ceiling cancels sequences the hold clock is still working on: "
        f"ceiling {_MAX_LATENESS}, one clock "
        f"{_HOLD_GIVE_UP_AFTER_HOLDS * _HOLD_RETRY_AFTER}"
    )

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # With an inbound on file the consent gate permits the send, so
                # the only thing that can stop it is the ceiling.
                lead_id, _ = await _lead_with_thread(db, "+13035557032")
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - _MAX_LATENESS
                        - timedelta(days=1),
                        # Deferred, so the shorter staleness rule for rows
                        # nobody ever looked at does not apply here.
                        postponed_until=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:60])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert delivered == [], (
                f"a message this late is not worth sending: {delivered}"
            )

            async with get_session_factory()() as db:
                row = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == lead_id)
                    )
                ).scalar_one()
                assert row.status is FollowUpStatus.CANCELLED, row.status
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_hour_of_errors_does_not_spend_the_consent_fortnight() -> None:
    """An outage is not a lead declining to be written to.

    Choosing a channel raised for an hour. The sweep runs every five minutes, so
    that is thirteen passes. The error handler used to spend `attempts` — which
    was also the consent counter — and write no `postponed_until`, so the row
    fell due again on the very next pass. Thirteen sweeps put it two short of
    the fortnight; two ordinary passes later the consent give-up fired, and
    since v0.51.0 it takes the rest of the sequence with it.

    A lead who viewed a property on the 3rd then received none of the three
    post-visit messages, and the sequence was dead on the 5th, with the other
    two rows never having been held at all.
    """
    from app.services.followups import _HOLD_GIVE_UP_AFTER_HOLDS

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(db, "+13035557033")
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-blip-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=2),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                # 24h and 7d only. `_lead_with_thread` seeds an inbound dated
                # now and the re-engagement rule fires on 72H alone, which
                # would settle that row for an unrelated reason and hide what
                # this test is watching.
                for kind, age in (
                    (FollowUpKind.POST_VISIT_24H, timedelta(days=1)),
                    (FollowUpKind.POST_VISIT_7D, timedelta(0)),
                ):
                    db.add(
                        FollowUp(
                            lead_id=lead_id,
                            visit_id=visit.id,
                            kind=kind,
                            status=FollowUpStatus.PENDING,
                            scheduled_for=datetime.now(UTC) - age,
                        )
                    )
                await db.commit()

            async def _raises(*a, **k):  # noqa: ANN002, ANN003, ANN202
                raise RuntimeError("channel selection is down")

            # Thirteen sweeps in one hour, which is what a five-minute worker
            # does while something is broken.
            for _ in range(13):
                async with get_session_factory()() as db:
                    with patch(
                        "app.services.followups.reachable_active_conversations",
                        _raises,
                    ):
                        await process_due_followups(db)

            async with get_session_factory()() as db:
                rows = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == lead_id)
                    )
                ).scalars().all()

            alive = [r for r in rows if r.status is FollowUpStatus.PENDING]
            assert len(alive) == 2, (
                "an hour of errors settled part of the sequence: "
                f"{[(r.kind.value, r.status.value) for r in rows]}"
            )
            assert all(r.consent_holds == 0 for r in rows), (
                "an outage was charged to the consent fortnight: "
                f"{[(r.kind.value, r.consent_holds) for r in rows]}"
            )
            # And the retry stamp is what stops the burn: without it the row is
            # due again on the next tick and the hour costs thirteen passes.
            assert all(r.postponed_until is not None for r in rows), (
                "a row that errored carries no retry stamp, so it falls due "
                "again immediately"
            )
            assert all(r.attempts <= _HOLD_GIVE_UP_AFTER_HOLDS for r in rows), (
                f"error tries ran past the consent budget: "
                f"{[(r.kind.value, r.attempts) for r in rows]}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_sweep_counts_each_follow_up_once() -> None:
    """Three follow-ups cannot produce four outcomes.

    The batch is ordered by `coalesce(postponed_until, scheduled_for)` first and
    cadence rank only as a tie-break, so a later-cadence row that was never
    postponed can sort ahead of the earlier row that was. It is then held by the
    cadence invariant — counted, and still PENDING — and counted a second time
    when the earlier row gives up and takes it down.

    The number is returned by the sweep and logged. It over-reported during
    precisely the consent-hold wave it was added to make honest.
    """
    from app.services.followups import _HOLD_GIVE_UP_AFTER_HOLDS

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, _ = await _lead_with_thread(
                    db, "+13035557034", with_inbound=False
                )
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-count-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=15),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                # The 24h row is one hold short of giving up and drifted, so its
                # `postponed_until` sorts it AFTER the 7d row, which never was
                # postponed and is due on its own `scheduled_for`.
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(days=14),
                        consent_holds=_HOLD_GIVE_UP_AFTER_HOLDS,
                        postponed_until=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                db.add(
                    FollowUp(
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=FollowUpKind.POST_VISIT_7D,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                    )
                )
                await db.commit()

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    counts = await process_due_followups(db)

            async with get_session_factory()() as db:
                rows = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == lead_id)
                    )
                ).scalars().all()

            reported = counts["sent"] + counts["skipped"] + counts["failed"]
            assert reported <= len(rows), (
                f"reported {reported} outcomes for {len(rows)} follow-ups: "
                f"{counts}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visitless_give_up_does_not_reach_the_rest_of_the_tenant() -> None:
    """`visit_id IS NULL` is not a visit.

    The sibling cancellation finds the rest of a sequence with
    `FollowUp.visit_id == fu.visit_id`. On a follow-up that has no visit that
    renders `visit_id IS NULL`, which matches every visit-less PENDING row in
    the organisation — across every lead. `CALL_FOLLOW_UP` rows are exactly
    that: one is created per logged call, for whoever the office rang.

    So one lead running out of consent grace would settle the call follow-ups of
    every other client on the books. The guard is a single `is not None`, and
    removing it left the whole suite green.
    """
    from app.services.followups import _HOLD_GIVE_UP_AFTER_HOLDS

    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                doomed_lead, _ = await _lead_with_thread(
                    db, "+13035557035", with_inbound=False
                )
                bystander, _ = await _lead_with_thread(
                    db, "+13035557036", with_inbound=False
                )
                # Out of grace, no visit: this one gives up on this sweep.
                db.add(
                    FollowUp(
                        lead_id=doomed_lead,
                        visit_id=None,
                        kind=FollowUpKind.CALL_FOLLOW_UP,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(days=14),
                        consent_holds=_HOLD_GIVE_UP_AFTER_HOLDS,
                        postponed_until=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                # Somebody else entirely, also without a visit.
                db.add(
                    FollowUp(
                        lead_id=bystander,
                        visit_id=None,
                        kind=FollowUpKind.CALL_FOLLOW_UP,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) + timedelta(days=3),
                    )
                )
                await db.commit()

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            async with get_session_factory()() as db:
                others = (
                    await db.execute(
                        select(FollowUp).where(FollowUp.lead_id == bystander)
                    )
                ).scalars().all()

            assert [r.status for r in others] == [FollowUpStatus.PENDING], (
                "another client's call follow-up was settled by a give-up on a "
                f"lead they have nothing to do with: {[r.status for r in others]}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_cadence_invariant_does_not_treat_no_visit_as_one_visit() -> None:
    """The invariant's own copy of the same guard.

    It holds a later-cadence message while an earlier one *about the same
    visit* is still owed. Without the `visit_id is not None` check, a row with
    no visit compares `visit_id IS NULL` and is held behind an unrelated
    client's visit-less follow-up — silently, for ever, since that other row
    has no reason to move.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                mine, _ = await _lead_with_thread(db, "+13035557037")
                stranger, _ = await _lead_with_thread(db, "+13035557038")
                db.add(
                    FollowUp(
                        lead_id=mine,
                        visit_id=None,
                        kind=FollowUpKind.POST_VISIT_7D,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                    )
                )
                # Earlier in the cadence, no visit, belongs to somebody else.
                db.add(
                    FollowUp(
                        lead_id=stranger,
                        visit_id=None,
                        kind=FollowUpKind.POST_VISIT_24H,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) + timedelta(days=5),
                    )
                )
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:40])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert len(delivered) == 1, (
                "a due message was held behind a stranger's follow-up that "
                f"shares nothing but having no visit: {delivered}"
            )
    finally:
        await _cleanup()


def test_the_staleness_ceiling_is_written_as_a_formula() -> None:
    """Not merely equal to the right number today.

    The literal `timedelta(days=30)` satisfies every numeric assertion about
    the ceiling — it is identical to 14 + 16 — so the property the derivation
    exists for went unchecked: that raising the hold clock MOVES the ceiling.
    Only the source can answer that, and somebody who bumps the holds should
    get a failure pointing at the formula rather than one telling them to edit
    a literal.
    """
    tree = ast.parse(
        Path(app.services.followups.__file__).read_text(encoding="utf-8")
    )
    ceiling = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_MAX_LATENESS"
            for t in node.targets
        )
    )
    referenced = {
        n.id for n in ast.walk(ceiling.value) if isinstance(n, ast.Name)
    }
    assert "_HOLD_GIVE_UP_AFTER_HOLDS" in referenced, (
        "the ceiling no longer mentions the hold clock it has to clear, so "
        f"raising the clock leaves it behind: {sorted(referenced)}"
    )


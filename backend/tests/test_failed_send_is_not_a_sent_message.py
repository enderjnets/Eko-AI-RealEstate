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
                held.attempts = 3
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
                assert row.attempts == 4, "it should have been held once more"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_long_outage_does_not_release_a_held_sequence_as_a_burst() -> None:
    """The other side of the coin from the previous test, and the trade I got wrong.

    Exempting every touched row from the staleness rule protected held
    sequences from being cancelled — and turned a long outage into three
    messages arriving together, weeks after the visit they are about. A counter
    says whether a row was touched, never how long ago, so lateness is bounded
    from the visit the message is for.
    """
    await _agency()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead_id, conv_id = await _lead_with_thread(db, "+13035557025")
                visit = Visit(
                    lead_id=lead_id,
                    calendar_provider="manual",
                    external_booking_id="manual-burst-1",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=datetime.now(UTC) - timedelta(days=38),
                    duration_minutes=30,
                    timezone="UTC",
                )
                db.add(visit)
                await db.flush()
                for kind, attempts in (
                    (FollowUpKind.POST_VISIT_24H, 3),
                    (FollowUpKind.POST_VISIT_72H, 2),
                    (FollowUpKind.POST_VISIT_7D, 1),
                ):
                    fu = FollowUp(
                        lead_id=lead_id,
                        visit_id=visit.id,
                        kind=kind,
                        status=FollowUpStatus.PENDING,
                        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
                    )
                    fu.attempts = attempts
                    db.add(fu)
                await db.commit()

            delivered: list[str] = []

            async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
                delivered.append(text[:18])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert delivered == [], (
                f"a 38-day-old sequence went out anyway: {delivered}"
            )
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
                delivered.append(text[:18])
                return "sm.x", None

            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

            assert len(delivered) == 1, (
                f"the lead received {len(delivered)} messages in one sweep: {delivered}"
            )
    finally:
        await _cleanup()

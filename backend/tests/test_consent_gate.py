"""TCPA: who may be texted automatically, and through which conversation.

Two defects live here and they are related. The consent columns would be inert
decoration if nothing consulted them — the dead-field pattern this codebase has
now paid for four times. And the follow-up worker picked whichever conversation
was newest, which for a lead who arrived through the public form is the `web`
one, a thread nothing can be delivered to.

The second bug hides the first: while every web lead's follow-up failed on
dispatch, no automated text was going out, so an absent consent check looked
harmless. Fixing the channel selection is what makes the gate load-bearing, and
that is why both are tested in one file.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.conversation import Conversation, ConversationStatus
from app.models.follow_up import FollowUp, FollowUpKind, FollowUpStatus
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.capture import may_send_automated
from app.services.conversation import _latest_active_conversation
from app.services.followups import process_due_followups

WEB = "web"
MARK = "+19995551"  # every phone this file creates starts here
ADDRESS_LEAD = "gate-email@capture.test"


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM leads WHERE phone LIKE :m OR phone = :a"),
            {"m": f"{MARK}%", "a": ADDRESS_LEAD},
        )
        await db.commit()


async def _lead_with(
    db: AsyncSession,
    *,
    suffix: str,
    consent: bool = False,
    channels: tuple[str, ...] = (WEB,),
    inbound_on: tuple[str, ...] = (WEB,),
) -> tuple[Lead, dict[str, Conversation]]:
    """A lead plus one conversation per channel, with inbound where asked.

    `channels` is in CHRONOLOGICAL order — the last one is the most recently
    active, and therefore the one an unfiltered auto-pick would return. Getting
    this backwards is how a test about channel selection ends up selecting the
    right channel for the wrong reason.
    """
    lead = Lead(
        phone=f"{MARK}{suffix}",
        name="Gate Test",
        consent_at=datetime.now(UTC) if consent else None,
        consent_text="I agree to receive texts." if consent else None,
    )
    db.add(lead)
    await db.flush()

    convs: dict[str, Conversation] = {}
    for offset, channel in enumerate(channels):
        conv = Conversation(
            lead_id=lead.id,
            channel=channel,
            status=ConversationStatus.ACTIVE,
            # Newest last, so the `web` thread is the most recent one
            # deliberately rather than by accident of insertion order.
            last_at=datetime.now(UTC) - timedelta(minutes=len(channels) - offset),
        )
        db.add(conv)
        await db.flush()
        convs[channel] = conv
        if channel in inbound_on:
            db.add(
                Message(
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content="hello",
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
    await db.commit()
    return lead, convs


# ── The gate ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_consent_and_never_texted_us_blocks_sms() -> None:
    # The case that matters: they filled in the form without ticking the box,
    # an agent sent one manual SMS — which is what created the SMS thread — and
    # from then on the worker has a perfectly sendable channel and no
    # permission to use it. Nothing else in the system would object.
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="01", channels=(WEB, "sms"), inbound_on=(WEB,)
            )
            assert await may_send_automated(lead, "sms", db) is False
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_written_consent_opens_the_gate() -> None:
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="02", consent=True, channels=(WEB, "sms"), inbound_on=(WEB,)
            )
            assert await may_send_automated(lead, "sms", db) is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_who_texted_us_first_needs_no_checkbox() -> None:
    # Consumer-initiated contact on that channel is its own basis. Every lead
    # who ever texted this system keeps behaving exactly as before.
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="03", channels=("sms",), inbound_on=("sms",)
            )
            assert await may_send_automated(lead, "sms", db) is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_consent_is_per_channel_not_global() -> None:
    # Having written to us on WhatsApp is not permission to start texting.
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="04", channels=("whatsapp", "sms"), inbound_on=("whatsapp",)
            )
            assert await may_send_automated(lead, "whatsapp", db) is True
            assert await may_send_automated(lead, "sms", db) is False
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_email_is_not_gated() -> None:
    # CAN-SPAM asks for a working unsubscribe, not prior consent. Gating email
    # here would suppress legitimate mail and protect nobody.
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="05", channels=(WEB,), inbound_on=(WEB,)
            )
            assert await may_send_automated(lead, "email", db) is True
    finally:
        await _cleanup()


# ── Channel selection ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_pick_skips_a_channel_nothing_can_be_sent_through() -> None:
    try:
        async with get_session_factory()() as db:
            lead, convs = await _lead_with(
                db, suffix="06", channels=("sms", WEB), inbound_on=(WEB,)
            )
            # `web` is the newest, so the unfiltered pick returns it.
            unfiltered = await _latest_active_conversation(lead.id, db)
            assert unfiltered is not None
            assert unfiltered.channel == WEB
            # The filtered pick — what both senders now use — returns the SMS one.
            picked = await _latest_active_conversation(
                lead.id, db, identifier=lead.phone
            )
            assert picked is not None
            assert picked.channel == "sms"
            assert picked.id == convs["sms"].id
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_web_only_lead_has_nothing_to_send_through() -> None:
    # Not an error and not a crash: there is genuinely no way to reach this
    # person automatically until somebody replies to them by email or SMS.
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="07", channels=(WEB,), inbound_on=(WEB,)
            )
            picked = await _latest_active_conversation(
                lead.id, db, identifier=lead.phone
            )
            assert picked is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_email_lead_never_gets_handed_an_sms_thread() -> None:
    # The inverse guard: a lead identified by an address cannot be texted,
    # whatever conversations happen to exist on the record.
    try:
        async with get_session_factory()() as db:
            lead = Lead(phone=ADDRESS_LEAD, email=ADDRESS_LEAD)
            db.add(lead)
            await db.flush()
            for channel in ("sms", "email"):
                db.add(
                    Conversation(
                        lead_id=lead.id,
                        channel=channel,
                        status=ConversationStatus.ACTIVE,
                        last_at=datetime.now(UTC),
                    )
                )
            await db.commit()
            picked = await _latest_active_conversation(
                lead.id, db, identifier=lead.phone
            )
            assert picked is not None
            assert picked.channel == "email"
    finally:
        await _cleanup()


# ── The worker actually consults the gate ────────────────────────────────
#
# Everything above proves `may_send_automated` answers correctly. All of it
# would still pass if nothing ever called it — which is exactly how a consent
# column becomes decoration. These two drive the real worker.


async def _due_followup(lead: Lead, db: AsyncSession) -> int:
    fu = FollowUp(
        lead_id=lead.id,
        visit_id=None,
        kind=FollowUpKind.REMINDER_24H,
        status=FollowUpStatus.PENDING,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
    )
    db.add(fu)
    await db.commit()
    return fu.id


async def _outbound_channels(lead_id: int, db: AsyncSession) -> list[str]:
    rows = await db.execute(
        text(
            "SELECT c.channel FROM messages m "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE c.lead_id = :lead AND m.direction = 'outbound'"
        ),
        {"lead": lead_id},
    )
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_the_worker_holds_a_followup_with_no_consent() -> None:
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="09", channels=("sms", WEB), inbound_on=(WEB,)
            )
            await _due_followup(lead, db)

            result = await process_due_followups(db)

            assert result["sent"] == 0
            assert result["skipped"] >= 1
            assert await _outbound_channels(lead.id, db) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_worker_sends_once_consent_is_on_record() -> None:
    try:
        async with get_session_factory()() as db:
            lead, _ = await _lead_with(
                db, suffix="10", consent=True, channels=("sms", WEB), inbound_on=(WEB,)
            )
            await _due_followup(lead, db)

            result = await process_due_followups(db)

            assert result["sent"] == 1
            # And it went out on SMS, not on the `web` thread that was newer.
            assert await _outbound_channels(lead.id, db) == ["sms"]
    finally:
        await _cleanup()

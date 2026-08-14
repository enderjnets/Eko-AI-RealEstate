"""The preferred-channel rule, which is the one that can do damage.

A stated preference and a recorded consent are different things, and the whole
TCPA exposure of this feature is in conflating them. So these tests are about
what the preference must NOT do: it must not make a message sendable that was
not sendable before, and choosing "call me" must never produce an automated
message, because there is no voice sender and an automated call to a mobile is
the thing the statute is about.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Conversation,
    ConversationStatus,
    FollowUp,
    FollowUpKind,
    FollowUpStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.models.lead import LeadStatus, PreferredChannel
from app.services.followups import process_due_followups


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these tests need live Postgres")
    return url


def _session(url: str):
    engine = create_async_engine(url, echo=False, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _seed(
    url: str,
    *,
    channels: list[str],
    inbound_on: list[str],
    preferred: PreferredChannel | None,
    consent: bool = False,
    due_days_ago: int = 1,
) -> int:
    """A lead with the given conversations, a due call-follow-up, and nothing
    else that could decide the outcome."""
    engine, Session = _session(url)
    try:
        async with Session() as s:
            sfx = uuid.uuid4().hex[:8].upper()
            lead = Lead(
                phone=f"+1303PREF{sfx}"[:20],
                name="Pref Tester",
                email=f"pref-{sfx.lower()}@example.com",
                status=LeadStatus.QUALIFIED,
                preferred_channel=preferred,
            )
            if consent:
                lead.consent_at = datetime.now(UTC) - timedelta(days=10)
                lead.consent_text = "seeded for test"
            s.add(lead)
            await s.flush()

            for channel in channels:
                conv = Conversation(
                    lead_id=lead.id, channel=channel, status=ConversationStatus.ACTIVE
                )
                s.add(conv)
                await s.flush()
                if channel in inbound_on:
                    s.add(
                        Message(
                            conversation_id=conv.id,
                            direction=MessageDirection.INBOUND,
                            sender=MessageSender.LEAD,
                            content="hello",
                            external_id=f"in-{channel}-{sfx}",
                            delivery_status=MessageStatus.DELIVERED,
                        )
                    )

            s.add(
                FollowUp(
                    lead_id=lead.id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(days=due_days_ago),
                )
            )
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _cleanup(url: str, *lead_ids: int) -> None:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            for lead_id in lead_ids:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
            await s.commit()
    finally:
        await engine.dispose()


async def _rows(url: str, lead_id: int) -> list[FollowUp]:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            return list(
                (
                    await s.execute(select(FollowUp).where(FollowUp.lead_id == lead_id))
                ).scalars().all()
            )
    finally:
        await engine.dispose()


async def _sent_channels(url: str, lead_id: int) -> list[str]:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            rows = (
                await s.execute(
                    select(Conversation.channel)
                    .join(Message, Message.conversation_id == Conversation.id)
                    .where(
                        Conversation.lead_id == lead_id,
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                )
            ).scalars().all()
            return list(rows)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_preferred_channel_goes_first(database_url: str) -> None:
    """Both threads are reachable and permitted; the preference picks one."""
    lead_id = await _seed(
        database_url,
        channels=["whatsapp", "sms"],
        inbound_on=["whatsapp", "sms"],
        preferred=PreferredChannel.SMS,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            await process_due_followups(s)
        assert await _sent_channels(database_url, lead_id) == ["sms"]
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_preferring_email_never_sends_automatically(database_url: str) -> None:
    """Outbound email carries no unsubscribe header and no physical address,
    and optout.py does not recognise the channel — automated commercial email
    without a working opt-out is a CAN-SPAM violation. So the row is a task."""
    lead_id = await _seed(
        database_url,
        channels=["sms"],
        inbound_on=["sms"],
        preferred=PreferredChannel.EMAIL,
        consent=True,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            await process_due_followups(s)
        assert await _sent_channels(database_url, lead_id) == []
        rows = await _rows(database_url, lead_id)
        assert rows[0].status == FollowUpStatus.PENDING
        assert rows[0].attempts == 0
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_preference_does_not_make_an_ungated_channel_sendable(
    database_url: str,
) -> None:
    """The lead asked for SMS but never wrote to us and never consented. The
    hold must stand: a preference is not permission."""
    lead_id = await _seed(
        database_url,
        channels=["sms"],
        inbound_on=[],
        preferred=PreferredChannel.SMS,
        consent=False,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            await process_due_followups(s)
        assert await _sent_channels(database_url, lead_id) == []
        rows = await _rows(database_url, lead_id)
        assert rows[0].status == FollowUpStatus.PENDING, "held, not sent, not skipped"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_preference_still_reaches_someone_on_their_other_channel(
    database_url: str,
) -> None:
    """Reorders, never filters. Dropping the rest would mean a lead who said
    "text me" but whose consent is on WhatsApp is never contacted again."""
    lead_id = await _seed(
        database_url,
        channels=["sms", "whatsapp"],
        inbound_on=["whatsapp"],
        preferred=PreferredChannel.SMS,
        consent=False,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            await process_due_followups(s)
        # SMS is preferred but ungated-and-unpermitted; WhatsApp carries it.
        assert await _sent_channels(database_url, lead_id) == ["whatsapp"]
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_preferring_a_call_never_sends_anything(database_url: str) -> None:
    """There is no voice sender behind this choice, and an automated call to a
    mobile is exactly what TCPA punishes. The row stays a task."""
    lead_id = await _seed(
        database_url,
        channels=["sms", "email"],
        inbound_on=["sms"],
        preferred=PreferredChannel.CALL,
        consent=True,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            await process_due_followups(s)
        assert await _sent_channels(database_url, lead_id) == []
        rows = await _rows(database_url, lead_id)
        assert rows[0].status == FollowUpStatus.PENDING
        assert rows[0].attempts == 0, "a task must not burn the give-up counter"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_call_tasks_do_not_starve_the_sendable_ones(database_url: str) -> None:
    """A permanently-pending row that is always the oldest would sit at the
    head of every limited batch for ever. Excluded in SQL for that reason."""
    call_lead = await _seed(
        database_url,
        channels=["sms"],
        inbound_on=["sms"],
        preferred=PreferredChannel.CALL,
        due_days_ago=30,
    )
    sms_lead = await _seed(
        database_url,
        channels=["sms"],
        inbound_on=["sms"],
        preferred=PreferredChannel.SMS,
        due_days_ago=1,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            # limit=1: with the call-task in the batch it would take the only
            # slot every sweep, because it is thirty days older.
            result = await process_due_followups(s, limit=1)
        assert result["sent"] == 1
        assert await _sent_channels(database_url, sms_lead) == ["sms"]
        assert await _sent_channels(database_url, call_lead) == []
    finally:
        await engine.dispose()
        await _cleanup(database_url, call_lead, sms_lead)

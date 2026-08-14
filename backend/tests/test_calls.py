"""Tests for the call console service.

The console's whole claim is that one tap records what was learned *and* fires
the next step. So what is worth testing is not that a row was written — it is
that each outcome causes exactly its own action and none of the others, and
that the ones which mean "stop" really do stop everything already in flight.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    CallLog,
    CallOutcome,
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
from app.models.lead import LeadIntent, LeadStatus, PreferredChannel
from app.services.calls import CallUpdates, register_call


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — call console tests need live Postgres")
    return url


def _session(url: str):
    engine = create_async_engine(url, echo=False, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _make_lead(url: str, **kw) -> int:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            sfx = uuid.uuid4().hex[:8].upper()
            lead = Lead(phone=f"+1303CALL{sfx}"[:20], name="Call Tester", **kw)
            s.add(lead)
            await s.flush()
            conv = Conversation(
                lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE
            )
            s.add(conv)
            await s.flush()
            s.add(
                Message(
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content="hi",
                    external_id=f"in-call-{sfx}",
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _cleanup(url: str, lead_id: int) -> None:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
            await s.commit()
    finally:
        await engine.dispose()


async def _pending(url: str, lead_id: int) -> list[FollowUp]:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            return list(
                (
                    await s.execute(
                        select(FollowUp).where(
                            FollowUp.lead_id == lead_id,
                            FollowUp.status == FollowUpStatus.PENDING,
                        )
                    )
                ).scalars().all()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_what_the_call_revealed_lands_on_the_lead(database_url: str) -> None:
    """The matcher and the scorer read the lead, not the call row. If the call
    does not update the lead, none of that machinery ever turns."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead,
                CallOutcome.WANTS_LISTINGS,
                s,
                logged_by="natalia@example.com",
                updates=CallUpdates(
                    intent=LeadIntent.BUY,
                    zone="Wash Park",
                    budget_min=Decimal("450000"),
                    budget_max=Decimal("650000"),
                    urgency="high",
                    preferred_channel=PreferredChannel.SMS,
                ),
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.intent == LeadIntent.BUY
            assert lead.zone == "Wash Park"
            assert lead.budget_max == Decimal("650000")
            assert lead.preferred_channel == PreferredChannel.SMS
            assert lead.status == LeadStatus.QUALIFIED
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_fields_not_discussed_are_left_alone(database_url: str) -> None:
    """`None` means "did not come up", never "erase it". A console that blanks
    a budget because the advisor did not retype it destroys the data it is
    supposed to be collecting."""
    lead_id = await _make_lead(
        database_url, zone="Cherry Creek", budget_max=Decimal("900000")
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead, CallOutcome.FOLLOW_UP, s, updates=CallUpdates(urgency="low")
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.zone == "Cherry Creek"
            assert lead.budget_max == Decimal("900000")
            assert lead.urgency == "low"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_follow_up_is_queued_only_when_one_was_asked_for(
    database_url: str,
) -> None:
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(lead, CallOutcome.FOLLOW_UP, s)
        assert result.follow_up is None
        assert await _pending(database_url, lead_id) == []

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(
                lead, CallOutcome.FOLLOW_UP, s, follow_up_in_days=3
            )
        assert result.follow_up is not None
        rows = await _pending(database_url, lead_id)
        assert len(rows) == 1
        assert rows[0].kind == FollowUpKind.CALL_FOLLOW_UP
        assert rows[0].call_log_id is not None
        due_in = rows[0].scheduled_for - datetime.now(UTC)
        assert timedelta(days=2, hours=23) < due_in < timedelta(days=3, hours=1)
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_do_not_contact_stops_everything_already_queued(
    database_url: str,
) -> None:
    """The complaint that follows a "stop calling me" is the nudge that goes
    out three days later because nobody cancelled it."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(lead, CallOutcome.FOLLOW_UP, s, follow_up_in_days=3)
        assert len(await _pending(database_url, lead_id)) == 1

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(lead, CallOutcome.DO_NOT_CONTACT, s)
        assert result.cancelled_follow_ups == 1
        assert await _pending(database_url, lead_id) == []

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            # The same field the STOP keyword sets, so every existing sender
            # already honours it.
            assert lead.opted_out_at is not None
            assert lead.status == LeadStatus.LOST
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_already_has_an_agent_pauses_rather_than_loses(
    database_url: str,
) -> None:
    """NAR Article 16 says stand down, not that the relationship is over."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(lead, CallOutcome.FOLLOW_UP, s, follow_up_in_days=7)
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(lead, CallOutcome.HAS_AGENT, s)
        assert result.cancelled_follow_ups == 1
        assert result.follow_up is None
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.status == LeadStatus.PAUSED
            assert lead.opted_out_at is None, "standing down is not an opt-out"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_stand_down_outcome_never_queues_a_follow_up(
    database_url: str,
) -> None:
    """Even if the caller passes a follow-up interval — the UI should not, but
    the rule belongs in the service, where it cannot be forgotten."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(
                lead, CallOutcome.DO_NOT_CONTACT, s, follow_up_in_days=3
            )
        assert result.follow_up is None
        assert await _pending(database_url, lead_id) == []
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_verbal_consent_is_recorded_once_and_says_where_it_came_from(
    database_url: str,
) -> None:
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead,
                CallOutcome.WANTS_LISTINGS,
                s,
                logged_by="robbie@example.com",
                asked_for_texts=True,
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            first_at = lead.consent_at
            assert first_at is not None
            assert "robbie@example.com" in (lead.consent_text or "")
            assert "call" in (lead.consent_text or "").lower()

        # A second call must not overwrite the record of the first.
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead,
                CallOutcome.FOLLOW_UP,
                s,
                logged_by="someone-else@example.com",
                asked_for_texts=True,
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.consent_at == first_at
            assert "someone-else" not in (lead.consent_text or "")
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_preferring_a_channel_does_not_create_consent(
    database_url: str,
) -> None:
    """"Text me rather than email me" is a preference about how. It is not
    permission to start, and conflating the two is the whole TCPA exposure."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead,
                CallOutcome.FOLLOW_UP,
                s,
                updates=CallUpdates(preferred_channel=PreferredChannel.SMS),
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.preferred_channel == PreferredChannel.SMS
            assert lead.consent_at is None
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_logging_a_new_call_closes_out_the_task_it_satisfied(
    database_url: str,
) -> None:
    """A call-task the advisor has just done must leave the list, or the
    console shows them work that is already finished."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(lead, CallOutcome.NO_ANSWER, s, follow_up_in_days=1)
        assert len(await _pending(database_url, lead_id)) == 1

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(
                lead, CallOutcome.WANTS_LISTINGS, s, follow_up_in_days=2
            )
        rows = await _pending(database_url, lead_id)
        assert result.cancelled_follow_ups == 1, "the earlier task stayed open"
        assert len(rows) == 1, "exactly the new one is pending"
        assert rows[0].call_log_id == result.call.id
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_two_calls_are_two_rows_and_two_distinct_follow_ups(
    database_url: str,
) -> None:
    """The UNIQUE is on (call_log_id, kind), so it must not collapse separate
    calls — only a double-submit of the same one."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        for _ in range(2):
            async with Session() as s:
                lead = await s.get(Lead, lead_id)
                await register_call(lead, CallOutcome.NO_ANSWER, s, follow_up_in_days=1)
        async with Session() as s:
            calls = (
                await s.execute(select(CallLog).where(CallLog.lead_id == lead_id))
            ).unique().scalars().all()
        assert len(calls) == 2
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_lead_with_no_name_or_email_does_not_break_the_call(
    database_url: str,
) -> None:
    """The commonest lead in the database is a bare phone number."""
    engine, Session = _session(database_url)
    lead_id = None
    try:
        async with Session() as s:
            sfx = uuid.uuid4().hex[:6].upper()
            bare = Lead(phone=f"+1303BARE{sfx}"[:20], status=LeadStatus.NEW)
            s.add(bare)
            await s.commit()
            lead_id = bare.id
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(
                lead, CallOutcome.WANTS_LISTINGS, s, asked_for_texts=True
            )
        assert result.call.id is not None
        assert isinstance(result.score, int)
    finally:
        await engine.dispose()
        if lead_id:
            await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_blank_string_is_silence_not_an_erasure(database_url: str) -> None:
    """An untouched input that posts "" must read as "did not come up".

    Found by probing the API rather than the service: the console trims before
    sending, so the rule looked kept while it lived only in the client. A blank
    zone wiped the lead's zone, and the first sign would have been the matcher
    quietly finding nothing for them.
    """
    lead_id = await _make_lead(
        database_url, zone="Cherry Creek", urgency="high", property_type="condo"
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead,
                CallOutcome.FOLLOW_UP,
                s,
                updates=CallUpdates(zone="", urgency="   ", property_type="\t"),
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.zone == "Cherry Creek"
            assert lead.urgency == "high"
            assert lead.property_type == "condo"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_value_with_stray_whitespace_is_stored_trimmed(
    database_url: str,
) -> None:
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead, CallOutcome.FOLLOW_UP, s, updates=CallUpdates(zone="  Berkeley  ")
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.zone == "Berkeley"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_consent_is_refused_for_someone_who_already_opted_out(
    database_url: str,
) -> None:
    """An advisor ticking a box cannot give consent on behalf of someone who
    told us to stop.

    Two consequences if it could: the fabricated record goes live the moment
    they text START, and because consent is never overwritten it permanently
    blocks the real written consent from ever being recorded.
    """
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            lead.opted_out_at = datetime.now(UTC) - timedelta(days=2)
            await s.commit()

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead, CallOutcome.FOLLOW_UP, s, asked_for_texts=True, logged_by="a@b.c"
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.consent_at is None, "manufactured consent for an opted-out lead"
            assert lead.consent_text is None
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_do_not_contact_and_asked_for_texts_in_one_submit_records_no_consent(
    database_url: str,
) -> None:
    """The console should not offer both at once, but the rule belongs where it
    cannot be reached around."""
    lead_id = await _make_lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(
                lead, CallOutcome.DO_NOT_CONTACT, s, asked_for_texts=True
            )
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.opted_out_at is not None
            assert lead.consent_at is None
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_call_closes_a_stale_task_the_sweep_can_never_reach(
    database_url: str,
) -> None:
    """A lead who asked to be phoned is excluded from the follow-up sweep, so
    nothing in that worker will ever close their overdue rows. Before this the
    task showed on the console for ever, however many calls were logged."""
    lead_id = await _make_lead(database_url, preferred_channel=PreferredChannel.CALL)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.REMINDER_24H,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(days=30),
                )
            )
            await s.commit()
        assert len(await _pending(database_url, lead_id)) == 1

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            result = await register_call(lead, CallOutcome.NO_ANSWER, s)
        assert result.cancelled_follow_ups == 1
        assert await _pending(database_url, lead_id) == []
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_future_follow_up_is_left_alone_by_an_unrelated_call(
    database_url: str,
) -> None:
    """Only what is due counts as a job this call has done. Cancelling a
    reminder for a viewing next week because somebody rang today would delete
    the arrangement rather than fulfil it."""
    lead_id = await _make_lead(database_url, preferred_channel=PreferredChannel.CALL)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.REMINDER_24H,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) + timedelta(days=6),
                )
            )
            await s.commit()

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            await register_call(lead, CallOutcome.NO_ANSWER, s)
        assert len(await _pending(database_url, lead_id)) == 1
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)

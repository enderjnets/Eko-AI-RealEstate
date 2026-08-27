"""Tests for the nurture follow-ups service (Phase 10)."""
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
    Visit,
    VisitStatus,
)
from app.services.followups import enqueue_for_visit, process_due_followups


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — follow-up tests need live Postgres")
    return url


def _session(url: str):
    engine = create_async_engine(url, echo=False, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _make_lead_visit(url: str, *, scheduled_at: datetime, human_takeover: bool = False,
                           visit_status: VisitStatus = VisitStatus.SCHEDULED) -> tuple[int, int]:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            sfx = uuid.uuid4().hex[:8].upper()
            lead = Lead(phone=f"+1305FU{sfx}", name="Nurture Tester", human_takeover=human_takeover)
            s.add(lead)
            await s.flush()
            conv = Conversation(lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE)
            s.add(conv)
            await s.flush()
            # an inbound so the conversation is real
            s.add(Message(conversation_id=conv.id, direction=MessageDirection.INBOUND,
                          sender=MessageSender.LEAD, content="hi", external_id=f"in-{sfx}",
                          delivery_status=MessageStatus.DELIVERED))
            visit = Visit(lead_id=lead.id, calendar_provider="calcom",
                          external_booking_id=f"calcom-sim-fu-{sfx}", status=visit_status,
                          scheduled_at=scheduled_at, duration_minutes=30, timezone="UTC")
            s.add(visit)
            await s.commit()
            return lead.id, visit.id
    finally:
        await engine.dispose()


async def _delete_lead(url: str, lead_id: int) -> None:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            row = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_creates_sequence_and_is_idempotent(database_url: str) -> None:
    # Visit 2 days out → reminder (future) + 3 post-visit = 4 follow-ups.
    future = datetime.now(UTC) + timedelta(days=2)
    lead_id, visit_id = await _make_lead_visit(database_url, scheduled_at=future)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            visit = (await s.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
            created = await enqueue_for_visit(visit, s)
            assert created == 4
            again = await enqueue_for_visit(visit, s)
            assert again == 0  # idempotent
            kinds = set((await s.execute(
                select(FollowUp.kind).where(FollowUp.visit_id == visit_id)
            )).scalars().all())
            assert FollowUpKind.REMINDER_24H in kinds
            assert FollowUpKind.POST_VISIT_7D in kinds
    finally:
        await engine.dispose()
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_past_visit_skips_reminder(database_url: str) -> None:
    """A visit already in the past → no reminder, only the 3 post-visit ones."""
    past = datetime.now(UTC) - timedelta(days=1)
    lead_id, visit_id = await _make_lead_visit(database_url, scheduled_at=past)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            visit = (await s.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
            created = await enqueue_for_visit(visit, s)
            assert created == 3
    finally:
        await engine.dispose()
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_process_sends_due_followup(database_url: str) -> None:
    """A due post-visit follow-up (visit 2 days ago) gets sent (SIMULATED)."""
    # One day back, not two: the 24h message is then due right now. At two
    # days it is a full cadence gap overdue, and `enqueue_for_visit` stops
    # scheduling those — three post-visit messages arriving seconds apart is
    # what a back-dated visit used to produce.
    past = datetime.now(UTC) - timedelta(days=1)
    lead_id, visit_id = await _make_lead_visit(database_url, scheduled_at=past)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            visit = (await s.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
            await enqueue_for_visit(visit, s)
            result = await process_due_followups(s)
            assert result["sent"] >= 1
            sent = (await s.execute(
                select(FollowUp).where(FollowUp.visit_id == visit_id, FollowUp.status == FollowUpStatus.SENT)
            )).scalars().all()
            assert len(sent) >= 1
            assert all(f.sent_at is not None for f in sent)
    finally:
        await engine.dispose()
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_human_takeover_skips(database_url: str) -> None:
    # One day back, not two: the 24h message is then due right now. At two
    # days it is a full cadence gap overdue, and `enqueue_for_visit` stops
    # scheduling those — three post-visit messages arriving seconds apart is
    # what a back-dated visit used to produce.
    past = datetime.now(UTC) - timedelta(days=1)
    lead_id, visit_id = await _make_lead_visit(database_url, scheduled_at=past, human_takeover=True)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            visit = (await s.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
            await enqueue_for_visit(visit, s)
            result = await process_due_followups(s)
            assert result["sent"] == 0
            assert result["skipped"] >= 1
    finally:
        await engine.dispose()
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_cancelled_visit_not_enqueued(database_url: str) -> None:
    future = datetime.now(UTC) + timedelta(days=2)
    lead_id, visit_id = await _make_lead_visit(
        database_url, scheduled_at=future, visit_status=VisitStatus.CANCELLED
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            visit = (await s.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
            created = await enqueue_for_visit(visit, s)
            assert created == 0
    finally:
        await engine.dispose()
        await _delete_lead(database_url, lead_id)


@pytest.mark.asyncio
async def test_no_reminder_for_a_visit_already_completed(database_url: str) -> None:
    """"Your viewing is tomorrow" about a viewing they already attended.

    The dead-status guard listed CANCELLED and NO_SHOW but not COMPLETED, so a
    24h reminder still fired for a visit the realtor had already marked done.
    Post-visit follow-ups are the opposite case — COMPLETED is exactly when
    those should go — so the extra status applies to the pre-visit reminder
    only.
    """
    future = datetime.now(UTC) + timedelta(days=2)
    lead_id, visit_id = await _make_lead_visit(database_url, scheduled_at=future)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            await s.execute(
                text("UPDATE visits SET status = 'completed' WHERE id = :v"),
                {"v": visit_id},
            )
            await s.execute(
                text(
                    "DELETE FROM follow_ups WHERE visit_id = :v"
                ),
                {"v": visit_id},
            )
            await s.execute(
                text(
                    "INSERT INTO follow_ups (org_id, lead_id, visit_id, kind, "
                    "status, scheduled_for, attempts) VALUES "
                    "(1, :l, :v, 'reminder_24h', 'pending', :due, 0)"
                ),
                {"l": lead_id, "v": visit_id,
                 "due": datetime.now(UTC) - timedelta(minutes=5)},
            )
            await s.commit()

            result = await process_due_followups(s)
            assert result["sent"] == 0

            status = (
                await s.execute(
                    text(
                        "SELECT status FROM follow_ups WHERE visit_id = :v "
                        "AND kind = 'reminder_24h'"
                    ),
                    {"v": visit_id},
                )
            ).scalar_one()
            assert status == "cancelled"
    finally:
        await _delete_lead(database_url, lead_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_agency_name_reaches_the_lead_through_the_filter(
    database_url: str,
) -> None:
    """The hole the plan's own reasoning left open, closed with a real send.

    The plan excluded this lane because "these are OUR templates, fixed, so a
    build-time sweep of the templates is enough". The templates are ours.
    `{agency}` is not — it is `agent_settings.agency_name`, typed by the client
    and interpolated verbatim (`followups.py`, `template.format(agency=…)`).

    So the template sweep proved the template was clean and said nothing about
    the value poured into it. A brokerage that named itself "Perfect for
    Families Realty" sent that phrase to every lead on this lane, with
    `fair_housing_flags` reading NULL, which the watcher's predicate
    (`jsonb_array_length(...) > 0`) cannot see — no chip in the timeline, no
    alert, nothing. Meanwhile the release notes told that same realtor every
    answer we send is screened.

    Not a hypothetical name: the broker attribution this product reproduces
    verbatim by legal obligation is exactly where a phrase like that arrives.

    Record and warn, never block — the same policy as the reply lane. A nurture
    message that does not go out is a lead who hears nothing.
    """
    from unittest.mock import AsyncMock, patch

    from app.models.agent_settings import AgentSettings

    # CALL_FOLLOW_UP on purpose: it is one of only TWO templates that interpolate
    # `{agency}`, and interpolation is the whole point of this test. The
    # post-visit kinds do not, so enqueuing those would send a message with no
    # client-controlled text in it and pass while proving nothing.
    past = datetime.now(UTC) - timedelta(days=1)
    lead_id, visit_id = await _make_lead_visit(
        database_url, scheduled_at=past, visit_status=VisitStatus.COMPLETED
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            row = (await s.execute(select(AgentSettings))).scalars().first()
            before = row.agency_name if row else None
            if row is None:
                row = AgentSettings(agency_name="Perfect for Families Realty")
                s.add(row)
            else:
                row.agency_name = "Perfect for Families Realty"
            # Due yesterday, so the sweep picks it up on this tick.
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    visit_id=visit_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                )
            )
            await s.commit()

        try:
            with patch(
                "app.services.followups._dispatch_send",
                new=AsyncMock(return_value=("ext-fh-1", None)),
            ) as sent:
                async with Session() as s:
                    result = await process_due_followups(s)

            assert result["sent"] >= 1, result
            assert sent.await_count >= 1, "nothing was actually dispatched"

            async with Session() as s:
                msgs = (
                    await s.execute(
                        select(Message)
                        .join(Conversation, Message.conversation_id == Conversation.id)
                        .where(
                            Conversation.lead_id == lead_id,
                            Message.direction == MessageDirection.OUTBOUND,
                        )
                    )
                ).scalars().all()
                assert msgs, "the follow-up wrote no outbound message"
                carrying = [m for m in msgs if m.content and "Perfect for Families" in m.content]
                assert carrying, [m.content for m in msgs]
                for m in carrying:
                    assert m.fair_housing_flags, (
                        "the agency name reached the lead unscreened: "
                        f"{m.content!r} -> {m.fair_housing_flags!r}"
                    )
                    assert any(
                        f["category"] == "familial_status" for f in m.fair_housing_flags
                    ), m.fair_housing_flags
                    # And it still went out. Recording is not blocking.
                    assert m.delivery_status == MessageStatus.SENT
        finally:
            async with Session() as s:
                row = (await s.execute(select(AgentSettings))).scalars().first()
                if row is not None and before is not None:
                    row.agency_name = before
                    await s.commit()
    finally:
        await engine.dispose()
        await _delete_lead(database_url, lead_id)

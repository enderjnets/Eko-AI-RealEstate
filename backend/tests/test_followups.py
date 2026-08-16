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

"""The console API: logging a call, and the list of today.

The list matters because two of its three sections surface state that was
previously invisible — a follow-up nobody can send, and a follow-up being held
for want of consent. Both used to exist only as a log line, which is the same
as not existing.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
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


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — console API tests need live Postgres")
    return url


def _session(url: str):
    engine = create_async_engine(url, echo=False, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _lead(url: str, **kw) -> int:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            sfx = uuid.uuid4().hex[:8].upper()
            lead = Lead(phone=f"+1720CON{sfx}"[:20], name="Console Tester", **kw)
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
                    content="hello",
                    external_id=f"in-con-{sfx}",
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _cleanup(url: str, *ids: int) -> None:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            for i in ids:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": i})
            await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_logging_a_call_updates_the_lead_and_returns_the_new_score(
    database_url: str,
) -> None:
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={
                    "outcome": "wants_listings",
                    "intent": "buy",
                    "zone": "Berkeley",
                    "budget_max": 725000,
                    "preferred_channel": "sms",
                    "note": "Pre-approved, wants a yard.",
                    "follow_up_in_days": 3,
                },
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["call"]["outcome"] == "wants_listings"
        assert body["follow_up_scheduled_for"] is not None
        assert isinstance(body["score"], int)

        async with await _client() as c:
            r = await c.get(f"/api/v1/leads/{lead_id}/calls")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["note"] == "Pre-approved, wants a yard."
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_logging_a_call_for_a_missing_lead_is_404(database_url: str) -> None:
    async with await _client() as c:
        r = await c.post("/api/v1/leads/99999999/calls", json={"outcome": "no_answer"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_outcome_is_refused(database_url: str) -> None:
    """The outcome is the trigger. A typo must not become a silently
    unhandled branch."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls", json={"outcome": "maybe_later"}
            )
        assert r.status_code == 422
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_an_absurd_follow_up_interval_is_refused(database_url: str) -> None:
    """A fat-fingered interval should not park a lead past the point anyone
    would look for them."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "follow_up_in_days": 9000},
            )
        assert r.status_code == 422
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_today_lists_a_call_task_that_nothing_can_send(
    database_url: str,
) -> None:
    lead_id = await _lead(
        database_url, preferred_channel=PreferredChannel.CALL, status=LeadStatus.QUALIFIED
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                )
            )
            await s.commit()

        async with await _client() as c:
            r = await c.get("/api/v1/console/today")
        assert r.status_code == 200, r.text
        mine = [t for t in r.json()["tasks"] if t["lead"]["id"] == lead_id]
        assert len(mine) == 1
        assert mine[0]["channel"] == "call"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_today_shows_a_follow_up_held_for_want_of_consent(
    database_url: str,
) -> None:
    """Previously this existed only as a log line, so the office could not tell
    "we are nurturing them" from "we have been unable to say anything for a
    week"."""
    lead_id = await _lead(database_url, status=LeadStatus.QUALIFIED)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) + timedelta(hours=6),
                    attempts=3,
                )
            )
            await s.commit()

        async with await _client() as c:
            r = await c.get("/api/v1/console/today")
        mine = [h for h in r.json()["held"] if h["lead"]["id"] == lead_id]
        assert len(mine) == 1
        assert mine[0]["holds"] == 3
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_lead_who_opted_out_appears_nowhere_on_the_list(
    database_url: str,
) -> None:
    """The list is a list of things to do. Doing any of them to somebody who
    asked us to stop is the failure that costs $500 a message."""
    lead_id = await _lead(
        database_url,
        preferred_channel=PreferredChannel.CALL,
        status=LeadStatus.QUALIFIED,
        score=95,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            lead.opted_out_at = datetime.now(UTC)
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                    attempts=2,
                )
            )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        assert [t for t in body["tasks"] if t["lead"]["id"] == lead_id] == []
        assert [h for h in body["held"] if h["lead"]["id"] == lead_id] == []
        assert [x for x in body["untouched_hot"] if x["id"] == lead_id] == []
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_hot_lead_leaves_the_untouched_list_once_it_is_called(
    database_url: str,
) -> None:
    lead_id = await _lead(
        database_url,
        status=LeadStatus.QUALIFIED,
        score=88,
        last_message_at=datetime.now(UTC) - timedelta(days=30),
    )
    try:
        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        assert any(x["id"] == lead_id for x in body["untouched_hot"])

        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls", json={"outcome": "no_answer"}
            )
            assert r.status_code == 201, r.text
            body = (await c.get("/api/v1/console/today")).json()
        assert not any(x["id"] == lead_id for x in body["untouched_hot"]), (
            "a lead that was just called is not untouched"
        )
    finally:
        await _cleanup(database_url, lead_id)

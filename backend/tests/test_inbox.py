"""Inbox / communications buzón — GET /api/v1/inbox (+ count, mark handled).

Derives needs_response (last message inbound + not handled since), has_visit, and
priority ordering across leads with conversations.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models import (
    Conversation,
    ConversationStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
    Visit,
    VisitStatus,
)
from app.services.inbox import set_handled


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — inbox tests need live Postgres")
    return url


async def _http_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mk_lead(
    s, phone: str, *, channel: str, last_dir: MessageDirection,
    score: int = 0, created_at: datetime | None = None,
) -> int:
    """Lead + one conversation + a single message with the given direction/time."""
    created_at = created_at or datetime(2026, 5, 28, 10, 0, 0, tzinfo=UTC)
    lead = Lead(phone=phone, name=f"Inbox {phone[-4:]}", score=score)
    s.add(lead)
    await s.flush()
    conv = Conversation(lead_id=lead.id, channel=channel, status=ConversationStatus.ACTIVE,
                        last_at=created_at)
    s.add(conv)
    await s.flush()
    sender = MessageSender.LEAD if last_dir == MessageDirection.INBOUND else MessageSender.AGENT
    s.add(Message(
        conversation_id=conv.id, direction=last_dir, sender=sender,
        content=f"msg on {channel}", external_id=f"{channel}_{uuid.uuid4().hex[:10]}",
        delivery_status=MessageStatus.DELIVERED, created_at=created_at,
    ))
    return lead.id


async def _cleanup(database_url: str, *phones: str) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            for phone in phones:
                row = (await s.execute(select(Lead).where(Lead.phone == phone))).scalar_one_or_none()
                if row is not None:
                    await s.delete(row)
            await s.commit()
    finally:
        await engine.dispose()


def _find(items: list[dict], lead_id: int) -> dict | None:
    return next((it for it in items if it["lead_id"] == lead_id), None)


@pytest.mark.asyncio
async def test_pending_reflects_last_inbound(database_url: str) -> None:
    """Last message inbound → needs_response + last_channel; last outbound → not."""
    sfx = uuid.uuid4().hex[:6]
    p_in, p_out = f"+34666IB{sfx}A", f"+34666IB{sfx}B"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            id_in = await _mk_lead(s, p_in, channel="email", last_dir=MessageDirection.INBOUND)
            id_out = await _mk_lead(s, p_out, channel="sms", last_dir=MessageDirection.OUTBOUND)
            await s.commit()

        async with await _http_client() as c:
            r = await c.get("/api/v1/inbox?filter=all")
        items = r.json()["items"]
        a = _find(items, id_in)
        b = _find(items, id_out)
        assert a and a["needs_response"] is True
        assert a["last_channel"] == "email" and a["last_direction"] == "inbound"
        assert b and b["needs_response"] is False

        async with await _http_client() as c:
            rp = await c.get("/api/v1/inbox?filter=pending")
        pending_ids = [it["lead_id"] for it in rp.json()["items"]]
        assert id_in in pending_ids
        assert id_out not in pending_ids
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_in, p_out)


@pytest.mark.asyncio
async def test_handled_suppresses_then_rearms(database_url: str) -> None:
    """Marking handled clears pending; a NEW inbound after that re-arms it."""
    sfx = uuid.uuid4().hex[:6]
    phone = f"+34666IBH{sfx}"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead_id = await _mk_lead(s, phone, channel="sms", last_dir=MessageDirection.INBOUND,
                                     created_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC))
            await s.commit()

        async with await _http_client() as c:
            assert _find((await c.get("/api/v1/inbox?filter=all")).json()["items"], lead_id)["needs_response"]
            # Mark handled → pending clears.
            mh = await c.post(f"/api/v1/inbox/{lead_id}/handled")
            assert mh.status_code == 200, mh.text
            after = _find((await c.get("/api/v1/inbox?filter=all")).json()["items"], lead_id)
            assert after["needs_response"] is False
            assert after["handled_at"] is not None

        # A new inbound dated in the future (after handled_at) re-arms pending.
        async with Session() as s:
            conv = (await s.execute(
                select(Conversation).where(Conversation.lead_id == lead_id)
            )).scalars().first()
            s.add(Message(
                conversation_id=conv.id, direction=MessageDirection.INBOUND,
                sender=MessageSender.LEAD, content="following up",
                external_id=f"re_{uuid.uuid4().hex[:10]}", delivery_status=MessageStatus.DELIVERED,
                created_at=datetime(2027, 1, 1, 0, 0, tzinfo=UTC),
            ))
            await s.commit()

        async with await _http_client() as c:
            again = _find((await c.get("/api/v1/inbox?filter=all")).json()["items"], lead_id)
        assert again["needs_response"] is True
    finally:
        await engine.dispose()
        await _cleanup(database_url, phone)


@pytest.mark.asyncio
async def test_booked_filter_and_next_visit(database_url: str) -> None:
    """filter=booked returns only leads with an active visit, ordered by date."""
    sfx = uuid.uuid4().hex[:6]
    p_soon, p_late, p_none = f"+34666VB{sfx}A", f"+34666VB{sfx}B", f"+34666VB{sfx}C"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        soon = datetime.now(UTC) + timedelta(days=1)
        late = datetime.now(UTC) + timedelta(days=5)
        async with Session() as s:
            id_soon = await _mk_lead(s, p_soon, channel="sms", last_dir=MessageDirection.OUTBOUND)
            id_late = await _mk_lead(s, p_late, channel="email", last_dir=MessageDirection.OUTBOUND)
            id_none = await _mk_lead(s, p_none, channel="sms", last_dir=MessageDirection.INBOUND)
            s.add(Visit(lead_id=id_late, external_booking_id=f"v_{uuid.uuid4().hex[:8]}",
                        status=VisitStatus.SCHEDULED, scheduled_at=late))
            s.add(Visit(lead_id=id_soon, external_booking_id=f"v_{uuid.uuid4().hex[:8]}",
                        status=VisitStatus.CONFIRMED, scheduled_at=soon))
            await s.commit()

        async with await _http_client() as c:
            body = (await c.get("/api/v1/inbox?filter=booked")).json()
        booked_ids = [it["lead_id"] for it in body["items"]]
        assert id_none not in booked_ids
        # Ordered by next_visit_at asc → soon before late.
        assert booked_ids.index(id_soon) < booked_ids.index(id_late)
        soon_item = _find(body["items"], id_soon)
        assert soon_item["has_visit"] is True and soon_item["next_visit_at"] is not None
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_soon, p_late, p_none)


@pytest.mark.asyncio
async def test_pending_priority_sort_and_count(database_url: str) -> None:
    """Pending sorted by score desc; count endpoint agrees."""
    sfx = uuid.uuid4().hex[:6]
    p_hot, p_cold = f"+34666PR{sfx}H", f"+34666PR{sfx}C"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            id_hot = await _mk_lead(s, p_hot, channel="sms", last_dir=MessageDirection.INBOUND, score=90)
            id_cold = await _mk_lead(s, p_cold, channel="sms", last_dir=MessageDirection.INBOUND, score=10)
            await s.commit()

        async with await _http_client() as c:
            items = (await c.get("/api/v1/inbox?filter=pending")).json()["items"]
            count = (await c.get("/api/v1/inbox/count")).json()
        ids = [it["lead_id"] for it in items]
        assert ids.index(id_hot) < ids.index(id_cold)  # hotter first
        hot_item = _find(items, id_hot)
        assert hot_item["tier"] == "hot"
        assert count["pending"] >= 2
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_hot, p_cold)


@pytest.mark.asyncio
async def test_past_visit_not_counted_as_booked(database_url: str) -> None:
    """A past SCHEDULED/CONFIRMED visit (status never advanced) is NOT 'booked';
    with a past + a future visit, next_visit_at is the future one."""
    sfx = uuid.uuid4().hex[:6]
    p_past, p_both = f"+34666VP{sfx}A", f"+34666VP{sfx}B"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        past = datetime.now(UTC) - timedelta(days=2)
        future = datetime.now(UTC) + timedelta(days=3)
        async with Session() as s:
            id_past = await _mk_lead(s, p_past, channel="sms", last_dir=MessageDirection.OUTBOUND)
            id_both = await _mk_lead(s, p_both, channel="sms", last_dir=MessageDirection.OUTBOUND)
            s.add(Visit(lead_id=id_past, external_booking_id=f"v_{uuid.uuid4().hex[:8]}",
                        status=VisitStatus.SCHEDULED, scheduled_at=past))
            s.add(Visit(lead_id=id_both, external_booking_id=f"v_{uuid.uuid4().hex[:8]}",
                        status=VisitStatus.SCHEDULED, scheduled_at=past))
            s.add(Visit(lead_id=id_both, external_booking_id=f"v_{uuid.uuid4().hex[:8]}",
                        status=VisitStatus.CONFIRMED, scheduled_at=future))
            await s.commit()

        async with await _http_client() as c:
            items = (await c.get("/api/v1/inbox?filter=all")).json()["items"]
            booked_ids = [it["lead_id"] for it in (await c.get("/api/v1/inbox?filter=booked")).json()["items"]]
        past_item = _find(items, id_past)
        both_item = _find(items, id_both)
        assert past_item["has_visit"] is False  # past-only → not booked
        assert id_past not in booked_ids
        assert both_item["has_visit"] is True
        # next_visit_at is the FUTURE visit, not the earliest (past) one.
        assert both_item["next_visit_at"] is not None
        assert both_item["next_visit_at"] > datetime.now(UTC).isoformat()
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_past, p_both)


@pytest.mark.asyncio
async def test_counts_scoped_to_channel_filter(database_url: str) -> None:
    """With ?channel=X the pending/booked counts reflect only that channel."""
    sfx = uuid.uuid4().hex[:6]
    p_email, p_sms = f"+34666CS{sfx}A", f"+34666CS{sfx}B"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            await _mk_lead(s, p_email, channel="email", last_dir=MessageDirection.INBOUND)
            await _mk_lead(s, p_sms, channel="sms", last_dir=MessageDirection.INBOUND)
            await s.commit()

        async with await _http_client() as c:
            unscoped = (await c.get("/api/v1/inbox?filter=all")).json()
            email_only = (await c.get("/api/v1/inbox?filter=all&channel=email")).json()
        # Global pending count includes both; email-scoped excludes the sms lead.
        assert unscoped["pending_count"] >= 2
        # Every returned item actually has the email channel (filter guarantee).
        assert all("email" in it["channels"] for it in email_only["items"])
        assert email_only["pending_count"] < unscoped["pending_count"]
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_email, p_sms)


@pytest.mark.asyncio
async def test_attention_includes_fresh_unhandled_and_pending(database_url: str) -> None:
    """needs_attention = awaiting reply OR a fresh (<24h) untriaged conversation
    (e.g. a just-finished voice call where the agent spoke last). Old untriaged
    outbound leads do NOT count; marking handled clears it."""
    sfx = uuid.uuid4().hex[:6]
    p_fresh, p_old, p_pend = f"+34666AT{sfx}F", f"+34666AT{sfx}O", f"+34666AT{sfx}P"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        now = datetime.now(UTC)
        async with Session() as s:
            id_fresh = await _mk_lead(s, p_fresh, channel="voice",
                                      last_dir=MessageDirection.OUTBOUND, created_at=now)
            id_old = await _mk_lead(s, p_old, channel="sms", last_dir=MessageDirection.OUTBOUND,
                                    created_at=now - timedelta(days=3))
            id_pend = await _mk_lead(s, p_pend, channel="email", last_dir=MessageDirection.INBOUND,
                                     created_at=now - timedelta(days=3))
            await s.commit()

        async with await _http_client() as c:
            att = (await c.get("/api/v1/inbox?filter=attention")).json()
            att_ids = [it["lead_id"] for it in att["items"]]
            allitems = (await c.get("/api/v1/inbox?filter=all")).json()["items"]
        # Fresh completed call counts even though it's not awaiting a reply.
        assert id_fresh in att_ids
        fresh_item = _find(allitems, id_fresh)
        assert fresh_item["needs_response"] is False and fresh_item["needs_attention"] is True
        # Pending counts; old untriaged outbound does NOT.
        assert id_pend in att_ids
        assert id_old not in att_ids
        assert _find(allitems, id_old)["needs_attention"] is False

        # Marking the fresh one handled clears it from attention.
        async with await _http_client() as c:
            mh = await c.post(f"/api/v1/inbox/{id_fresh}/handled")
            assert mh.status_code == 200
            att2_ids = [it["lead_id"] for it in (await c.get("/api/v1/inbox?filter=attention")).json()["items"]]
        assert id_fresh not in att2_ids
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_fresh, p_old, p_pend)


@pytest.mark.asyncio
async def test_handled_does_not_clobber_concurrent_meta(database_url: str) -> None:
    """Regression: handled state is its own column, so an interleaved writer to
    Lead.meta (e.g. enrichment) and a mark-handled don't clobber each other.

    Under the old meta-blob approach, whichever transaction committed last would
    overwrite the other's meta key. With a dedicated column they touch different
    columns and both survive.
    """
    sfx = uuid.uuid4().hex[:6]
    phone = f"+34666MC{sfx}"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            lead_id = await _mk_lead(s, phone, channel="sms", last_dir=MessageDirection.INBOUND)
            await s.commit()

        # Two overlapping sessions edit the SAME lead.
        async with Session() as s1, Session() as s2:
            l1 = (await s1.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            l2 = (await s2.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            l1.meta = {**(l1.meta or {}), "enrichment": {"partner_type": "referral"}}
            set_handled(l2, datetime.now(UTC))
            await s1.commit()  # writes meta
            await s2.commit()  # writes inbox_handled_at — must NOT wipe meta

        async with Session() as s:
            lead = (await s.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            assert lead.inbox_handled_at is not None
            assert lead.meta.get("enrichment", {}).get("partner_type") == "referral"
    finally:
        await engine.dispose()
        await _cleanup(database_url, phone)


@pytest.mark.asyncio
async def test_mark_handled_idempotent_and_isolated(database_url: str) -> None:
    """POST /handled twice is safe; another lead is unaffected."""
    sfx = uuid.uuid4().hex[:6]
    p_a, p_b = f"+34666MH{sfx}A", f"+34666MH{sfx}B"
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            id_a = await _mk_lead(s, p_a, channel="sms", last_dir=MessageDirection.INBOUND,
                                  created_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC))
            id_b = await _mk_lead(s, p_b, channel="email", last_dir=MessageDirection.INBOUND,
                                  created_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC))
            await s.commit()

        async with await _http_client() as c:
            await c.post(f"/api/v1/inbox/{id_a}/handled")
            await c.post(f"/api/v1/inbox/{id_a}/handled")  # idempotent
            items = (await c.get("/api/v1/inbox?filter=all")).json()["items"]
        assert _find(items, id_a)["needs_response"] is False
        assert _find(items, id_b)["needs_response"] is True  # untouched

        async with await _http_client() as c:
            r404 = await c.post("/api/v1/inbox/999999999/handled")
        assert r404.status_code == 404
    finally:
        await engine.dispose()
        await _cleanup(database_url, p_a, p_b)

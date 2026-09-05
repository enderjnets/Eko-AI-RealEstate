"""The analytics endpoint, asserted on values rather than on shape.

The version this replaces checked that the response had the right keys and
never that any number was right. That is worth stating because it is exactly
how the old `avg_first_response_seconds` shipped counting internal notes as
replies for months: the test was green the whole time.

Each test seeds what it needs and asserts the number it expects. Two of them
exist for defects that were live in production when this was written:

* **The day is the agency's day.** A lead that arrived at 23:30 in Denver was
  filed under the next day, because the grouping ran in UTC.
* **An internal note is not a reply.** A lead nobody ever answered showed a
  two-minute response time because an advisor typed "no answer" into the thread.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import (
    Conversation,
    ConversationStatus,
    LandingSession,
    Lead,
    LeadIntent,
    LeadStatus,
    Message,
    MessageDirection,
    MessageSender,
)

ORG = 1
MARKER = "+1997000"
TZ_OFFSET = timedelta(hours=6)  # Denver is UTC-6 in September (MDT)


async def _cleanup() -> None:
    """Everything, not just this file's rows.

    These tests assert totals, and a total is not a number you can scope to a
    marker: one lead left behind by another test makes "the 3rd has one lead"
    read as four. The suite recreates this database, so clearing it here costs
    nothing and every test below seeds exactly what it measures.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads"))
        await db.execute(text("DELETE FROM landing_sessions"))
        await db.commit()


async def _fresh() -> None:
    await _cleanup()


async def _get(params: str = "") -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/v1/analytics{params}")
        assert resp.status_code == 200, resp.text
        return resp.json()


@pytest.mark.asyncio
async def test_the_envelope_carries_every_section() -> None:
    body = await _get()
    for section in (
        "range",
        "traffic",
        "funnel",
        "leads",
        "response",
        "calls",
        "appointments",
        "deals",
        "content",
        "by_agent",
    ):
        assert section in body, section
    assert body["range"]["timezone"], "a report without a timezone is a report about nothing"


@pytest.mark.asyncio
async def test_a_lead_that_arrived_at_half_eleven_at_night_counts_that_day() -> None:
    """The six-hour error that every individual number hides.

    23:30 on the 3rd in Denver is 05:30 UTC on the 4th. Grouped in UTC the lead
    lands on the 4th, so the two busiest hours of every evening are permanently
    filed under the following morning — and nothing looks wrong, because each
    daily count is still a plausible number.
    """
    await _fresh()
    local_evening = datetime(2026, 9, 3, 23, 30, tzinfo=UTC) + TZ_OFFSET  # 05:30Z on the 4th
    async with get_bypass_session_factory()() as db:
        db.add(
            Lead(
                org_id=ORG,
                phone=f"{MARKER}0001",
                intent=LeadIntent.BUY,
                status=LeadStatus.NEW,
                created_at=local_evening,
            )
        )
        await db.commit()
    try:
        body = await _get("?from=2026-09-03&to=2026-09-03")
        assert body["leads"]["total"] == 1, "the 3rd is the day it happened in Denver"

        body = await _get("?from=2026-09-04&to=2026-09-04")
        assert body["leads"]["total"] == 0, "and it must not also appear on the 4th"

        # The range and the grouping are two different things, and only this
        # second assertion sees the grouping: a window computed in Denver but
        # bucketed in UTC still returns the right total for a one-day range —
        # it just files the lead in the wrong column of the chart. Removing the
        # timezone from `Window.day` left the assertions above perfectly green.
        body = await _get("?from=2026-09-01&to=2026-09-07")
        per_day = {d["date"]: d["leads"] for d in body["leads"]["new_by_day"]}
        assert per_day["2026-09-03"] == 1, per_day
        assert per_day["2026-09-04"] == 0, per_day
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_internal_note_is_not_an_answer() -> None:
    """H8, and the reason the old average was meaningless.

    An advisor typing "called, no answer" into the thread is a note to
    themselves. Counted as a reply it produces a response time for a lead that
    was never answered — a number that is not merely wrong, it is the opposite
    of the truth.
    """
    await _fresh()
    started = datetime.now(UTC) - timedelta(hours=2)
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG, phone=f"{MARKER}0002", intent=LeadIntent.BUY, status=LeadStatus.NEW
        )
        db.add(lead)
        await db.flush()
        conv = Conversation(
            org_id=ORG,
            lead_id=lead.id,
            channel="sms",
            status=ConversationStatus.ACTIVE,
            started_at=started,
        )
        db.add(conv)
        await db.flush()
        db.add(
            Message(
                org_id=ORG,
                conversation_id=conv.id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.HUMAN,
                content="called, no answer",
                internal=True,
                created_at=started + timedelta(minutes=2),
            )
        )
        await db.commit()
    try:
        body = await _get()
        assert body["response"]["first_response_seconds"]["median"] is None
        assert body["response"]["unanswered"] == 1, "they are still waiting"
        assert body["response"]["by_kind"] == {}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_real_reply_is_measured_and_named() -> None:
    await _fresh()
    started = datetime.now(UTC) - timedelta(hours=1)
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG, phone=f"{MARKER}0003", intent=LeadIntent.BUY, status=LeadStatus.NEW
        )
        db.add(lead)
        await db.flush()
        conv = Conversation(
            org_id=ORG,
            lead_id=lead.id,
            channel="sms",
            status=ConversationStatus.ACTIVE,
            started_at=started,
        )
        db.add(conv)
        await db.flush()
        db.add_all(
            [
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Hi, happy to help.",
                    llm_provider="kimi",
                    internal=False,
                    created_at=started + timedelta(seconds=90),
                ),
                # The canned reply that goes out when no model answers. Counted
                # as AI it would hide an outage behind a healthy response time.
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="We'll be right with you.",
                    llm_provider="fallback",
                    internal=False,
                    created_at=started + timedelta(minutes=5),
                ),
            ]
        )
        await db.commit()
    try:
        body = await _get()
        assert body["response"]["first_response_seconds"]["median"] == 90.0
        assert body["response"]["by_kind"] == {"ai": 1, "fallback": 1}
        assert body["response"]["unanswered"] == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_funnel_never_widens_as_it_goes_down() -> None:
    """A stage bigger than the one above it is the shape that makes a funnel
    obviously wrong in a chart and quietly wrong in a table."""
    body = await _get()
    counts = [step["count"] for step in body["funnel"]]
    stages = [step["stage"] for step in body["funnel"]]
    assert stages[-1] == "won"
    assert stages[:4] == ["sessions", "engaged", "cta", "leads"]
    # Leads can exceed sessions — a phone call is a lead with no visit — so the
    # monotonic claim is only made from `leads` down, where it must hold.
    below = counts[stages.index("leads") :]
    assert below == sorted(below, reverse=True), below


@pytest.mark.asyncio
async def test_a_visit_is_counted_where_it_was_read() -> None:
    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        db.add(
            LandingSession(
                org_id=ORG,
                session_key="analytics-" + "a" * 22,
                first_seen_at=now,
                last_seen_at=now,
                source="tiktok",
                device="phone",
                max_scroll_pct=100,
                sections_viewed=["about", "how"],
                tel_clicks=1,
                event_count=6,
            )
        )
        await db.commit()
    try:
        body = await _get()
        traffic = body["traffic"]
        assert traffic["sessions"] >= 1
        assert traffic["engaged"] >= 1, "100% scrolled and two sections read"
        assert traffic["tel_clicks"] >= 1
        assert any(s["name"] == "tiktok" for s in traffic["by_source"])
        assert traffic["sections"]["about"] >= 1
        assert traffic["sections"]["consult"] == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_every_day_in_the_range_appears_even_when_nothing_happened() -> None:
    """A chart drawn from the rows alone closes up empty days, which turns a
    week with two dead days into a smooth line that never happened.

    Seven columns for seven days. The naive version produced eight, because the
    window's end is an instant in UTC and `.date()` on it lands on the next
    Denver morning."""
    body = await _get("?from=2026-09-01&to=2026-09-07")
    assert [d["date"] for d in body["traffic"]["by_day"]] == [
        f"2026-09-0{n}" for n in range(1, 8)
    ]


@pytest.mark.asyncio
async def test_an_inverted_or_absurd_range_is_refused() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/analytics?from=2026-09-10&to=2026-09-01")).status_code == 422
        assert (await c.get("/api/v1/analytics?from=2020-01-01&to=2026-09-01")).status_code == 422
        # Half a range is a typo, not a default: answering it with 30 days would
        # silently ignore the date the person actually typed.
        assert (await c.get("/api/v1/analytics?from=2026-09-01")).status_code == 422


@pytest.mark.asyncio
async def test_the_amount_closed_is_admin_only() -> None:
    from app.api.v1.auth import current_role

    try:
        for role, visible in (("member", False), ("admin", True)):
            app.dependency_overrides[current_role] = lambda role=role: role
            body = await _get()
            assert (body["deals"]["total_value"] is not None) is visible, role
            # The count is not a secret; only the money is.
            assert "won" in body["deals"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_one_agency_never_reads_anothers_numbers() -> None:
    """H7: there was no isolation test for analytics at all.

    Every count must be **zero** under the other organization, not merely
    "no error". Aggregates are the easiest place to leak a tenant boundary,
    because a wrong number looks exactly like a right one and no row is ever
    displayed with somebody else's name on it.
    """
    from app.services.tenant_context import org_scope

    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG, phone=f"{MARKER}0009", intent=LeadIntent.BUY, status=LeadStatus.NEW
        )
        db.add(lead)
        db.add(
            LandingSession(
                org_id=ORG,
                session_key="analytics-" + "b" * 22,
                first_seen_at=now,
                last_seen_at=now,
                source="tiktok",
                max_scroll_pct=100,
                event_count=3,
            )
        )
        await db.commit()
    try:
        from app.services import analytics as svc

        window = svc.Window(
            start=now - timedelta(days=1), end=now + timedelta(days=1), tz=svc.DEFAULT_TZ
        )
        from app.db.base import get_session_factory

        with org_scope(2):
            async with get_session_factory()() as db:
                assert (await svc.leads(db, window))["total"] == 0
                assert (await svc.traffic(db, window))["sessions"] == 0
                assert (await svc.funnel(db, window, await svc.traffic(db, window)))[0][
                    "count"
                ] == 0

        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert (await svc.leads(db, window))["total"] == 1
                assert (await svc.traffic(db, window))["sessions"] == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_range_does_not_reach_back_to_older_publications() -> None:
    """`content` had no range at all: it returned the twenty most recent posts
    whatever was asked, so a seven-day report showed August's videos and
    counted the visits around them."""
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )

    await _fresh()
    old = datetime.now(UTC) - timedelta(days=60)
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="analytics range check",
        )
        db.add(piece)
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.TIKTOK,
                status=PublicationStatus.PUBLISHED,
                published_at=old,
            )
        )
        await db.commit()
        piece_id = piece.id
    try:
        assert (await _get("?range=7d"))["content"] == []
        assert (await _get("?range=90d"))["content"], "and it is there when asked for"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM content_pieces WHERE id = :i"), {"i": piece_id}
            )
            await db.commit()
        await _cleanup()


# There is deliberately no "the endpoint is tenant-bound" test here, and the
# reason is worth writing down rather than leaving as an absence.
#
# A first attempt wrapped the HTTP call in `org_scope(2)` and asserted zero. It
# failed, correctly: the context manager sets the org for *this* coroutine, and
# the request resolves its own tenant inside the app, so the assertion was
# measuring the wrong thing entirely. Making it real needs a signed session for
# a user belonging to the second organization — worth building, but it belongs
# with the auth fixtures and not here.
#
# What IS proven above is the part that carries the guarantee: every section
# reads through the RLS-bound session, and under `org_scope(2)` each one returns
# zero. The router adds one query of its own — `_agency_zone`, reading
# `AgentSettings` — and it uses the same session, so it is inside the same
# boundary as everything it precedes.

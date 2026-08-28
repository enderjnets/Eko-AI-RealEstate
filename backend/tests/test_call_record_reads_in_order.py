"""Two things a real phone call got wrong, and both were visible to the realtor.

1. THE FILE READ SCRAMBLED. A voice call writes its whole transcript at
   hang-up, so every turn shares one `created_at` down to the microsecond. One
   measured call left 27 rows on 2 distinct timestamps; `get_conversation_for_lead`
   ordered by `created_at` alone, so Postgres returned them in whatever order it
   liked and the answer appeared above the question. The thread endpoint next to
   it already tie-broke by id — one of the two was simply never updated.

2. THE APPOINTMENT CARRIED THE WRONG NAME. A lead is keyed by phone and keeps
   the first name ever given for it, so a caller who states a different name is
   ignored — by design, because a realtor can fix a name by hand and voice
   transcription would undo it. The cost was the owner reading his own booking
   under a stranger's name. The stated name now lands on the VISIT, where a bad
   transcription costs one appointment instead of an identity.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.conversation import Conversation, ConversationStatus
from app.models.lead import Lead, LeadStatus
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.models.visit import Visit

ORG = 1
PHONE = "+19995550888"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": PHONE})
        await db.commit()


# ── 1. El orden del expediente ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_call_written_all_at_once_still_reads_in_order(
    database_url: str,
) -> None:
    """The turns share one timestamp, exactly as the voice ingest writes them.

    Insert order is deliberately NOT the reading order here: rows go in with
    ids ascending, and the assertion is that the endpoint returns them that way
    rather than however the database felt like. Without the tie-break this
    passes or fails at random, which is worse than failing.
    """
    await _cleanup()
    stamp = datetime.now(UTC) - timedelta(minutes=5)
    turns = ["greeting", "i want to sell", "which address?", "6000 s fraser"]
    async with get_bypass_session_factory()() as db:
        lead = Lead(org_id=ORG, name="Order Probe", phone=PHONE, status=LeadStatus.NEW)
        db.add(lead)
        await db.flush()
        conv = Conversation(
            org_id=ORG, lead_id=lead.id, channel="voice", status=ConversationStatus.ACTIVE
        )
        db.add(conv)
        await db.flush()
        for i, body in enumerate(turns):
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=(
                        MessageDirection.OUTBOUND if i % 2 == 0 else MessageDirection.INBOUND
                    ),
                    sender=MessageSender.AGENT if i % 2 == 0 else MessageSender.LEAD,
                    content=body,
                    delivery_status=MessageStatus.SENT,
                    created_at=stamp,  # the ingest's single hang-up timestamp
                )
            )
            await db.flush()
        await db.commit()
        lead_id = lead.id

        # Make the physical order disagree with the id order, or this test
        # cannot fail. Postgres has no inherent row order: with four freshly
        # inserted rows a sequential scan happens to return them in insertion
        # order, so the assertion below passed WITHOUT the tie-break too — a
        # test that only ever agreed with the bug it was written for.
        #
        # An UPDATE is what really disturbs it, and it is not contrived: MVCC
        # writes a new version at the end of the heap, and every outbound
        # message gets exactly one update when its delivery status resolves.
        # After this, the second turn is physically last.
        await db.execute(
            text(
                "UPDATE messages SET delivery_status = 'sent' "
                "WHERE conversation_id = :c AND content = :b"
            ),
            {"c": conv.id, "b": turns[1]},
        )
        await db.commit()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/api/v1/conversations/{lead_id}")
        assert r.status_code == 200, r.text
        got = [m["content"] for m in r.json()["messages"]]
        assert got == turns, (
            f"the call reads out of order: {got}. Every row shares one timestamp, "
            "so without a tie-break the database chooses."
        )
    finally:
        await _cleanup()


# ── 2. El nombre en la cita ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_visit_carries_the_name_the_caller_gave(database_url: str) -> None:
    """A returning lead states a different name: the VISIT takes it, the LEAD
    keeps its own. Both halves matter — the second is what protects a name a
    realtor typed by hand."""
    from unittest.mock import AsyncMock, patch

    from app.services.tenant_context import org_scope
    from app.services.voice import handle_tool_call

    await _cleanup()
    async with get_bypass_session_factory()() as db:
        lead = Lead(org_id=ORG, name="Margie Quintero", phone=PHONE, status=LeadStatus.NEW)
        db.add(lead)
        await db.commit()
        lead_id = lead.id

    when = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )

    class _Booking:
        external_booking_id = "voice-name-probe"
        scheduled_at = when
        duration_minutes = 45
        meeting_url = None

    try:
        from app.db.base import get_session_factory

        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    # The office timezone decides how `_parse_dt` reads the
                    # naive wall-clock string the assistant sends, so it is
                    # pinned here: otherwise the slot the mock offers and the
                    # instant the code parses differ by the UTC offset and the
                    # booking is refused as "that time is taken".
                    "app.services.voice._office_tz_name",
                    AsyncMock(return_value="UTC"),
                ), patch(
                    "app.services.calendar_cal.list_available_slots",
                    AsyncMock(return_value=[type("S", (), {"start": when})()]),
                ), patch(
                    "app.services.calendar_cal.create_booking",
                    AsyncMock(return_value=_Booking()),
                ), patch(
                    "app.services.calendar_cal.ensure_recordable",
                    AsyncMock(side_effect=lambda b: b),
                ), patch(
                    "app.api.v1.visits._busy_starts", AsyncMock(return_value=set())
                ), patch(
                    "app.services.visit_invite.send_email",
                    AsyncMock(side_effect=[{"id": "re_n1"}, {"id": "re_n2"}]),
                ):
                    spoken = await handle_tool_call(
                        "book_visit",
                        {
                            "datetime": when.isoformat().replace("+00:00", ""),
                            "name": "Ender Ocando",
                            "property_address": "6000 S Fraser St",
                        },
                        customer_number=PHONE,
                        db=db,
                    )

        assert "booked" in spoken.lower(), spoken
        async with get_bypass_session_factory()() as db:
            visit = (
                await db.execute(
                    select(Visit).where(Visit.external_booking_id == "voice-name-probe")
                )
            ).scalar_one()
            lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
        assert visit.title == "Ender Ocando", (
            "the calendar renders `title or lead_name`, so without this the "
            "booking shows the stale name"
        )
        assert lead.name == "Margie Quintero", (
            "the lead's own name must survive: a realtor may have typed it, and "
            "voice transcription is not good enough to overwrite it"
        )
    finally:
        await _cleanup()

"""A lead's history writes itself, and carries the right organization.

The critical part of this file is not that a row appears. It is `org_id`.

`_stamp_org_id` fills that column in on new rows, and it is the reason nothing
else in the application has to remember to. But a `LeadEvent` created inside a
`before_flush` listener is born in the middle of the flush that the stamping
listener is also part of, and the order two listeners run in is a detail of
SQLAlchemy's registration, not a contract. If the history ran first, every event
for a newly created lead would carry `org_id = None` and be rejected by the
policy — or worse, if the column were nullable, land unattributed.

So the events here are about the two shapes that break it: a lead created inside
a request, whose `org_id` is still None when the listener sees it; and a lead
touched by a background worker on a bypass session, where nothing stamps at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import Lead, LeadEvent, LeadIntent, LeadStatus
from app.services.lead_events import record
from app.services.tenant_context import org_scope

ORG_A = 1
ORG_B = 2

MARKER = "+1999000"


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "DELETE FROM lead_events WHERE lead_id IN "
                "(SELECT id FROM leads WHERE phone LIKE :m)"
            ),
            {"m": f"{MARKER}%"},
        )
        await db.execute(text("DELETE FROM leads WHERE phone LIKE :m"), {"m": f"{MARKER}%"})
        await db.commit()


async def _events(lead_id: int) -> list[LeadEvent]:
    async with get_bypass_session_factory()() as db:
        rows = await db.execute(
            select(LeadEvent).where(LeadEvent.lead_id == lead_id).order_by(LeadEvent.id)
        )
        return list(rows.scalars())


@pytest.mark.asyncio
async def test_a_lead_created_in_a_request_gets_the_acting_org() -> None:
    """The case the phase turns on.

    Inside a request the lead's `org_id` is still None when `before_flush` runs
    — that is exactly what the stamping listener is for. The history has to
    resolve the org itself rather than read a column that is not filled in yet.
    """
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                lead = Lead(
                    phone=f"{MARKER}0000",
                    intent=LeadIntent.BUY,
                    status=LeadStatus.NEW,
                )
                db.add(lead)
                await db.commit()
                lead_id = lead.id

        events = await _events(lead_id)
        assert [e.type for e in events] == ["created"]
        assert events[0].org_id == ORG_A, "the event must not be born without an org"
        assert events[0].to_status == "new"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_status_change_records_where_it_came_from_and_who_did_it() -> None:
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                lead = Lead(
                    phone=f"{MARKER}1001",
                    intent=LeadIntent.VALUATION,
                    status=LeadStatus.NEW,
                )
                db.add(lead)
                await db.commit()
                lead_id = lead.id

                lead.status = LeadStatus.QUALIFIED
                lead._status_actor = "agent@example.com"
                await db.commit()

        events = await _events(lead_id)
        assert [e.type for e in events] == ["created", "status_changed"]
        moved = events[1]
        # The enum's value on both sides. `str(LeadStatus.NEW)` would store
        # "LeadStatus.NEW", which groups into nothing in a report.
        assert (moved.from_status, moved.to_status) == ("new", "qualified")
        assert moved.actor == "agent@example.com"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_write_that_does_not_touch_the_status_records_nothing() -> None:
    """Otherwise every enrichment pass would forge a history entry."""
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                lead = Lead(
                    phone=f"{MARKER}2002",
                    intent=LeadIntent.BUY,
                    status=LeadStatus.NEW,
                )
                db.add(lead)
                await db.commit()
                lead_id = lead.id

                lead.name = "Renamed"
                await db.commit()

        assert [e.type for e in await _events(lead_id)] == ["created"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_background_worker_records_against_the_leads_own_org() -> None:
    """Bypass sessions stamp nothing, and the workers legitimately walk many
    organizations in one loop. The event has to follow the lead, not the
    ambient context — which on those sessions is often None."""
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG_B,
            phone=f"{MARKER}3003",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
        )
        db.add(lead)
        await db.commit()
        lead_id = lead.id
    try:
        with org_scope(None):
            async with get_bypass_session_factory()() as db:
                lead = await db.get(Lead, lead_id)
                lead.status = LeadStatus.PAUSED
                await db.commit()

        events = await _events(lead_id)
        assert [e.type for e in events] == ["created", "status_changed"]
        assert {e.org_id for e in events} == {ORG_B}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_agencys_history_is_invisible_to_the_other() -> None:
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG_A,
            phone=f"{MARKER}4004",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
        )
        db.add(lead)
        await db.commit()
        lead_id = lead.id
    try:
        with org_scope(ORG_B):
            async with get_session_factory()() as db:
                seen = (
                    await db.execute(
                        select(LeadEvent).where(LeadEvent.lead_id == lead_id)
                    )
                ).scalars().all()
        assert seen == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_unknown_event_name_is_refused_at_the_call_site() -> None:
    """A raise, not a skip: a typo here would show up months later as a report
    quietly missing a column, and nobody would know to look."""
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG_A,
            phone=f"{MARKER}5005",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
        )
        db.add(lead)
        await db.commit()
        try:
            with pytest.raises(ValueError, match="Unknown lead event"):
                record(db, lead, "call_inbund")
        finally:
            await _cleanup()


@pytest.mark.asyncio
async def test_an_event_with_nobody_to_attach_to_is_dropped_quietly() -> None:
    """A calendar entry can exist with no lead behind it. There is nothing to
    hang the history on, and refusing to save the appointment over it would be
    the measurement breaking the thing it measures."""
    async with get_bypass_session_factory()() as db:
        assert record(db, None, "appointment_set") is None

@pytest.mark.asyncio
async def test_a_lead_with_no_org_yet_takes_it_from_the_acting_context() -> None:
    """The fallback, tested where it cannot hide.

    The test above passes even without this fallback, and that is the trap:
    `_stamp_org_id` is registered first, so by the time the history listener
    runs the lead already has an org and the fallback is dead code — until
    somebody registers a third listener, or SQLAlchemy stops promising
    registration order, and then every event for a new lead is born orphaned.

    So this calls `record()` directly on a lead that has not been flushed and
    genuinely has `org_id = None`. Deterministic, and independent of what any
    other listener does or when.
    """
    with org_scope(ORG_A):
        async with get_session_factory()() as db:
            lead = Lead(phone=f"{MARKER}9009", intent=LeadIntent.BUY, status=LeadStatus.NEW)
            assert lead.org_id is None, "the premise: nothing has stamped it yet"
            event = record(db, lead, "created")
            assert event is not None
            assert event.org_id == ORG_A


@pytest.mark.asyncio
async def test_an_event_with_no_org_anywhere_is_dropped_rather_than_raised() -> None:
    """Neither the lead nor the context knows the organization. There is no
    correct row to write, and the alternative to dropping it is an exception
    inside a flush that would take a real lead or a real call down with it."""
    with org_scope(None):
        async with get_session_factory()() as db:
            lead = Lead(phone=f"{MARKER}9010", intent=LeadIntent.BUY, status=LeadStatus.NEW)
            assert record(db, lead, "created") is None


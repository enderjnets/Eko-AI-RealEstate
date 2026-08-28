"""The hours an agent declared are the hours the system offers — both lanes.

Phase 1 gave the schedule a place to live and phase 2 gave a person a way to
write it. Neither changed what a lead is told, so until this the feature was a
form that did nothing. What is asserted here is the join: which Cal.com event
type each lane asks about, and what the resulting appointment records.

**Both lanes, deliberately.** The voice tool and `conversation.py` are separate
code paths that answer the same question, and an early version of this plan
converted only the first. That would have left the phone offering an agent's
real hours while the chat kept offering the agency-wide default — two different
answers to "when can I come", from one system, with nothing to reveal the
disagreement.

Cal.com is never called: `CALENDAR_SIMULATED` is the suite default, and where
the real branch matters the boundary is stubbed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentCalendar,
    AppointmentActivity,
    Lead,
    Visit,
    VisitStatus,
)
from app.models.lead import LeadIntent, LeadStatus
from app.services.agent_calendar import BookingTarget, activity_for_lead, pick_agent
from app.services.tenant_context import org_scope

ORG = 1
NATALIA = "hours-natalia@example.com"
ROBBIE = "hours-robbie@example.com"


async def _calendar(
    email: str,
    activity: AppointmentActivity,
    event_type_id: str | None,
    *,
    active: bool = True,
) -> None:
    async with get_bypass_session_factory()() as db:
        db.add(
            AgentCalendar(
                org_id=ORG,
                email=email,
                activity=activity,
                calcom_event_type_id=event_type_id,
                calcom_schedule_id="sched-1" if event_type_id else None,
                active=active,
            )
        )
        await db.commit()


async def _visit(email: str, *, days_ahead: int, marker: str) -> None:
    async with get_bypass_session_factory()() as db:
        db.add(
            Visit(
                org_id=ORG,
                external_booking_id=marker,
                status=VisitStatus.SCHEDULED,
                scheduled_at=datetime.now(UTC) + timedelta(days=days_ahead),
                assigned_email=email,
            )
        )
        await db.commit()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM agent_calendars WHERE email LIKE 'hours-%'")
        )
        await db.execute(
            text("DELETE FROM visits WHERE external_booking_id LIKE 'hours-probe-%'")
        )
        await db.execute(text("DELETE FROM leads WHERE phone LIKE '+1999888%'"))
        await db.commit()


# ── Which appointment a person is actually asking for ────────────────────────


def test_a_seller_gets_a_valuation_and_everybody_else_a_showing() -> None:
    """The mapping that makes this business's own funnel work. Denver Home
    Story exists to find people who want to SELL, and every one of them was
    being booked a buyer's showing: wrong length, wrong hours, and an agent
    turning up prepared for the wrong meeting."""
    from types import SimpleNamespace

    assert (
        activity_for_lead(SimpleNamespace(intent=LeadIntent.VALUATION))
        == AppointmentActivity.VALUATION
    )
    for other in (LeadIntent.BUY, LeadIntent.RENT, LeadIntent.OTHER, None):
        assert (
            activity_for_lead(SimpleNamespace(intent=other))
            == AppointmentActivity.SHOWING
        ), f"{other} should fall back to a showing"


# ── Who takes it ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_with_nobody_configured_it_falls_back_to_the_agency_default() -> None:
    """Turning this feature on must not stop bookings for an agency that has
    not filled it in. Empty target → the caller uses the global event type,
    which is what every lane did before agent scheduling existed."""
    await _cleanup()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                target = await pick_agent(db, AppointmentActivity.SHOWING)
        assert target == BookingTarget(None, None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_row_that_is_off_or_unprovisioned_is_not_bookable() -> None:
    """Offering hours against a calendar with no Cal.com event type promises a
    slot nothing can take."""
    await _cleanup()
    try:
        await _calendar(NATALIA, AppointmentActivity.SHOWING, None)
        await _calendar(ROBBIE, AppointmentActivity.SHOWING, "et-off", active=False)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await pick_agent(db, AppointmentActivity.SHOWING) == BookingTarget()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_with_two_agents_the_lighter_diary_takes_it() -> None:
    """The owner asked for "por ahora solo Natalia, pero escalable". This is the
    escalable half, and it is a test rather than a TODO: enabling the second
    agent has to be a data change, not a code change. Today only one row exists
    in production, so this path is dormant — dormant is not the same as absent.
    """
    await _cleanup()
    try:
        await _calendar(NATALIA, AppointmentActivity.SHOWING, "et-natalia")
        await _calendar(ROBBIE, AppointmentActivity.SHOWING, "et-robbie")
        await _visit(NATALIA, days_ahead=2, marker="hours-probe-1")
        await _visit(NATALIA, days_ahead=3, marker="hours-probe-2")
        await _visit(ROBBIE, days_ahead=2, marker="hours-probe-3")
        with org_scope(ORG):
            async with get_session_factory()() as db:
                target = await pick_agent(db, AppointmentActivity.SHOWING)
        assert target.agent_email == ROBBIE, "the busier agent was picked"
        assert target.event_type_id == "et-robbie"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_past_appointment_does_not_count_against_an_agent() -> None:
    """Otherwise last month's work decides who takes next week's, and an agent
    who has been here longer is quietly starved of new appointments."""
    await _cleanup()
    try:
        await _calendar(NATALIA, AppointmentActivity.SHOWING, "et-natalia")
        await _calendar(ROBBIE, AppointmentActivity.SHOWING, "et-robbie")
        await _visit(NATALIA, days_ahead=-30, marker="hours-probe-old")
        await _visit(ROBBIE, days_ahead=5, marker="hours-probe-new")
        with org_scope(ORG):
            async with get_session_factory()() as db:
                target = await pick_agent(db, AppointmentActivity.SHOWING)
        assert target.agent_email == NATALIA, (
            "a past visit counted as load, so the free agent was skipped"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_choice_is_stable_when_two_agents_are_equally_free() -> None:
    """Not cosmetic. The hours are quoted in one request and booked in another;
    if the tie broke differently between them, the lead would be offered one
    agent's openings and booked into the other's."""
    await _cleanup()
    try:
        await _calendar(NATALIA, AppointmentActivity.SHOWING, "et-natalia")
        await _calendar(ROBBIE, AppointmentActivity.SHOWING, "et-robbie")
        with org_scope(ORG):
            async with get_session_factory()() as db:
                picks = {(await pick_agent(db, AppointmentActivity.SHOWING)).agent_email
                         for _ in range(5)}
        assert len(picks) == 1, f"the tie broke differently across calls: {picks}"
    finally:
        await _cleanup()


# ── The join: what each lane actually asks Cal.com ───────────────────────────


@pytest.mark.asyncio
async def test_the_voice_lane_books_a_seller_on_the_valuation_calendar() -> None:
    """End to end through the tool the phone actually calls.

    Mutation this must catch: dropping `event_type_id` from the `create_booking`
    call, or mapping every lead to a showing. Either one hands a seller a
    buyer's appointment on hours the agent never declared for it.
    """
    from app.services.voice import handle_tool_call

    await _cleanup()
    phone = "+19998881111"
    try:
        async with get_bypass_session_factory()() as db:
            db.add(
                Lead(
                    org_id=ORG,
                    phone=phone,
                    status=LeadStatus.NEW,
                    intent=LeadIntent.VALUATION,
                    name="Seller Probe",
                )
            )
            await db.commit()
        await _calendar(NATALIA, AppointmentActivity.VALUATION, "et-valuation")
        await _calendar(NATALIA, AppointmentActivity.SHOWING, "et-showing")

        when = (datetime.now(UTC) + timedelta(days=3)).replace(
            hour=15, minute=0, second=0, microsecond=0
        )
        booked = AsyncMock()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.calendar_cal.create_booking", booked
                ) as _spy:
                    booked.return_value = __import__(
                        "app.services.calendar_cal", fromlist=["BookingResult"]
                    ).BookingResult(
                        external_booking_id="calcom-sim-probe",
                        scheduled_at=when,
                        duration_minutes=60,
                        meeting_url=None,
                        simulated=True,
                    )
                    await handle_tool_call(
                        "book_visit",
                        {
                            "datetime": when.isoformat(),
                            "property_address": "1 Probe St",
                        },
                        customer_number=phone,
                        db=db,
                    )
        assert booked.await_count == 1, "the booking never reached Cal.com"
        assert booked.await_args.kwargs["event_type_id"] == "et-valuation", (
            "a seller was booked on the showing calendar"
        )

        async with get_bypass_session_factory()() as db:
            visit = (
                await db.execute(
                    text(
                        "SELECT purpose, assigned_email FROM visits "
                        "WHERE external_booking_id = 'calcom-sim-probe'"
                    )
                )
            ).one()
        assert visit.purpose == "valuation"
        assert visit.assigned_email == NATALIA
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM visits WHERE external_booking_id = 'calcom-sim-probe'")
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_the_text_lane_asks_about_the_same_calendar_as_the_phone() -> None:
    """The lane the first draft of the plan forgot.

    With only the voice lane converted, a lead who asks by SMS is quoted the
    agency-wide default while the same person asking by phone is quoted the
    agent's real hours. Nothing in the product would show the disagreement — the
    lead would just be told two different things.
    """
    from app.models import AgentSettings
    from app.services.conversation import _real_slots_note

    await _cleanup()
    try:
        await _calendar(NATALIA, AppointmentActivity.VALUATION, "et-valuation")
        seller = Lead(org_id=ORG, phone="+19998882222", intent=LeadIntent.VALUATION)

        listed = AsyncMock(return_value=[])
        with org_scope(ORG):
            async with get_session_factory()() as db:
                cfg = AgentSettings(org_id=ORG, timezone="UTC")
                with patch(
                    "app.services.calendar_cal.list_available_slots", listed
                ):
                    await _real_slots_note(
                        cfg, "can I book a visit on Tuesday?", db, seller
                    )
        assert listed.await_count == 1, "the text lane never asked for hours"
        assert listed.await_args.kwargs["event_type_id"] == "et-valuation", (
            "the chat quoted the agency default while the phone quotes the "
            "agent's own calendar"
        )
    finally:
        await _cleanup()

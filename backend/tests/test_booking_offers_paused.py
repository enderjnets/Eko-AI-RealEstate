"""While appointments are arranged personally, no automated lane may quote hours.

`BOOKING_OFFERS_PAUSED` exists because Cal.com's conflict source is still only
the brand calendar: an automated booking can double-book the agent, so the
interim funnel promises a call-back instead. Two lanes can quote or take times
and BOTH are gated — the voice tools are also removed in the VAPI console, but
that is external configuration a redeploy could silently restore, so the rule
lives in the codebase too.

The chat gate must return an INSTRUCTION, not an empty string: the docstring
on `_real_slots_note` records the measured failure — left without guidance,
the model invents plausible hours. Withholding the slots without replacing the
instruction would reopen exactly that.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings

ORG = 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.mark.asyncio
async def test_paused_chat_replaces_slots_with_a_callback_instruction(
    database_url: str,
) -> None:
    """Paused + a lead asking for a time → the note tells the model what to
    say instead, and Cal.com is never consulted."""
    from app.db.base import get_session_factory
    from app.models.agent_settings import AgentSettings
    from app.services.conversation import _real_slots_note
    from app.services.tenant_context import org_scope

    calendar = AsyncMock(side_effect=AssertionError("Cal.com must not be consulted"))
    with (
        patch.object(get_settings(), "BOOKING_OFFERS_PAUSED", True),
        patch("app.services.calendar_cal.list_available_slots", calendar),
    ):
        with org_scope(ORG):
            async with get_session_factory()() as db:
                cfg = AgentSettings(org_id=ORG, timezone="America/Denver")
                note = await _real_slots_note(
                    cfg, "can we schedule a visit tomorrow?", db, None
                )
    assert "CITAS EN PAUSA" in note
    assert "llamar" in note.lower()
    assert calendar.await_count == 0


@pytest.mark.asyncio
async def test_paused_chat_stays_quiet_when_nobody_asked_for_a_time(
    database_url: str,
) -> None:
    """The pause note rides the same trigger as the slots did: a message with
    no scheduling talk gets no scheduling instruction — the prompt does not
    grow a permanent paragraph about appointments."""
    from app.db.base import get_session_factory
    from app.models.agent_settings import AgentSettings
    from app.services.conversation import _real_slots_note
    from app.services.tenant_context import org_scope

    with patch.object(get_settings(), "BOOKING_OFFERS_PAUSED", True):
        with org_scope(ORG):
            async with get_session_factory()() as db:
                cfg = AgentSettings(org_id=ORG, timezone="America/Denver")
                note = await _real_slots_note(
                    cfg, "what neighborhoods do you cover?", db, None
                )
    assert note == ""


@pytest.mark.asyncio
async def test_paused_voice_promises_a_callback_and_touches_nothing(
    database_url: str,
) -> None:
    """Both voice tools answer with the call-back line; no slots are listed,
    no booking is created, no lead row is written by the availability probe."""
    from app.db.base import get_session_factory
    from app.services.tenant_context import org_scope
    from app.services.voice import handle_tool_call

    slots = AsyncMock(side_effect=AssertionError("must not list slots"))
    booked = AsyncMock(side_effect=AssertionError("must not book"))
    with (
        patch.object(get_settings(), "BOOKING_OFFERS_PAUSED", True),
        patch("app.services.calendar_cal.list_available_slots", slots),
        patch("app.services.calendar_cal.create_booking", booked),
    ):
        with org_scope(ORG):
            async with get_session_factory()() as db:
                for tool in ("check_availability", "book_visit"):
                    spoken = await handle_tool_call(
                        tool,
                        {"days": 7, "datetime": "2026-09-01T15:00:00"},
                        customer_number="+19995550909",
                        db=db,
                    )
                    assert "call" in spoken.lower(), spoken
                    assert "next few hours" in spoken.lower(), spoken
    assert slots.await_count == 0
    assert booked.await_count == 0


@pytest.mark.asyncio
async def test_unpaused_chat_still_offers_the_real_hours(database_url: str) -> None:
    """The control: with the flag off, the same question still reaches the
    calendar. This is what makes the pause a switch and not a regression."""
    from datetime import UTC, datetime, timedelta

    from app.db.base import get_session_factory
    from app.models.agent_settings import AgentSettings
    from app.services.calendar_cal import Slot
    from app.services.tenant_context import org_scope

    start = datetime.now(UTC) + timedelta(days=1)
    calendar = AsyncMock(return_value=[Slot(start=start, end=start)])
    with (
        patch.object(get_settings(), "BOOKING_OFFERS_PAUSED", False),
        patch("app.services.calendar_cal.list_available_slots", calendar),
    ):
        from app.services.conversation import _real_slots_note

        with org_scope(ORG):
            async with get_session_factory()() as db:
                cfg = AgentSettings(org_id=ORG, timezone="America/Denver")
                note = await _real_slots_note(
                    cfg, "can we schedule a visit tomorrow?", db, None
                )
    assert calendar.await_count == 1
    assert "HUECOS REALES" in note

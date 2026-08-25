"""Tests for the LLM safety-net watchdog.

The whole design is one sentence: **alert on a change, never on a state.** So
the test that matters most is not "does it send an email" — it is "does it stay
quiet on the second tick". An alarm that repeats on a schedule is how six
correct warnings became background noise elsewhere in this house, and a
watchdog that cries every five minutes gets muted, which is worse than not
having one because muting looks like coverage.

These need live Postgres: `run_monitor_tick` opens its own bypass session, and
faking that would test a mock instead of the thing that runs in production.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.monitor_state import MonitorState
from app.services import llm_monitor
from app.services.llm_monitor import MONITOR_KEY, run_monitor_tick
from app.services.ops_alert import MAX_ALERTS_PER_DAY


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — the monitor test needs live Postgres")
    return url


@pytest.fixture
async def clean_state(database_url: str):
    """Start each test from no prior observation, and leave none behind."""
    engine = create_async_engine(database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def wipe() -> None:
        async with factory() as s:
            await s.execute(delete(MonitorState).where(MonitorState.key == MONITOR_KEY))
            await s.commit()

    await wipe()
    yield factory
    await wipe()
    await engine.dispose()


async def _row(factory) -> MonitorState | None:
    async with factory() as s:
        return (
            await s.execute(select(MonitorState).where(MonitorState.key == MONITOR_KEY))
        ).scalar_one_or_none()


def _no_canned_replies():
    """Silence the ground-truth sweep so probe tests measure only the probe."""
    return patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(0, None)))


# ── the probe: one alert per transition ────────────────────────────────────


@pytest.mark.asyncio
async def test_second_tick_in_the_same_state_says_nothing(clean_state) -> None:
    """MUTATION GUARD — the reason this module exists.

    Delete the `previous != status` comparison in `run_monitor_tick` (alert
    whenever the reading is bad) and this test must go red. If it stays green
    the watchdog is a spammer, and a spammer gets muted.
    """
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="model-missing")), \
         patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        await run_monitor_tick()
        assert alert.await_count == 1, "la primera lectura mala debe avisar"
        await run_monitor_tick()
        await run_monitor_tick()

    assert alert.await_count == 1, "el mismo estado no vuelve a avisar"


@pytest.mark.asyncio
async def test_recovery_is_reported_too(clean_state) -> None:
    """Coming back is a change, and the operator needs to stop worrying."""
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="unreachable")):
            await run_monitor_tick()
        with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")):
            await run_monitor_tick()

    assert alert.await_count == 2
    assert "recuperado" in alert.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_a_healthy_first_reading_is_silent(clean_state) -> None:
    """Nothing happened. Saying so on every fresh deploy is noise."""
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")), \
         patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        await run_monitor_tick()

    alert.assert_not_awaited()
    row = await _row(clean_state)
    assert row is not None and row.state == "ok"


@pytest.mark.asyncio
async def test_the_alert_names_the_command_that_fixes_it(clean_state) -> None:
    """An alert that does not say what to do gets postponed until forgotten."""
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="model-missing")), \
         patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        await run_monitor_tick()

    body = alert.await_args.args[1]
    assert "ollama pull" in body


# ── the budget: a loop must be capped, not delivered ───────────────────────


@pytest.mark.asyncio
async def test_daily_budget_stops_a_flapping_provider(clean_state) -> None:
    """Flapping between states is still a loop, and it shares Resend's quota
    with the replies that go to real customers."""
    alert = AsyncMock(return_value=True)
    states = ["unreachable", "ok", "unreachable", "ok", "unreachable"]
    with patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        for st in states:
            with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value=st)):
                await run_monitor_tick()

    assert alert.await_count == MAX_ALERTS_PER_DAY, "el tope corta el resto"


@pytest.mark.asyncio
async def test_a_send_that_fails_does_not_spend_budget(clean_state) -> None:
    """The provider rejected it; the operator was not told. Charging that to
    the budget would let one broken transport silence the next real one."""
    alert = AsyncMock(return_value=False)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="unreachable")), \
         patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        await run_monitor_tick()

    row = await _row(clean_state)
    assert row is not None and row.alerts_today == 0


# ── the ground truth: a customer already paid for it ───────────────────────


@pytest.mark.asyncio
async def test_first_run_takes_a_high_water_mark_instead_of_reporting_history(
    clean_state,
) -> None:
    sweep = AsyncMock(return_value=(5, datetime.now(UTC)))
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")), \
         patch.object(llm_monitor, "send_operator_alert", alert), \
         patch.object(llm_monitor, "_count_canned_replies", sweep):
        await run_monitor_tick()

    sweep.assert_not_awaited()
    alert.assert_not_awaited()
    row = await _row(clean_state)
    assert row is not None and row.last_seen_fallback_at is not None


@pytest.mark.asyncio
async def test_a_canned_reply_is_reported_once_and_not_again(clean_state) -> None:
    """`provider='fallback'` means a real lead got the holding line. It is the
    only signal here that describes damage instead of risk — and reporting the
    same damage every five minutes is how a real alarm turns into wallpaper."""
    alert = AsyncMock(return_value=True)
    newest = datetime.now(UTC) + timedelta(seconds=1)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")), \
         patch.object(llm_monitor, "send_operator_alert", alert):
        with patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(0, None))):
            await run_monitor_tick()  # establishes the high-water mark
        with patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(2, newest))):
            await run_monitor_tick()
        assert alert.await_count == 1
        assert "enlatada" in alert.await_args.args[0]
        # Same window, nothing newer: the mark moved, so this is silent.
        with patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(0, None))):
            await run_monitor_tick()

    assert alert.await_count == 1


@pytest.mark.asyncio
async def test_the_sweep_asks_only_for_rows_newer_than_the_mark(clean_state) -> None:
    """Off-by-one here means either re-reporting forever or missing the next one."""
    alert = AsyncMock(return_value=True)
    sweep = AsyncMock(return_value=(0, None))
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")), \
         patch.object(llm_monitor, "send_operator_alert", alert):
        with patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(0, None))):
            await run_monitor_tick()
        mark = (await _row(clean_state)).last_seen_fallback_at
        with patch.object(llm_monitor, "_count_canned_replies", sweep):
            await run_monitor_tick()

    assert sweep.await_args.args[0] == mark

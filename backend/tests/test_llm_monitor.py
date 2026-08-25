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


@pytest.fixture(autouse=True)
def _channel_is_configured():
    """Assume a usable alert channel unless a test says otherwise.

    The real `undeliverable_reason()` reads settings, and the test environment
    has no sender or API key — so without this every test would take the
    "cannot deliver, do not retry" branch and silently stop exercising the
    retry machine these tests exist to pin down. The one test about an
    unconfigured channel patches it back.
    """
    with patch.object(llm_monitor, "undeliverable_reason", lambda: None):
        yield


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
async def test_a_failed_send_spends_budget_so_a_broken_transport_cannot_loop(
    clean_state,
) -> None:
    """MUTATION GUARD — charge the ATTEMPT, never only the delivery.

    An earlier draft charged successes only, on the reasoning that a retry is
    free. It is not: `send_operator_alert` returns False when the response times
    out, and a message that timed out has often already been delivered. Charging
    nothing means the budget never closes, the next tick tries again, and the
    operator gets 288 real duplicates a day out of the quota that answers leads
    — the exact circuit this cap exists to break.

    Move `alerts_today += 1` back inside `if sent:` and this goes red.
    """
    alert = AsyncMock(return_value=False)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="unreachable")), \
         patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        for _ in range(6):
            await run_monitor_tick()

    assert alert.await_count == MAX_ALERTS_PER_DAY, \
        "el reintento tiene techo: el presupuesto lo cierra"
    row = await _row(clean_state)
    assert row is not None
    assert row.alerts_today == MAX_ALERTS_PER_DAY
    assert row.alerted_state is None, "y sigue pendiente para mañana"


@pytest.mark.asyncio
async def test_an_unconfigured_channel_is_not_retried(clean_state) -> None:
    """"This attempt failed" and "no attempt can succeed" are different facts.

    With no sender configured, every retry reaches nobody. Holding the
    transition open would produce identical log lines on a timer and — in the
    sweep branch — freeze the cutoff, so an unbounded window gets re-counted
    across every organization every five minutes.
    """
    alert = AsyncMock(return_value=False)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="unreachable")), \
         patch.object(llm_monitor, "send_operator_alert", alert), \
         patch.object(llm_monitor, "undeliverable_reason", lambda: "OPS_ALERT_FROM is unset"), \
         _no_canned_replies():
        await run_monitor_tick()
        await run_monitor_tick()

    alert.assert_not_awaited()
    row = await _row(clean_state)
    assert row is not None
    assert row.alerted_state == "unreachable", "consumido: no hay nada que reintentar"
    assert row.alerts_today == 0, "y no gasta presupuesto que nadie va a usar"


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


# ── delivery is durable: a failed send does not consume the outage ─────────
#
# Found by an adversarial review of v0.54.3, and it was the watchdog reproducing
# the exact failure it exists to prevent: the tick committed the new state
# whether or not the email left the building, so one transport hiccup at the
# wrong moment retired the transition and the outage was never mentioned again.
# `state` is what we saw; `alerted_state` is what the operator was told.


@pytest.mark.asyncio
async def test_failed_send_is_retried_next_tick(clean_state) -> None:
    """MUTATION GUARD — the reason `alerted_state` exists.

    Make the tick advance `alerted_state` without checking the send result and
    this goes red: the second tick would find no gap and stay silent forever.
    """
    alert = AsyncMock(return_value=False)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="unreachable")), \
         patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        await run_monitor_tick()
        assert alert.await_count == 1

        await run_monitor_tick()
        assert alert.await_count == 2, "un envio fallido debe reintentarse"

        row = await _row(clean_state)
        assert row is not None
        assert row.state == "unreachable", "lo observado si avanza"
        assert row.alerted_state is None, "lo comunicado NO avanza sin acuse"

        # Once it lands, the gap closes and the noise stops.
        alert.return_value = True
        await run_monitor_tick()
        assert alert.await_count == 3
        await run_monitor_tick()

    assert alert.await_count == 3, "entregado una vez, no se repite"
    row = await _row(clean_state)
    assert row is not None and row.alerted_state == "unreachable"


@pytest.mark.asyncio
async def test_failed_ground_truth_send_does_not_advance_the_mark(clean_state) -> None:
    """MUTATION GUARD — move `last_seen_fallback_at = newest` above the send and
    this goes red.

    A rejected email must not erase the evidence that a real customer received
    the holding line. That is the only signal here describing damage already
    done, so losing it is worse than losing a risk warning.
    """
    newest = datetime.now(UTC) + timedelta(seconds=1)
    alert = AsyncMock(return_value=False)
    sweep = AsyncMock(return_value=(2, newest))
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")), \
         patch.object(llm_monitor, "send_operator_alert", alert):
        with patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(0, None))):
            await run_monitor_tick()  # establishes the high-water mark
        mark = (await _row(clean_state)).last_seen_fallback_at

        with patch.object(llm_monitor, "_count_canned_replies", sweep):
            await run_monitor_tick()
            assert alert.await_count == 1
            assert (await _row(clean_state)).last_seen_fallback_at == mark, \
                "el envio fallo: la marca no puede avanzar"

            alert.return_value = True
            await run_monitor_tick()
            assert alert.await_count == 2, "reintenta hasta entregarlo"

    assert (await _row(clean_state)).last_seen_fallback_at == newest


@pytest.mark.asyncio
async def test_budget_exhaustion_delivers_after_the_day_rolls_over(
    clean_state, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap must delay an alert, never cancel it.

    Capping is how the watchdog avoids exhausting the mail quota it shares with
    replies to real customers. But a cap that also forgets is just a slower way
    of losing the outage.
    """
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "send_operator_alert", alert), _no_canned_replies():
        monkeypatch.setattr(llm_monitor, "_today_utc", lambda: "2026-08-25")
        for st in ["unreachable", "ok", "unreachable", "ok"]:
            with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value=st)):
                await run_monitor_tick()

        assert alert.await_count == MAX_ALERTS_PER_DAY
        row = await _row(clean_state)
        assert row is not None
        assert row.state == "ok" and row.alerted_state == "unreachable", \
            "el 4o aviso no salio: sigue pendiente"

        monkeypatch.setattr(llm_monitor, "_today_utc", lambda: "2026-08-26")
        with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")):
            await run_monitor_tick()

    assert alert.await_count == MAX_ALERTS_PER_DAY + 1, "al dia siguiente se entrega"
    row = await _row(clean_state)
    assert row is not None and row.alerted_state == "ok"


@pytest.mark.asyncio
async def test_an_unconfigured_channel_also_consumes_the_damage_mark(
    clean_state,
) -> None:
    """The sweep branch of the same decision, which had no test at all.

    An audit found this one uncovered, and it is the more uncomfortable half:
    the high-water mark records that a real customer already received the
    holding line, and here it advances without anyone being told. That is still
    the right call — no retry reaches an unconfigured channel, and holding the
    cutoff back would re-count an unbounded window across every organization on
    every tick, over a column with no index. But it means the evidence lives
    only in `messages.llm_provider` from then on, so the behaviour is pinned
    here rather than left to be rediscovered.
    """
    newest = datetime.now(UTC) + timedelta(seconds=1)
    alert = AsyncMock(return_value=True)
    with patch.object(llm_monitor, "check_fallback_provider", AsyncMock(return_value="ok")), \
         patch.object(llm_monitor, "send_operator_alert", alert):
        with patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(0, None))):
            await run_monitor_tick()  # establishes the mark
        with patch.object(llm_monitor, "undeliverable_reason", lambda: "OPS_ALERT_FROM is unset"), \
             patch.object(llm_monitor, "_count_canned_replies", AsyncMock(return_value=(3, newest))):
            await run_monitor_tick()

    alert.assert_not_awaited()
    row = await _row(clean_state)
    assert row is not None
    assert row.last_seen_fallback_at == newest, "consumido: no hay nada que reintentar"
    assert row.alerts_today == 0

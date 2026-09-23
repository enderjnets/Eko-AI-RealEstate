"""A deploy must not restart the clock of a once-a-day worker from zero.

Both metrics loops used to sleep their whole interval BEFORE the first pass.
The backend is deployed about once a day, so the Buffer pass (24 h) could only
run after a full day without a deploy.
"""

from __future__ import annotations

import asyncio
from itertools import islice

import pytest

from app import main
from app.config import get_settings
from app.services import tenant_context


def test_the_first_wait_is_short_and_the_rest_are_the_interval() -> None:
    assert list(islice(main._waits(86_400), 3)) == [
        main.FIRST_PASS_AFTER_BOOT_SECONDS,
        86_400,
        86_400,
    ]
    # Never longer than the interval itself.
    assert next(main._waits(60)) == 60


async def _two_ticks(loop, monkeypatch) -> tuple[list[float], list[str]]:
    slept: list[float] = []
    ran: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 2:
            raise asyncio.CancelledError

    async def fake_every_org(fn) -> None:
        ran.append(fn.__name__)

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(tenant_context, "run_for_every_org", fake_every_org)
    with pytest.raises(asyncio.CancelledError):
        await loop()
    return slept, ran


@pytest.mark.asyncio
async def test_the_buffer_pass_runs_minutes_after_boot(monkeypatch) -> None:
    slept, ran = await _two_ticks(main._buffer_metrics_loop, monkeypatch)
    interval = max(3600, get_settings().CONTENT_BUFFER_METRICS_INTERVAL_SECONDS)
    assert slept == [main.FIRST_PASS_AFTER_BOOT_SECONDS, interval]
    # The deleted-post pass rides the same daily tick. Five minutes after a
    # deploy is before the writer's first hourly pass, so a day freed in
    # Buffer is free by the time the writer looks for one.
    assert ran == ["snapshot_buffer", "forget_deleted_future"]


@pytest.mark.asyncio
async def test_a_failed_metrics_read_does_not_skip_the_deleted_post_pass(
    monkeypatch,
) -> None:
    ran: list[str] = []
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 2:
            raise asyncio.CancelledError

    async def fake_every_org(fn) -> None:
        ran.append(fn.__name__)
        if fn.__name__ == "snapshot_buffer":
            raise RuntimeError("quota")

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(tenant_context, "run_for_every_org", fake_every_org)
    with pytest.raises(asyncio.CancelledError):
        await main._buffer_metrics_loop()
    assert ran == ["snapshot_buffer", "forget_deleted_future"]


@pytest.mark.asyncio
async def test_the_youtube_pass_runs_minutes_after_boot(monkeypatch) -> None:
    slept, ran = await _two_ticks(main._content_metrics_loop, monkeypatch)
    interval = max(3600, get_settings().CONTENT_METRICS_INTERVAL_SECONDS)
    assert slept == [main.FIRST_PASS_AFTER_BOOT_SECONDS, interval]
    assert ran == ["snapshot_youtube"]

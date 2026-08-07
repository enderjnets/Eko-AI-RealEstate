"""Cal.com service — simulated slots + booking + cancellation (no network)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.calendar_cal import (
    SIMULATED_HOURS_OF_DAY,
    Slot,
    _simulated_slots,
    cancel_booking,
    create_booking,
    list_available_slots,
)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def test_simulated_slots_only_weekdays() -> None:
    # 2026-05-25 is a Monday → 5 weekdays in next 7 days.
    start = _utc(2026, 5, 25, 0)
    end = start + timedelta(days=7)
    slots = _simulated_slots(start, end)
    weekdays_seen = {s.start.date() for s in slots}
    # 5 weekdays in the [Mon-Mon) window — Mon, Tue, Wed, Thu, Fri.
    assert len(weekdays_seen) == 5
    # Sat (2026-05-30) + Sun (2026-05-31) excluded.
    assert all(s.start.weekday() < 5 for s in slots)


def test_simulated_slots_hours_match_constant() -> None:
    start = _utc(2026, 5, 25, 0)
    end = start + timedelta(days=2)
    slots = _simulated_slots(start, end)
    hours = {s.start.hour for s in slots}
    assert hours == set(SIMULATED_HOURS_OF_DAY)


def test_simulated_slots_filters_busy() -> None:
    start = _utc(2026, 5, 25, 0)
    end = start + timedelta(days=1)
    busy = {_utc(2026, 5, 25, 10), _utc(2026, 5, 25, 14)}
    slots = _simulated_slots(start, end, busy_starts=busy)
    starts = {s.start for s in slots}
    assert _utc(2026, 5, 25, 10) not in starts
    assert _utc(2026, 5, 25, 14) not in starts
    assert _utc(2026, 5, 25, 11) in starts  # 11h not busy


@pytest.mark.asyncio
async def test_list_available_slots_uses_simulated_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_SIMULATED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    start = _utc(2026, 5, 25, 0)
    end = start + timedelta(days=2)
    slots = await list_available_slots(start=start, end=end)
    assert isinstance(slots, list)
    assert len(slots) > 0
    assert all(isinstance(s, Slot) for s in slots)


@pytest.mark.asyncio
async def test_create_booking_simulated_returns_calcom_sim_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_SIMULATED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    result = await create_booking(
        start_time=_utc(2026, 5, 26, 10),
        attendee_name="Juan Test",
        attendee_email="juan@test.com",
        attendee_phone=None,
        notes="visita Malasaña",
    )
    assert result.simulated is True
    assert result.external_booking_id.startswith("calcom-sim-")
    assert result.scheduled_at == _utc(2026, 5, 26, 10)
    assert result.duration_minutes == 30
    assert result.meeting_url is None


@pytest.mark.asyncio
async def test_cancel_booking_simulated_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_SIMULATED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    ok = await cancel_booking("calcom-sim-deadbeef", reason="cliente reagendó")
    assert ok is True


@pytest.mark.asyncio
async def test_cancel_simulated_id_works_even_with_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A booking id with calcom-sim- prefix always uses simulated cancel, even
    in production mode — useful for cleanup of dev bookings without hitting API."""
    monkeypatch.setenv("CALENDAR_SIMULATED", "false")
    monkeypatch.setenv("CALCOM_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    ok = await cancel_booking("calcom-sim-fakeid", reason="x")
    assert ok is True

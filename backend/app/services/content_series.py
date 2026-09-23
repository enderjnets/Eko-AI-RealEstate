"""Trusted editorial calendar and production contracts for DHS video lines."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.models import ContentSeries


@dataclass(frozen=True)
class ContentContract:
    word_min: int
    word_max: int
    scene_min: int
    scene_max: int
    duration_min: float
    duration_max: float
    social_ctas: tuple[str, ...]
    requires_site_link: bool
    objective: str


_CONVERSION = ContentContract(
    word_min=45,
    word_max=65,
    scene_min=7,
    scene_max=9,
    duration_min=20,
    duration_max=35,
    social_ctas=(),
    requires_site_link=True,
    objective="Turn qualified attention into site visits and conversations.",
)
_GROWTH = ContentContract(
    word_min=25,
    word_max=35,
    scene_min=5,
    scene_max=6,
    duration_min=12,
    duration_max=18,
    social_ctas=("follow", "comment", "share"),
    requires_site_link=False,
    objective="Earn follows, comments and shares with useful Denver knowledge.",
)
_WEEKEND = ContentContract(
    word_min=25,
    word_max=35,
    scene_min=5,
    scene_max=6,
    duration_min=12,
    duration_max=18,
    social_ctas=("save", "share"),
    requires_site_link=False,
    objective="Earn saves and shares with a timely Denver weekend idea.",
)
_AUTHORITY = ContentContract(
    word_min=25,
    word_max=35,
    scene_min=5,
    scene_max=6,
    duration_min=12,
    duration_max=18,
    social_ctas=("follow",),
    requires_site_link=False,
    objective="Build trust with a dated, sourced Denver market explanation.",
)

_CONTRACTS = {
    ContentSeries.CONVERSION: _CONVERSION,
    ContentSeries.DENVER_DECODED: _GROWTH,
    ContentSeries.DENVER_WEEKEND: _WEEKEND,
    ContentSeries.DENVER_MARKET_NO_HYPE: _AUTHORITY,
    # Recorded answers use the short authority format once the line is on.
    ContentSeries.ASK_DENVER_HOME_STORY: _AUTHORITY,
}


def contract_for(series: ContentSeries) -> ContentContract:
    return _CONTRACTS[series]


def series_for_date(day: date, *, ask_enabled: bool = False) -> ContentSeries:
    """The approved calendar, keyed to a Denver-local date."""
    weekday = day.weekday()
    if weekday in (0, 2, 4):
        return ContentSeries.DENVER_DECODED
    if weekday in (1, 6):
        return ContentSeries.CONVERSION
    if weekday == 5:
        return ContentSeries.DENVER_WEEKEND
    if ask_enabled and day.isocalendar().week % 2 == 0:
        return ContentSeries.ASK_DENVER_HOME_STORY
    return ContentSeries.DENVER_MARKET_NO_HYPE


def next_editorial_date(
    today: date,
    *,
    scheduled_dates: Iterable[date],
    reserved_dates: Iterable[date],
) -> date:
    """The first day from `today` that nothing already owns; never rewrite one.

    The first free day, not the day after the last taken one. With `max + 1` a
    single piece kept on 26-oct pushed every new line past it and left the
    month in between empty (23-sep-2026).
    """
    occupied = {day for day in (*scheduled_dates, *reserved_dates) if day >= today}
    day = today
    while day in occupied:
        day += timedelta(days=1)
    return day


def render_contract(series: ContentSeries) -> dict[str, int | float | str]:
    contract = contract_for(series)
    # The deterministic sign-off may add words after the writer's range. The
    # worker limit includes that tail while the writer limit does not.
    tail_words = {
        ContentSeries.CONVERSION: 10,
        ContentSeries.DENVER_DECODED: 7,
        ContentSeries.DENVER_WEEKEND: 6,
        ContentSeries.DENVER_MARKET_NO_HYPE: 7,
        ContentSeries.ASK_DENVER_HOME_STORY: 9,
    }
    word_max = contract.word_max + tail_words[series]
    return {
        "series": series.value,
        "duration_min": contract.duration_min,
        "duration_max": contract.duration_max,
        "word_max": word_max,
        "scene_min": contract.scene_min,
        "scene_max": contract.scene_max,
    }

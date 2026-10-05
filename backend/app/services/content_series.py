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


# 60-80 words and a floor of 18 s since 25-sep-2026: piece 92 (56 words) came
# out at 19.2 s and 18.5 s on the MiniMax-only voice and was refused twice
# against 20. Same measured spread as the short lines below. Ceiling 40 since
# 4-oct-2026, for the slower voice (see the note above _GROWTH).
_CONVERSION = ContentContract(
    word_min=60,
    word_max=80,
    scene_min=7,
    scene_max=9,
    duration_min=18,
    duration_max=40,
    social_ctas=(),
    requires_site_link=True,
    objective="Turn qualified attention into site visits and conversations.",
)
# The three short lines aim for 20-30 s. They were 25-35 words and 8-18 s
# until 24-sep-2026, when Ender rejected piece 88 (11 s): at that length the
# video never says what it is about. The DHS voice (MiniMax only since 23-sep)
# spoke 2.9-3.9 narrated words a second across the four renders of piece 88,
# so 65-80 script words plus the 7-word spoken sign-off last 18.5-30 s. The
# render bounds are 18-32, slightly wider than the aim, so a take inside that
# measured spread is not refused after its narration and pictures are paid for.
# 4-oct-2026: the voice is English_Upbeat_Woman at normal speed (Ender's choice
# from the DIA prototype), measured at 2.43-2.91 words a second on four real
# DHS scripts (97, 99, 101, 103). The same 65-80 words plus the sign-off now
# last 25-36 s. Ender chose slightly longer videos over shorter scripts, so the
# ceiling is 38: 87 narrated words at 2.3, a margin under the slowest take.
_GROWTH = ContentContract(
    word_min=65,
    word_max=80,
    scene_min=6,
    scene_max=8,
    duration_min=18,
    duration_max=38,
    social_ctas=("follow", "comment", "share"),
    requires_site_link=False,
    objective="Earn follows, comments and shares with useful Denver knowledge.",
)
_WEEKEND = ContentContract(
    word_min=65,
    word_max=80,
    scene_min=6,
    scene_max=8,
    duration_min=18,
    duration_max=38,
    social_ctas=("save", "share"),
    requires_site_link=False,
    objective="Earn saves and shares with a timely Denver weekend idea.",
)
_AUTHORITY = ContentContract(
    word_min=65,
    word_max=80,
    scene_min=6,
    scene_max=8,
    duration_min=18,
    duration_max=38,
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

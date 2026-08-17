"""The voice agent resolves a wall clock too, and it was the sibling I missed.

The HTTP routes learned to refuse an hour that does not exist on the
spring-forward date. `voice.py` has its own resolver and did not, so a caller
on the phone naming 02:30 that morning was given a 03:30 appointment — and
02:30 and 03:30 became the same instant, which the double-booking guard reads
as a clash between two different people.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from app.services.voice import _parse_dt

DENVER = ZoneInfo("America/Denver")


def test_the_hour_that_does_not_exist_is_refused() -> None:
    assert _parse_dt("2027-03-14T02:30:00", DENVER) is None


def test_the_hours_on_either_side_still_book() -> None:
    before = _parse_dt("2027-03-14T01:59:00", DENVER)
    after = _parse_dt("2027-03-14T03:30:00", DENVER)
    assert before is not None and after is not None
    assert before != after


def test_an_ambiguous_autumn_hour_still_books() -> None:
    """It happens twice; resolving to the first pass is deterministic, not a refusal."""
    assert _parse_dt("2027-11-07T01:30:00", DENVER) is not None


def test_an_ordinary_time_is_unchanged() -> None:
    resolved = _parse_dt("2027-06-01T14:00:00", DENVER)
    assert resolved is not None
    assert resolved.astimezone(DENVER).hour == 14

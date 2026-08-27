"""The four things that go wrong in an .ics, each one checked on its own.

None of them fails loudly. A file with the wrong line endings is simply refused
by Apple Calendar and Outlook; a badly folded line truncates in some clients and
not others; an unescaped comma silently shortens an address; and a local time
written with a `Z` produces an appointment at the wrong hour that everybody
believes. The recipient sees a broken or wrong invitation and we see a sent
email, which is the same shape of failure as the SMS that Twilio accepted and
the carrier dropped.

There is no iCalendar parser in this project and this is not a reason to add
one: the checks below are properties of the output, and folding in particular
is verified by round trip — fold, then unfold with the RFC's own rule, and
require the original back.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.icalendar import build_visit_ics

DENVER = ZoneInfo("America/Denver")


def _unfold(text: str) -> list[str]:
    """RFC 5545 §3.1 unfolding: a CRLF followed by a space or tab is removed."""
    return text.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")


def _ics(**over) -> str:
    args = dict(
        uid="visit-1@realtors.ekoaiautomation.com",
        starts_at=datetime(2026, 9, 3, 10, 0, tzinfo=DENVER),
        duration_minutes=30,
        summary="Showing",
        organizer_email="natalia@example.com",
        now=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )
    args.update(over)
    return build_visit_ics(**args)


def test_every_line_ends_with_crlf_including_the_last() -> None:
    out = _ics()
    assert "\r\n" in out
    # A bare LF anywhere means some line was joined without the CR.
    assert out.replace("\r\n", "").count("\n") == 0
    assert out.endswith("END:VCALENDAR\r\n")


def test_a_long_line_folds_and_unfolds_back_to_exactly_itself() -> None:
    """The round trip is the test. Asserting 'it contains a space' would pass
    for a file folded in the wrong place, which is the only interesting bug."""
    address = "1234 Extremely Long Street Name Suite 900 Denver Colorado 80202 United States"
    out = _ics(location=address)
    for line in out.split("\r\n"):
        # Continuations are the only lines allowed to start with a space.
        assert len(line.encode("utf-8")) <= 75 or line.startswith(" ")
    unfolded = _unfold(out)
    assert f"LOCATION:{address}" in unfolded


def test_folding_never_cuts_a_character_in_half() -> None:
    """Counted in octets, not characters, with the boundary placed ON PURPOSE.

    The first version of this test used a long accented string and passed even
    with the boundary check removed: nothing guaranteed that a multi-byte
    character actually straddled octet 75, so the branch was never exercised.
    A mutation proved it was decoration. Here the split is constructed:
    "SUMMARY:" is 8 octets, then 66 ASCII characters take it to 74, so the
    two-octet "ñ" occupies octets 75-76 and a naive cut lands between them.
    """
    padding = "a" * 66
    name = f"{padding}ñtail"
    assert len(f"SUMMARY:{padding}".encode()) == 74  # the boundary is where we think
    out = _ics(summary=name)
    out.encode("utf-8").decode("utf-8")  # raises if a fold split a sequence
    assert f"SUMMARY:{name}" in _unfold(out)


@pytest.mark.parametrize(
    "raw,escaped",
    [
        ("1234 Main St, Denver", "1234 Main St\\, Denver"),
        ("Unit 3; rear entrance", "Unit 3\\; rear entrance"),
        ("back\\slash", "back\\\\slash"),
        ("line one\nline two", "line one\\nline two"),
    ],
)
def test_text_values_are_escaped(raw: str, escaped: str) -> None:
    """An unescaped comma ends the value early: '1234 Main St, Denver' becomes
    an appointment at '1234 Main St'."""
    assert f"LOCATION:{escaped}" in _unfold(_ics(location=raw))


def test_a_denver_morning_is_written_as_the_right_utc_instant() -> None:
    # 10:00 in Denver on 3-sep is MDT (UTC-6) → 16:00Z. Getting this wrong by
    # writing local time with a Z is the six-hour bug this repo already paid for.
    out = _unfold(_ics())
    assert "DTSTART:20260903T160000Z" in out
    assert "DTEND:20260903T163000Z" in out


def test_a_naive_datetime_is_refused_instead_of_assumed_to_be_utc() -> None:
    """Guessing produces a confident wrong answer, which is worse than an error."""
    with pytest.raises(ValueError, match="naive"):
        _ics(starts_at=datetime(2026, 9, 3, 10, 0))


def test_the_end_follows_the_duration() -> None:
    out = _unfold(_ics(duration_minutes=90))
    assert "DTEND:20260903T173000Z" in out


def test_a_zero_duration_still_produces_an_end_after_the_start() -> None:
    """A zero-length event is dropped by some clients and shown as all-day by
    others. Neither is what a 'visit' means."""
    out = _unfold(_ics(duration_minutes=0))
    # Compare the timestamps, not the whole lines: "DTEND:" sorts before
    # "DTSTART:" alphabetically, so comparing the lines passes for the wrong
    # reason and fails for the right one. This assertion caught itself.
    start = [ln for ln in out if ln.startswith("DTSTART:")][0].split(":", 1)[1]
    end = [ln for ln in out if ln.startswith("DTEND:")][0].split(":", 1)[1]
    assert end > start


def test_the_attendee_is_asked_to_reply() -> None:
    out = _unfold(_ics(attendee_email="lead@example.com", attendee_name="Ana Pérez"))
    line = [ln for ln in out if ln.startswith("ATTENDEE")][0]
    assert "RSVP=TRUE" in line
    assert "mailto:lead@example.com" in line
    assert "CN=Ana Pérez" in line


def test_no_attendee_line_when_there_is_no_email() -> None:
    # A lead who left only a phone gets no ATTENDEE stanza rather than an empty
    # mailto:, which some clients treat as a malformed event.
    assert not [ln for ln in _unfold(_ics()) if ln.startswith("ATTENDEE")]


def test_a_cancellation_keeps_the_uid_and_says_cancel() -> None:
    """Same UID is what lets a client remove the event it already accepted. A
    new UID would leave the original sitting in the calendar."""
    booked = _unfold(_ics())
    cancelled = _unfold(_ics(cancelled=True, sequence=1))
    uid = [ln for ln in booked if ln.startswith("UID:")][0]
    assert uid in cancelled
    assert "METHOD:CANCEL" in cancelled
    assert "STATUS:CANCELLED" in cancelled
    assert "SEQUENCE:1" in cancelled


def test_the_required_skeleton_is_present() -> None:
    out = _unfold(_ics())
    for required in ("BEGIN:VCALENDAR", "VERSION:2.0", "END:VEVENT", "END:VCALENDAR"):
        assert required in out
    assert [ln for ln in out if ln.startswith("PRODID:")]
    assert [ln for ln in out if ln.startswith("DTSTAMP:")]

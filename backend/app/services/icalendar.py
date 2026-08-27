"""Build the calendar invitation for a visit — RFC 5545, by hand.

Until now a booking existed only in our `visits` table. The dashboard showed it,
the phone assistant told the caller out loud that it was confirmed, and nothing
reached anybody's actual calendar: `CALENDAR_SIMULATED` defaults to true, so
`create_booking` returns a synthetic `calcom-sim-…` id and books nothing. Every
visit in production carries one of those ids. This is the piece that makes the
promise true without paying for a scheduling product.

Written by hand rather than pulling in `icalendar`: the whole format we need is
one VEVENT, and the four things that actually go wrong — CRLF, folding,
escaping, UTC — are the four things below. A dependency would not remove them
from the review, only from the diff.

The four, because each one fails differently and none of them fails loudly:

1. **CRLF.** RFC 5545 §3.1: lines end with CRLF. Apple Calendar and Outlook
   reject a file with bare LF outright — no error to the sender, the recipient
   simply gets an attachment that will not open.
2. **Folding at 75 octets.** Long lines must be split with CRLF + one space.
   Unfolded, a long address or description silently truncates in some clients.
   Counted in OCTETS, not characters: "Peña" is five octets in four characters,
   and a fold that lands mid-sequence corrupts it.
3. **Escaping.** In TEXT values, backslash, semicolon, comma and newline are
   delimiters. An unescaped comma in a street address ends the value early, so
   "1234 Main St, Denver" becomes an event at "1234 Main St".
4. **UTC.** `DTSTART` with a `Z` suffix must be genuinely UTC. Writing local
   time with a Z is the six-hour bug this repo has already paid for once.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Folding is defined in octets, so the limit is on the encoded bytes.
_MAX_OCTETS = 75


def _escape(value: str) -> str:
    """Escape a TEXT value. Order matters: backslash first, or it doubles the
    escapes introduced by the later replacements."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold one content line to 75 octets, continuation lines starting with a space.

    Splits on octet boundaries of the UTF-8 encoding, never inside a multi-byte
    character: a fold placed mid-sequence produces a file that is not valid
    UTF-8, which some clients render as replacement characters and others
    refuse entirely.
    """
    raw = line.encode("utf-8")
    if len(raw) <= _MAX_OCTETS:
        return line

    chunks: list[bytes] = []
    start = 0
    # First line takes 75 octets; continuations take 74, since the leading
    # space counts toward the limit.
    limit = _MAX_OCTETS
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Walk back off a continuation byte (0b10xxxxxx) so we cut between
        # characters.
        while end > start and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(raw[start:end])
        start = end
        limit = _MAX_OCTETS - 1
    head, *rest = (c.decode("utf-8") for c in chunks)
    return "\r\n ".join([head, *rest])


def _utc(value: datetime) -> str:
    """Format as an RFC 5545 UTC timestamp.

    A naive datetime is REFUSED rather than assumed to be UTC. Assuming is how
    an appointment lands six hours off — the exact failure this project fixed in
    v0.56.0, in four separate places. If the caller does not know the zone,
    neither do we, and guessing produces a confident wrong answer.
    """
    if value.tzinfo is None:
        raise ValueError("refusing to write a naive datetime as UTC; attach a timezone")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_visit_ics(
    *,
    uid: str,
    starts_at: datetime,
    duration_minutes: int,
    summary: str,
    organizer_email: str,
    organizer_name: str | None = None,
    attendee_email: str | None = None,
    attendee_name: str | None = None,
    location: str | None = None,
    description: str | None = None,
    sequence: int = 0,
    cancelled: bool = False,
    now: datetime | None = None,
) -> str:
    """One VEVENT, ready to attach as `invite.ics`.

    `cancelled=True` emits METHOD:CANCEL with the same UID, which is how a
    calendar client removes an event it already accepted. Same UID and a higher
    `sequence` is an update; a new UID is a second event sitting next to the
    first, which is the usual way rescheduling goes wrong.
    """
    stamp = _utc(now or datetime.now(UTC))
    ends_at = starts_at + timedelta(minutes=max(1, duration_minutes))

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        # PRODID is required. Ours identifies the product, which is also what a
        # recipient's client shows as the source of the invitation.
        "PRODID:-//Eko AI Realtors//Visit Invitation//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{'CANCEL' if cancelled else 'REQUEST'}",
        "BEGIN:VEVENT",
        f"UID:{_escape(uid)}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_utc(starts_at)}",
        f"DTEND:{_utc(ends_at)}",
        f"SUMMARY:{_escape(summary)}",
        f"SEQUENCE:{max(0, sequence)}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
    ]

    organizer = f"ORGANIZER;CN={_escape(organizer_name)}:mailto:{organizer_email}" if organizer_name else f"ORGANIZER:mailto:{organizer_email}"
    lines.append(organizer)

    if attendee_email:
        # RSVP=TRUE asks the client to offer Accept/Decline. Without PARTSTAT
        # the invitation shows as needing an answer, which is what we want: the
        # lead confirming is information the agent does not otherwise get.
        cn = f";CN={_escape(attendee_name)}" if attendee_name else ""
        lines.append(
            f"ATTENDEE{cn};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{attendee_email}"
        )

    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")

    lines += ["END:VEVENT", "END:VCALENDAR"]

    # CRLF between lines and a trailing CRLF: some parsers drop a final line
    # that is not terminated, which would take END:VCALENDAR with it.
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"

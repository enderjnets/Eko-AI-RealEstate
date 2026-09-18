"""A call where nobody spoke must not arrive wearing a name and a story.

Written on 18-sep-2026 from a real call, not from a worry. The owner rang the
agency's own number to check that Clara answers. She did, he hung up after
three seconds, and the Telegram notice that arrived said:

    Name: Clara Natalia
    Summary: The call was initiated by AI Clara Natalia. The call ended
             because the customer terminated it.

Both lines are false, and neither was written by this repo. There was no
transcript, so VAPI's extractor filled `analysis.structuredData.name` with the
only name in the conversation — **the assistant's own** — and its summariser
described an INBOUND call as one the AI had placed. `parse_end_of_call_report`
stored what the vendor said, faithfully.

The cost is not cosmetic. `conversation.py` copies `from_name` onto the lead,
so every caller who hangs up early is filed under the assistant's name; several
of them are indistinguishable rows in the inbox. And the summary is the first
line a person reads when deciding whether to ring back.

**The rule needs no threshold in seconds**, which matters — a number picked by
eye is how this repo has been wrong before. The transcript already carries
roles. If it is there and holds not one turn from the caller, the caller said
nothing, and any name or summary drawn from that silence is invention. What
stays is what makes the call worth returning: the number, the duration, the
reason it ended.

The other direction is asserted just as hard. A rule that quietly grew until it
threw away real callers' names would be worse than the bug it replaced.
"""

from __future__ import annotations

import pytest

from app.services.voice import parse_end_of_call_report

#: A test number, never a real one — this file is committed.
CALLER = "+13035550147"

#: The three seconds that produced the bad notice, in the shape VAPI sends.
LO_QUE_DIJO_VAPI = {
    "summary": (
        "The call was initiated by AI Clara Natalia. The call ended because "
        "the customer terminated it."
    ),
    "structuredData": {"name": "Clara Natalia"},
}


def _muda() -> dict:
    """The real call: Clara greeted, the caller hung up, transcript present."""
    return {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": "call_silent", "customer": {"number": CALLER}},
            "durationSeconds": 3,
            "endedReason": "customer-ended-call",
            "artifact": {
                "messages": [
                    {"role": "bot", "message": "Denver Home Story, this is Clara."},
                ]
            },
            "analysis": dict(LO_QUE_DIJO_VAPI),
        }
    }


def _hablada() -> dict:
    """The same call if the caller had actually said something."""
    payload = _muda()
    payload["message"]["durationSeconds"] = 94
    payload["message"]["artifact"]["messages"].append(
        {"role": "user", "message": "I'm thinking about selling my place in Wash Park."}
    )
    payload["message"]["analysis"] = {
        "summary": "Caller is considering selling a home in Washington Park.",
        "structuredData": {"name": "Dana Ruiz"},
    }
    return payload


# ── The silence ──────────────────────────────────────────────────────────


def test_the_assistants_name_does_not_become_the_callers() -> None:
    """The exact defect, in the exact payload that caused it."""
    report = parse_end_of_call_report(_muda())
    assert report is not None
    assert report.from_name is None, (
        f"the lead would be filed as {report.from_name!r} — the assistant's own name"
    )


def test_a_summary_of_a_conversation_that_never_happened_is_dropped() -> None:
    report = parse_end_of_call_report(_muda())
    assert report is not None
    assert report.summary is None, (
        "the vendor's model described an inbound call as one the AI placed, and "
        "that sentence would be the first thing a person read"
    )


def test_the_silence_is_recorded_as_a_fact_not_inferred_later() -> None:
    """Downstream has to be able to SAY what happened, not guess from a blank."""
    report = parse_end_of_call_report(_muda())
    assert report is not None
    assert report.caller_spoke is False


def test_the_whole_extraction_goes_not_just_the_name() -> None:
    """The second door, found by a test rather than by reading.

    `_apply_voice_structured` copies `structuredData` onto the lead. Clearing
    `from_name` alone left the assistant's name walking back on through there —
    and with it an intent, a zone and a budget read out of the same silence.
    """
    payload = _muda()
    payload["message"]["analysis"]["structuredData"] = {
        "name": "Clara Natalia",
        "intent": "sell",
        "zone": "Washington Park",
    }
    report = parse_end_of_call_report(payload)
    assert report is not None
    assert report.structured == {}, (
        f"these would be written onto the lead: {report.structured}"
    )


def test_what_makes_the_call_worth_returning_survives() -> None:
    """The point of keeping the lead at all: somebody dialled this number.

    If the cleanup took these with it, the fix would have destroyed more than
    the bug did — the bug produced a badly-named lead, and this would produce
    no lead worth ringing.
    """
    report = parse_end_of_call_report(_muda())
    assert report is not None
    assert report.from_identifier == CALLER
    assert report.duration_seconds == 3
    assert report.ended_reason == "customer-ended-call"


# ── The other direction, asserted just as hard ───────────────────────────


def test_a_caller_who_spoke_keeps_their_name_and_their_summary() -> None:
    """The rule must stay narrow. This is the test that keeps it there."""
    report = parse_end_of_call_report(_hablada())
    assert report is not None
    assert report.from_name == "Dana Ruiz"
    assert report.summary == "Caller is considering selling a home in Washington Park."
    assert report.caller_spoke is True


def test_a_report_with_no_transcript_at_all_is_left_alone() -> None:
    """Absent and empty are different facts, and only one of them is evidence.

    Some reports arrive without any transcript array. That says nothing about
    whether the caller spoke, so throwing the name away there would discard a
    real person's details on the strength of a field the vendor happened not to
    send.
    """
    payload = _muda()
    del payload["message"]["artifact"]
    report = parse_end_of_call_report(payload)
    assert report is not None
    assert report.caller_spoke is None
    assert report.from_name == "Clara Natalia"
    assert report.summary is not None


@pytest.mark.parametrize("vacio", [[], [{"role": "system", "message": "You are Clara."}]])
def test_a_transcript_with_no_human_turn_at_all_counts_as_silence(vacio: list) -> None:
    """An empty list, and a list holding only turns that are not the transcript.

    `system` turns are dropped before this rule looks, so a report carrying
    nothing but instructions has to read as silence rather than as a
    conversation whose name can be trusted.
    """
    payload = _muda()
    payload["message"]["artifact"]["messages"] = vacio
    report = parse_end_of_call_report(payload)
    assert report is not None
    assert report.caller_spoke is False
    assert report.from_name is None

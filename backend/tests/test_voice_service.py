"""Voice service (VAPI): secret verification + end-of-call parsing + tool calls."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.voice import (
    _parse_dt,
    handle_tool_call,
    parse_end_of_call_report,
    verify_vapi_secret,
)


class _FakeResult:
    def scalar_one_or_none(self):
        return None  # no AgentSettings row → office tz falls back to UTC


class _FakeDB:
    """Minimal async DB stub for the guard-path tool tests (no real settings row)."""

    async def execute(self, *args, **kwargs):
        return _FakeResult()

    async def rollback(self):
        pass


# ── Secret ───────────────────────────────────────────────────────────────


def test_verify_vapi_secret_accepts_match() -> None:
    assert verify_vapi_secret("s3cr3t", "s3cr3t") is True


def test_verify_vapi_secret_rejects_mismatch() -> None:
    assert verify_vapi_secret("wrong", "s3cr3t") is False


def test_verify_vapi_secret_rejects_empty() -> None:
    assert verify_vapi_secret(None, "s3cr3t") is False
    assert verify_vapi_secret("s3cr3t", "") is False


# ── End-of-call report parsing ─────────────────────────────────────────────


def _eocr(phone: str = "+13035551234") -> dict:
    return {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": "call_abc", "customer": {"number": phone}},
            "artifact": {
                "messages": [
                    {"role": "system", "message": "You are Eko."},
                    {"role": "bot", "message": "Are you looking to buy, rent, or sell?"},
                    {"role": "user", "message": "Buy a 3BR in Aurora under 600k"},
                    {"role": "bot", "message": "Great, I can help with that."},
                ]
            },
            "analysis": {
                "summary": "Caller wants to buy in Aurora.",
                "structuredData": {
                    "intent": "buy",
                    "zone": "Aurora",
                    "budget_max": 600000,
                    "property_type": "house",
                    "name": "Jordan",
                },
            },
        }
    }


def test_parse_end_of_call_report_full() -> None:
    report = parse_end_of_call_report(_eocr())
    assert report is not None
    assert report.call_id == "call_abc"
    assert report.from_identifier == "+13035551234"
    assert report.from_name == "Jordan"
    assert report.summary == "Caller wants to buy in Aurora."
    # system turn dropped; bot→agent, user→user, order preserved
    assert report.turns == [
        ("agent", "Are you looking to buy, rent, or sell?"),
        ("user", "Buy a 3BR in Aurora under 600k"),
        ("agent", "Great, I can help with that."),
    ]
    assert report.structured["intent"] == "buy"


def test_parse_end_of_call_report_web_call_has_no_number() -> None:
    payload = _eocr()
    payload["message"]["call"]["customer"] = {}
    report = parse_end_of_call_report(payload)
    assert report is not None
    assert report.from_identifier == "voice:call_abc"


def test_parse_end_of_call_report_without_call_id_returns_none() -> None:
    payload = {"message": {"type": "end-of-call-report", "call": {}}}
    assert parse_end_of_call_report(payload) is None


def test_parse_end_of_call_report_tolerates_unwrapped_payload() -> None:
    # Some integrations post the message dict directly (not under "message").
    payload = _eocr()["message"]
    report = parse_end_of_call_report(payload)
    assert report is not None and report.call_id == "call_abc"


# ── Tool calls ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_check_availability_returns_slots_text() -> None:
    # CALENDAR_SIMULATED defaults to true → list_available_slots needs no Cal.com.
    out = await handle_tool_call(
        "check_availability", {"days": 7}, customer_number=None, db=_FakeDB()
    )
    assert "available" in out.lower()


@pytest.mark.asyncio
async def test_tool_book_visit_rejects_bad_datetime() -> None:
    out = await handle_tool_call(
        "book_visit", {"datetime": "tomorrow-ish"}, customer_number="+13035551234", db=_FakeDB()
    )
    assert "date and time" in out.lower()


@pytest.mark.asyncio
async def test_tool_book_visit_needs_phone() -> None:
    out = await handle_tool_call(
        "book_visit", {"datetime": "2027-01-15T15:00:00Z"}, customer_number=None, db=_FakeDB()
    )
    assert "phone number" in out.lower()


@pytest.mark.asyncio
async def test_tool_unknown_returns_graceful_message() -> None:
    out = await handle_tool_call("do_a_backflip", {}, customer_number=None, db=_FakeDB())
    assert "not able" in out.lower()


# ── Timezone: a spoken local time is stored as office-local → UTC ───────────


def test_parse_dt_interprets_wall_clock_as_office_local() -> None:
    # "2 PM" in America/Denver (UTC-6 in June / MDT) → 20:00 UTC, NOT 14:00 UTC.
    out = _parse_dt("2026-06-03T14:00:00", ZoneInfo("America/Denver"))
    assert out == datetime(2026, 6, 3, 20, 0, tzinfo=UTC)


def test_parse_dt_ignores_llm_supplied_z_suffix() -> None:
    # Even if the LLM appends Z, the wall-clock is interpreted as office-local.
    out = _parse_dt("2026-06-03T14:00:00Z", ZoneInfo("America/Denver"))
    assert out == datetime(2026, 6, 3, 20, 0, tzinfo=UTC)


def test_parse_dt_bad_value_returns_none() -> None:
    assert _parse_dt("tomorrow-ish", ZoneInfo("UTC")) is None


# ── structuredData mapping (flat + VAPI's nested auto-shape) ────────────────


def test_apply_voice_structured_nested_shape() -> None:
    from app.models import Lead, LeadIntent
    from app.services.conversation import _apply_voice_structured

    lead = Lead(phone="+13035551234")
    nested = {
        "customer_info": {"name": "Margie Quintero", "phone_number": "7208387940"},
        "property_inquiry": {
            "inquiry_type": "rent",
            "location": "DTC",
            "budget_max": "2000",
            "bedrooms": "2",
            "move_in_timeline": "2 months",
        },
    }
    _apply_voice_structured(lead, nested)
    assert lead.intent == LeadIntent.RENT
    assert lead.zone == "DTC"
    assert lead.budget_max == 2000
    assert lead.name == "Margie Quintero"
    assert lead.urgency == "2 months"


def test_apply_voice_structured_flat_shape() -> None:
    from app.models import Lead, LeadIntent
    from app.services.conversation import _apply_voice_structured

    lead = Lead(phone="x")
    _apply_voice_structured(
        lead, {"intent": "buy", "zone": "Brickell", "budget_max": 800000, "name": "Jo"}
    )
    assert lead.intent == LeadIntent.BUY
    assert lead.zone == "Brickell"
    assert lead.budget_max == 800000
    assert lead.name == "Jo"


# ── What a call cost and how it ended ────────────────────────────────────────
#
# The field names here are not invented: they were read off two real VAPI calls
# on 4-sep-2026, before a line of this was written. The finding that mattered is
# a negative one — **there is no `durationSeconds`** on the Call object, which
# the plan had assumed there was. Duration is `endedAt - startedAt`, and the two
# real calls give 26.832s and 124.656s.


def _with_call_fields(**over: object) -> dict:
    payload = _eocr()
    payload["message"]["call"].update(
        {
            "startedAt": "2026-08-29T22:29:58.264Z",
            "endedAt": "2026-08-29T22:30:25.096Z",
            "endedReason": "customer-ended-call",
            "cost": 0.0471,
            "recordingUrl": "https://storage.vapi.ai/call_abc.wav",
        }
    )
    payload["message"]["call"].update(over)
    return payload


def test_duration_is_computed_because_vapi_does_not_send_one() -> None:
    report = parse_end_of_call_report(_with_call_fields())
    assert report is not None
    assert report.duration_seconds == pytest.approx(26.832, abs=0.001)
    assert report.ended_reason == "customer-ended-call"
    assert report.cost == pytest.approx(0.0471)
    assert report.recording_url == "https://storage.vapi.ai/call_abc.wav"


def test_the_longer_of_the_two_real_calls() -> None:
    report = parse_end_of_call_report(
        _with_call_fields(
            startedAt="2026-08-29T17:15:07.856Z", endedAt="2026-08-29T17:17:12.512Z"
        )
    )
    assert report is not None
    assert report.duration_seconds == pytest.approx(124.656, abs=0.001)


def test_an_explicit_duration_wins_over_the_subtraction() -> None:
    """If VAPI ever starts sending one, believe it: they know about the parts
    of a call that are not between those two timestamps."""
    report = parse_end_of_call_report(_with_call_fields(durationSeconds=42))
    assert report is not None and report.duration_seconds == 42.0


def test_a_call_with_none_of_it_still_ingests() -> None:
    """The whole point of the try. A payload with no timing at all is the
    shape every fixture in this file had until today, and it must keep
    producing a transcript."""
    report = parse_end_of_call_report(_eocr())
    assert report is not None
    assert report.turns, "the transcript is what must never be lost"
    assert report.duration_seconds is None
    assert report.ended_reason is None


def test_garbage_in_the_timing_fields_does_not_cost_us_the_call() -> None:
    report = parse_end_of_call_report(
        _with_call_fields(startedAt="not a date", endedAt=None, cost="free")
    )
    assert report is not None
    assert report.turns
    assert (report.duration_seconds, report.cost) == (None, None)


def test_a_duration_of_the_wrong_sign_is_dropped_not_stored() -> None:
    """Clocks disagree. A negative call length would poison an average and
    look like a real number in a report."""
    report = parse_end_of_call_report(
        _with_call_fields(
            startedAt="2026-08-29T22:30:25.096Z", endedAt="2026-08-29T22:29:58.264Z"
        )
    )
    assert report is not None and report.duration_seconds is None

"""Voice service (VAPI): secret verification + end-of-call parsing + tool calls."""
from __future__ import annotations

import pytest

from app.services.voice import (
    handle_tool_call,
    parse_end_of_call_report,
    verify_vapi_secret,
)

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
    # CALENDAR_SIMULATED defaults to true → list_available_slots needs no Cal.com,
    # and this branch never touches the DB.
    out = await handle_tool_call("check_availability", {"days": 7}, customer_number=None, db=None)
    assert "available" in out.lower()


@pytest.mark.asyncio
async def test_tool_book_visit_rejects_bad_datetime() -> None:
    out = await handle_tool_call(
        "book_visit", {"datetime": "tomorrow-ish"}, customer_number="+13035551234", db=None
    )
    assert "date and time" in out.lower()


@pytest.mark.asyncio
async def test_tool_book_visit_needs_phone() -> None:
    out = await handle_tool_call(
        "book_visit", {"datetime": "2027-01-15T15:00:00Z"}, customer_number=None, db=None
    )
    assert "phone number" in out.lower()


@pytest.mark.asyncio
async def test_tool_unknown_returns_graceful_message() -> None:
    out = await handle_tool_call("do_a_backflip", {}, customer_number=None, db=None)
    assert "not able" in out.lower()


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

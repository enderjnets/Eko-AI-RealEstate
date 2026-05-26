"""Tests for the SMS service — Twilio signature, inbound parse, simulated send."""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from app.services.sms import (
    parse_inbound_sms,
    send_sms,
    twilio_status_to_delivery,
    verify_twilio_signature,
)

_TOKEN = "test_auth_token_xyz"
_URL = "https://inmo-demo.ekoaiautomation.com/api/v1/webhooks/sms"
_PARAMS = {"From": "+13055550123", "To": "+13055559999", "Body": "Hola", "MessageSid": "SM123"}


def _sign(url: str, params: dict[str, str], token: str) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_signature_valid() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert verify_twilio_signature(_URL, _PARAMS, sig, auth_token=_TOKEN) is True


def test_signature_rejects_tampered_body() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    tampered = dict(_PARAMS, Body="Te hackeo")
    assert verify_twilio_signature(_URL, tampered, sig, auth_token=_TOKEN) is False


def test_signature_rejects_wrong_token() -> None:
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert verify_twilio_signature(_URL, _PARAMS, sig, auth_token="other_token") is False


def test_signature_missing_inputs_false() -> None:
    assert verify_twilio_signature(_URL, _PARAMS, None, auth_token=_TOKEN) is False
    assert verify_twilio_signature(_URL, _PARAMS, "x", auth_token="") is False


def test_parse_inbound_sms_ok() -> None:
    parsed = parse_inbound_sms(
        {"MessageSid": "SMabc", "From": "+13055550123", "To": "+1305", "Body": "  busco casa  "}
    )
    assert parsed is not None
    assert parsed.channel == "sms"
    assert parsed.external_id == "SMabc"
    assert parsed.from_identifier == "+13055550123"
    assert parsed.content == "busco casa"  # trimmed
    assert parsed.from_name is None


def test_parse_inbound_sms_missing_fields_none() -> None:
    assert parse_inbound_sms({"Body": "hola"}) is None
    assert parse_inbound_sms({"MessageSid": "SM1"}) is None


@pytest.mark.asyncio
async def test_send_sms_simulated_returns_sid() -> None:
    """Default config has SMS_SIMULATED=true → no network, synthetic sid."""
    result = await send_sms(to="+13055550123", body="Hola desde Eko")
    assert result["simulated"] is True
    assert result["sid"].startswith("SM_SIMULATED_")


def test_twilio_status_mapping() -> None:
    assert twilio_status_to_delivery("delivered") == "delivered"
    assert twilio_status_to_delivery("undelivered") == "failed"
    assert twilio_status_to_delivery("failed") == "failed"
    assert twilio_status_to_delivery("sent") == "sent"
    assert twilio_status_to_delivery("queued") == "pending"
    assert twilio_status_to_delivery("DELIVERED") == "delivered"  # case-insensitive
    assert twilio_status_to_delivery("bogus") is None

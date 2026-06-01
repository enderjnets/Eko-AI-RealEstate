"""Email service: signature verification + payload parsing + send (SIMULATED)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

import pytest

from app.services.email import (
    _strip_quoted_reply,
    parse_inbound_email,
    send_email,
    verify_resend_signature,
)


def test_strip_quoted_reply_gmail_attribution() -> None:
    # Gmail appends "On <date> … wrote:" + quoted ">" history below the new text.
    raw = (
        "Do you speak English?\n\n"
        "On Mon, Jun 1, 2026 at 7:33 AM Eko AI Realtors <\n"
        "noreply@realtors.ekoaiautomation.com> wrote:\n"
        "> Hola! Claro que si...\n"
    )
    assert _strip_quoted_reply(raw) == "Do you speak English?"


def test_strip_quoted_reply_noop_without_quotes() -> None:
    clean = "Hola, busco un condo en Centennial bajo 500k."
    assert _strip_quoted_reply(clean) == clean


SECRET_BASE64 = base64.b64encode(b"test-secret-bytes-32-chars-aaaaaa").decode("ascii")
SECRET = f"whsec_{SECRET_BASE64}"


def _sign(body: bytes, svix_id: str, svix_timestamp: str, secret: str) -> str:
    key_material = secret.removeprefix("whsec_")
    key = base64.b64decode(key_material)
    signed = f"{svix_id}.{svix_timestamp}.{body.decode('utf-8')}".encode("utf-8")
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")
    return f"v1,{sig}"


# ── Signature ──────────────────────────────────────────────────────────


def test_valid_signature_accepts() -> None:
    body = b'{"type":"email.received","data":{}}'
    sig = _sign(body, "msg_123", "1735066800", SECRET)
    assert verify_resend_signature(
        body, svix_id="msg_123", svix_timestamp="1735066800",
        svix_signature=sig, secret=SECRET,
    ) is True


def test_invalid_signature_rejects() -> None:
    body = b'{"type":"email.received","data":{}}'
    assert verify_resend_signature(
        body, svix_id="msg_123", svix_timestamp="1735066800",
        svix_signature="v1,deadbeef" + "A" * 40,
        secret=SECRET,
    ) is False


def test_missing_headers_reject() -> None:
    body = b"{}"
    assert verify_resend_signature(body, svix_id=None, svix_timestamp="1", svix_signature="x", secret=SECRET) is False
    assert verify_resend_signature(body, svix_id="a", svix_timestamp=None, svix_signature="x", secret=SECRET) is False
    assert verify_resend_signature(body, svix_id="a", svix_timestamp="1", svix_signature=None, secret=SECRET) is False


def test_missing_secret_rejects() -> None:
    body = b"{}"
    sig = _sign(body, "msg_1", "1", SECRET)
    assert verify_resend_signature(body, svix_id="msg_1", svix_timestamp="1", svix_signature=sig, secret="") is False


def test_multiple_signatures_in_header_one_matches() -> None:
    body = b'{"type":"email.received","data":{}}'
    valid = _sign(body, "msg_123", "1735066800", SECRET)
    multi = f"v1,decoyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= {valid}"
    assert verify_resend_signature(
        body, svix_id="msg_123", svix_timestamp="1735066800",
        svix_signature=multi, secret=SECRET,
    ) is True


# ── Parser ─────────────────────────────────────────────────────────────


def test_parse_minimal_text_email() -> None:
    payload = {
        "type": "email.received",
        "data": {
            "id": "resend_abc",
            "from": "juan@example.com",
            "to": ["info@realtor-demo.com"],
            "subject": "Consulta piso Madrid",
            "text": "Hola, busco piso en Malasaña",
            "headers": {"message-id": "<msg-001@example.com>"},
        },
    }
    out = parse_inbound_email(payload)
    assert len(out) == 1
    m = out[0]
    assert m.channel == "email"
    assert m.external_id == "<msg-001@example.com>"
    assert m.from_identifier == "juan@example.com"
    assert m.subject == "Consulta piso Madrid"
    assert "Malasaña" in m.content
    assert m.thread_id == "<msg-001@example.com>"


def test_parse_threading_uses_in_reply_to() -> None:
    payload = {
        "type": "email.received",
        "data": {
            "from": "juan@example.com",
            "subject": "Re: Consulta piso Madrid",
            "text": "Sí, me interesa visitar",
            "headers": {
                "message-id": "<msg-002@example.com>",
                "in-reply-to": "<msg-001@example.com>",
                "references": "<msg-001@example.com>",
            },
        },
    }
    out = parse_inbound_email(payload)
    assert len(out) == 1
    assert out[0].thread_id == "<msg-001@example.com>"


def test_parse_html_fallback_when_no_text() -> None:
    payload = {
        "type": "email.received",
        "data": {
            "from": "juan@example.com",
            "subject": "x",
            "html": "<p>Hola, busco <b>piso</b></p>",
            "headers": {"message-id": "<x@e>"},
        },
    }
    out = parse_inbound_email(payload)
    assert len(out) == 1
    assert "Hola, busco piso" in out[0].content


def test_parse_ignores_non_received_events() -> None:
    payload = {"type": "email.delivered", "data": {"id": "x"}}
    assert parse_inbound_email(payload) == []


def test_parse_skips_missing_from() -> None:
    payload = {"type": "email.received", "data": {"subject": "x"}}
    assert parse_inbound_email(payload) == []


# ── Send (SIMULATED mode) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_email_simulated_returns_fake_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_SIMULATED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    result = await send_email(
        to="juan@example.com",
        subject="Re: tu consulta",
        body_text="Hola Juan, gracias por escribirnos.",
        in_reply_to="<msg-001@example.com>",
    )
    assert result["simulated"] is True
    assert result["id"].startswith("resend.SIMULATED_")

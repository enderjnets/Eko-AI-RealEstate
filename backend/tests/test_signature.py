"""HMAC-SHA256 signature verification for the WhatsApp inbound webhook."""
from __future__ import annotations

import hashlib
import hmac

from app.services.whatsapp import verify_signature

SECRET = "test-app-secret-do-not-use-in-prod"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_accepts() -> None:
    assert verify_signature(BODY, _sign(BODY, SECRET), SECRET) is True


def test_invalid_signature_rejects() -> None:
    assert verify_signature(BODY, "sha256=deadbeef" + "00" * 30, SECRET) is False


def test_missing_signature_rejects() -> None:
    assert verify_signature(BODY, None, SECRET) is False
    assert verify_signature(BODY, "", SECRET) is False


def test_missing_secret_rejects() -> None:
    """Empty app secret should reject everything (avoid false positives)."""
    assert verify_signature(BODY, _sign(BODY, SECRET), "") is False


def test_wrong_prefix_rejects() -> None:
    sig = _sign(BODY, SECRET).replace("sha256=", "sha1=")
    assert verify_signature(BODY, sig, SECRET) is False


def test_body_tampering_rejects() -> None:
    """Sign one body, verify against modified body — must reject."""
    tampered = BODY + b' tampered'
    assert verify_signature(tampered, _sign(BODY, SECRET), SECRET) is False


def test_secret_mismatch_rejects() -> None:
    """Signature made with the wrong secret must reject."""
    assert verify_signature(BODY, _sign(BODY, "wrong-secret"), SECRET) is False

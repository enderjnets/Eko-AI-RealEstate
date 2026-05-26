"""Dashboard auth — a single shared password + an HMAC-signed session token.

One deploy = one inmobiliaria, so we don't need user accounts: the office sets a
single `DASHBOARD_PASSWORD`. On login we issue a compact HMAC-SHA256 signed token
(`payload.signature`, like a tiny JWT — no extra dependency) stored in an
httpOnly cookie. `require_auth` (gated by `AUTH_ENABLED`) protects the data API.

The signing secret is `AUTH_SECRET` if set, else derived from the password — so
tokens stay valid across restarts as long as the password is unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import get_settings

COOKIE_NAME = "eko_auth"
_SUBJECT = "dashboard"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _secret() -> bytes:
    s = get_settings()
    material = s.AUTH_SECRET or f"eko-auth::{s.DASHBOARD_PASSWORD}"
    return hashlib.sha256(material.encode("utf-8")).digest()


def check_password(password: str) -> bool:
    """Constant-time compare against DASHBOARD_PASSWORD (False if none set)."""
    expected = get_settings().DASHBOARD_PASSWORD
    if not expected:
        return False
    return hmac.compare_digest(password or "", expected)


def make_token(*, ttl_hours: int | None = None) -> str:
    s = get_settings()
    ttl = ttl_hours if ttl_hours is not None else s.AUTH_TTL_HOURS
    payload = {"sub": _SUBJECT, "exp": int(time.time()) + ttl * 3600}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    return f"{payload_b64}.{sig}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload_b64, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload = json.loads(_b64d(payload_b64))
    except Exception:
        return False
    if payload.get("sub") != _SUBJECT:
        return False
    return int(payload.get("exp", 0)) > int(time.time())

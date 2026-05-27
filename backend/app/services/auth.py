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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

COOKIE_NAME = "eko_auth"
_SUBJECT = "dashboard"

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


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


def make_token(
    *, email: str | None = None, role: str = ROLE_ADMIN, ttl_hours: int | None = None
) -> str:
    """Mint a signed session token carrying identity (email) + role.

    Password login mints `role=admin` (master key, no email). Google login mints
    the email + the role resolved from the access list.
    """
    s = get_settings()
    ttl = ttl_hours if ttl_hours is not None else s.AUTH_TTL_HOURS
    payload: dict = {"sub": _SUBJECT, "exp": int(time.time()) + ttl * 3600, "role": role}
    if email:
        payload["email"] = email
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    return f"{payload_b64}.{sig}"


def decode_token(token: str | None) -> dict | None:
    """Return the verified payload (sig + sub + exp ok), else None."""
    if not token or "." not in token:
        return None
    payload_b64, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(payload_b64))
    except Exception:
        return None
    if payload.get("sub") != _SUBJECT:
        return None
    if int(payload.get("exp", 0)) <= int(time.time()):
        return None
    return payload


def verify_token(token: str | None) -> bool:
    return decode_token(token) is not None


def token_role(token: str | None) -> str | None:
    """The role carried by a valid token, or None if invalid.

    Legacy tokens minted before roles existed have no `role` field — they were
    only ever the password/master session, so they resolve to admin.
    """
    payload = decode_token(token)
    if payload is None:
        return None
    return payload.get("role", ROLE_ADMIN)


# ─── Google Sign In (Google Identity Services) ──────────────────────────
# verify_google_id_token only validates the token (signature + aud +
# email_verified) and returns the verified email. The allow-list / role
# decision is DB-aware and lives in resolve_email_access below.

class GoogleAuthError(Exception):
    """Raised when Google ID token verification fails."""


def verify_google_id_token(id_token_str: str) -> str:
    """Validate a Google-issued ID token; return the verified email.

    Checks the signature against Google's public keys, that `aud` matches
    GOOGLE_CLIENT_ID, and that the email is verified. Raises GoogleAuthError
    otherwise. Whether the email may log in (and as what role) is decided by
    resolve_email_access.
    """
    s = get_settings()
    if not s.GOOGLE_CLIENT_ID:
        raise GoogleAuthError("google_signin_not_configured")
    if not id_token_str:
        raise GoogleAuthError("missing_id_token")

    # Import lazily so the dep is only required when the feature is used.
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError as e:
        raise GoogleAuthError(f"google_auth_library_missing: {e}") from e

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            s.GOOGLE_CLIENT_ID,
        )
    except ValueError as e:
        raise GoogleAuthError(f"invalid_id_token: {e}") from e

    if not claims.get("email_verified"):
        raise GoogleAuthError("email_not_verified")
    email = (claims.get("email") or "").lower().strip()
    if not email:
        raise GoogleAuthError("missing_email")
    return email


async def resolve_email_access(email: str, db: AsyncSession) -> str | None:
    """Return the role ('admin' | 'member') a verified email may log in as, or
    None to deny (safe default).

    Provider-agnostic: the same access list governs Google and Apple sign-in —
    the office's allow-list is keyed on the email, not on who issued the token.

    Precedence:
      1. env GOOGLE_ADMIN_EMAILS  → admin (always; immutable bootstrap).
      2. allowed_users DB row     → its role.
      3. env GOOGLE_ALLOWED_EMAILS→ member (back-compat static allow).
      4. env GOOGLE_ALLOWED_DOMAIN→ member (any @domain).
      5. otherwise                → None.
    """
    from app.models import AllowedUser

    s = get_settings()
    email = (email or "").lower().strip()
    if not email:
        return None
    if email in s.google_admin_emails_list:
        return ROLE_ADMIN
    row = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == email))
    ).scalar_one_or_none()
    if row is not None:
        return ROLE_ADMIN if row.role == ROLE_ADMIN else ROLE_MEMBER
    if email in s.google_allowed_emails_list:
        return ROLE_MEMBER
    domain = (s.GOOGLE_ALLOWED_DOMAIN or "").lower().strip()
    if domain and email.endswith("@" + domain):
        return ROLE_MEMBER
    return None


# Back-compat alias (Google-era name); role resolution is provider-agnostic.
resolve_google_access = resolve_email_access


# ─── Sign in with Apple ─────────────────────────────────────────────────
# verify_apple_id_token only validates Apple's identity token (RS256 signature
# against Apple's public keys + iss + aud + exp) and returns the verified email.
# Whether that email may log in (and as what role) is decided by
# resolve_email_access — the same allow-list as Google.

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

_apple_jwk_client = None  # lazy PyJWKClient — caches Apple's public keys


class AppleAuthError(Exception):
    """Raised when Apple identity token verification fails."""


def _get_apple_jwk_client():
    global _apple_jwk_client
    if _apple_jwk_client is None:
        from jwt import PyJWKClient

        _apple_jwk_client = PyJWKClient(APPLE_KEYS_URL)
    return _apple_jwk_client


def verify_apple_id_token(id_token_str: str) -> str:
    """Validate an Apple-issued identity token; return the verified email.

    Checks the RS256 signature against the matching key from
    appleid.apple.com/auth/keys, that `iss` is Apple, `aud` matches
    APPLE_CLIENT_ID (the Services ID), the token hasn't expired, and that the
    email is verified. Raises AppleAuthError otherwise.
    """
    s = get_settings()
    if not s.APPLE_CLIENT_ID:
        raise AppleAuthError("apple_signin_not_configured")
    if not id_token_str:
        raise AppleAuthError("missing_id_token")

    # Import lazily so the dep is only required when the feature is used.
    try:
        import jwt
    except ImportError as e:
        raise AppleAuthError(f"pyjwt_library_missing: {e}") from e

    try:
        signing_key = _get_apple_jwk_client().get_signing_key_from_jwt(id_token_str)
        claims = jwt.decode(
            id_token_str,
            signing_key.key,
            algorithms=["RS256"],
            audience=s.APPLE_CLIENT_ID,
            issuer=APPLE_ISSUER,
        )
    except Exception as e:
        raise AppleAuthError(f"invalid_id_token: {e}") from e

    # email_verified may arrive as a bool or the string "true" depending on the
    # token version; accept both.
    if claims.get("email_verified") not in (True, "true"):
        raise AppleAuthError("email_not_verified")
    email = (claims.get("email") or "").lower().strip()
    if not email:
        raise AppleAuthError("missing_email")
    return email

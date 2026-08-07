"""Dashboard auth — session tokens that carry identity, role AND organization.

On login we issue a compact HMAC-SHA256 signed token (`payload.signature`, like
a tiny JWT — no extra dependency) in an httpOnly cookie. `require_auth` (gated
by `AUTH_ENABLED`) protects the data API.

The `org` claim is the one that matters most: it is the only channel that tells
the request which tenant it acts for, and `db/base.py` stamps it onto every
transaction for the RLS policies to read. A token without a usable org is
rejected rather than defaulted — defaulting it is how every user once ended up
inside client zero's data.

`DASHBOARD_PASSWORD` remains the operator's master key. The signing secret is
`AUTH_SECRET` if set, else derived from the password; with neither set and auth
enabled, minting refuses rather than signing with a key published in this repo.
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
# Read-only demo accounts (self-registered with email + password). They can view
# the whole dashboard but cannot mutate anything — enforced in require_auth.
ROLE_VIEWER = "viewer"

# HTTP methods a viewer (read-only) may use on the protected data API.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


# ─── Password hashing for self-registered accounts (stdlib PBKDF2) ──────────
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 (stdlib, no extra dependency).

    Format: `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`."""
    import os

    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify a password against a `hash_password` digest."""
    try:
        algo, iters, salt_b64, hash_b64 = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"), _b64d(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, _b64d(hash_b64))
    except (ValueError, TypeError):
        return False


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class InsecureAuthConfig(RuntimeError):
    """Auth is on but nothing secret is configured to sign sessions with."""


def _secret() -> bytes:
    s = get_settings()
    material = s.AUTH_SECRET or (
        f"eko-auth::{s.DASHBOARD_PASSWORD}" if s.DASHBOARD_PASSWORD else ""
    )
    if not material:
        # With both unset the key used to be sha256("eko-auth::") — a constant
        # anyone can derive from this repository, so a session token could be
        # forged naming any role AND any organization, which under multi-tenancy
        # means reading any client agency's data. Reachable in the documented
        # Google-Sign-In-only setup, where an operator has no reason to set
        # DASHBOARD_PASSWORD. Refusing is the only safe answer; the installer
        # already generates a random AUTH_SECRET.
        if s.AUTH_ENABLED:
            raise InsecureAuthConfig(
                "AUTH_ENABLED is true but neither AUTH_SECRET nor DASHBOARD_PASSWORD "
                "is set — session tokens would be signed with a key published in "
                "this repository. Set AUTH_SECRET to a random value."
            )
        # Auth off: tokens are not a security boundary anyway (require_auth is a
        # no-op), so a fixed dev key is fine and keeps local work frictionless.
        material = "eko-auth::insecure-dev-only"
    return hashlib.sha256(material.encode("utf-8")).digest()


def check_password(password: str) -> bool:
    """Constant-time compare against DASHBOARD_PASSWORD (False if none set)."""
    expected = get_settings().DASHBOARD_PASSWORD
    if not expected:
        return False
    return hmac.compare_digest(password or "", expected)


def make_token(
    *,
    email: str | None = None,
    role: str = ROLE_ADMIN,
    ttl_hours: int | None = None,
    org_id: int | None = None,
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
    # Tokens minted before multi-tenancy carry no org and resolve to DEFAULT_ORG_ID
    # in current_org_id(); that keeps existing sessions working through the deploy
    # instead of logging everyone out.
    if org_id is not None:
        payload["org"] = org_id
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


def token_org_id(token: str | None) -> int | None:
    """The organization a valid token acts for, or None if the token is invalid.

    Tokens minted before multi-tenancy carry no `org`; they resolve to the
    default org so sessions open across the deploy keep working rather than
    every user being silently logged out.
    """
    data = decode_token(token)
    if data is None:
        return None
    from app.models.organization import DEFAULT_ORG_ID

    org = data.get("org")
    # `isinstance(True, int)` is True in Python, and a string or float claim
    # would silently fall through to the default org — i.e. into client zero's
    # data. Anything that is not a plain positive int is treated as no org at
    # all, which under default-deny RLS shows nothing rather than the wrong thing.
    if isinstance(org, bool) or not isinstance(org, int):
        return DEFAULT_ORG_ID if org is None else None
    return org if org > 0 else None



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


async def resolve_email_org(email: str, db: AsyncSession) -> int | None:
    """Which organization a verified email belongs to, or None if it has no row.

    Split from resolve_email_access so the caller gets both facts without a
    second query shape to keep in sync. Env-based bootstrap admins
    (GOOGLE_ADMIN_EMAILS) and domain allow-lists have no row and therefore no
    org of their own, so they land in the default org — they are the operator's
    own accounts, not a client agency's.

    MUST be called on a bypass session: at login time there is no org bound yet,
    so an RLS-enforcing session would find nobody and deny every sign-in.
    """
    from app.models import AllowedUser
    from app.models.organization import DEFAULT_ORG_ID

    email = (email or "").lower().strip()
    if not email:
        return None
    # Same precedence as resolve_email_access, deliberately. That one checks the
    # env bootstrap list BEFORE the database; if this one checked the database
    # first, an operator email that a client agency happened to add to their Team
    # would sign in as an admin OF THAT AGENCY instead of the default org.
    if email in get_settings().google_admin_emails_list:
        return DEFAULT_ORG_ID
    row = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == email))
    ).scalar_one_or_none()
    return row.org_id if row is not None else DEFAULT_ORG_ID


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

"""Tests for dashboard auth — token service + login/gate API."""
from __future__ import annotations

import os
import types
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.services import auth as auth_svc


def _fake_settings(**over):
    base = dict(
        AUTH_ENABLED=True,
        DASHBOARD_PASSWORD="s3cret-pass",
        AUTH_SECRET="unit-test-secret",
        AUTH_TTL_HOURS=168,
        is_production=False,
        REGISTRATION_ENABLED=True,
        # Google Sign In (defaults: feature configured, no env allow-list).
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        GOOGLE_ALLOWED_DOMAIN="",
        google_admin_emails_list=[],
        google_allowed_emails_list=[],
        # Platform operators (cross-tenant). Empty by default, which is what
        # keeps the shared password minting `su` for a single-customer install.
        platform_admin_emails_list=[],
        # Sign in with Apple (default: not configured).
        APPLE_CLIENT_ID="",
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — Google access tests need live Postgres")


async def _seed_allowed(email: str, role: str) -> None:
    from app.db.base import get_session_factory
    from app.models import AllowedUser

    Session = get_session_factory()
    async with Session() as s:
        s.add(AllowedUser(email=email, role=role, added_by="test"))
        await s.commit()


async def _clear_allowed(*emails: str) -> None:
    from app.db.base import get_session_factory
    from app.models import AllowedUser

    Session = get_session_factory()
    async with Session() as s:
        await s.execute(delete(AllowedUser).where(AllowedUser.email.in_(emails)))
        await s.commit()


# ── service (pure) ──────────────────────────────────────────────────────────


def test_check_password_and_token_roundtrip() -> None:
    with patch("app.services.auth.get_settings", return_value=_fake_settings()):
        assert auth_svc.check_password("s3cret-pass") is True
        assert auth_svc.check_password("wrong") is False
        token = auth_svc.make_token()
        assert auth_svc.verify_token(token) is True


def test_token_rejects_tamper_and_garbage() -> None:
    with patch("app.services.auth.get_settings", return_value=_fake_settings()):
        token = auth_svc.make_token()
        payload, sig = token.rsplit(".", 1)
        assert auth_svc.verify_token(f"{payload}.AAAA") is False  # bad sig
        assert auth_svc.verify_token(None) is False
        assert auth_svc.verify_token("garbage") is False
    # A token signed with a different secret must not validate.
    with patch("app.services.auth.get_settings", return_value=_fake_settings(AUTH_SECRET="other")):
        assert auth_svc.verify_token(token) is False


def test_token_expires() -> None:
    with patch("app.services.auth.get_settings", return_value=_fake_settings()):
        expired = auth_svc.make_token(ttl_hours=-1)
        assert auth_svc.verify_token(expired) is False


# ── API ───────────────────────────────────────────────────────────────────


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_me_open_when_auth_disabled() -> None:
    """Default config: AUTH_ENABLED=false → everything open."""
    async with await _client() as c:
        r = await c.get("/api/v1/auth/me")
    body = r.json()
    assert body["auth_enabled"] is False
    assert body["authenticated"] is True


@pytest.mark.asyncio
async def test_gate_enforced_when_enabled() -> None:
    fake = _fake_settings()
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake):
        async with await _client() as c:
            # No cookie → protected route 401.
            assert (await c.get("/api/v1/leads")).status_code == 401
            # Wrong password → 401.
            assert (await c.post("/api/v1/auth/login", json={"password": "nope"})).status_code == 401
            # Correct password → cookie set; protected route now works.
            login = await c.post("/api/v1/auth/login", json={"password": "s3cret-pass"})
            assert login.status_code == 200, login.text
            assert "eko_auth" in c.cookies
            assert (await c.get("/api/v1/leads")).status_code == 200


# ── roles ───────────────────────────────────────────────────────────────────


def test_token_carries_role() -> None:
    with patch("app.services.auth.get_settings", return_value=_fake_settings()):
        assert auth_svc.token_role(auth_svc.make_token()) == "admin"  # default = master
        assert auth_svc.token_role(auth_svc.make_token(role="member")) == "member"
        # Legacy token with no role field resolves to admin (only password sessions existed).
        legacy = auth_svc.make_token()
        payload_b64 = legacy.rsplit(".", 1)[0]
        import json as _json
        payload = _json.loads(auth_svc._b64d(payload_b64))
        payload.pop("role")
        raw = auth_svc._b64e(_json.dumps(payload, separators=(",", ":")).encode())
        sig = auth_svc._b64e(
            auth_svc.hmac.new(auth_svc._secret(), raw.encode(), auth_svc.hashlib.sha256).digest()
        )
        assert auth_svc.token_role(f"{raw}.{sig}") == "admin"


def test_verify_google_id_token_transport_deps_present() -> None:
    """Regression guard: google-auth's verifier needs the `requests` transport
    (an optional dep). A malformed token must fail with `invalid_id_token`, NOT
    `google_auth_library_missing` — the latter means a transport dep is absent."""
    fake = _fake_settings(GOOGLE_CLIENT_ID="cid.apps.googleusercontent.com")
    with patch("app.services.auth.get_settings", return_value=fake):
        with pytest.raises(auth_svc.GoogleAuthError) as ei:
            auth_svc.verify_google_id_token("not.a.valid.jwt")
        msg = str(ei.value)
    assert "google_auth_library_missing" not in msg, msg
    assert msg.startswith("invalid_id_token"), msg


def test_verify_apple_id_token_extracts_verified_email() -> None:
    """Happy path: a valid token (mocked JWKS + decode) yields the lowercased
    verified email; email_verified may be the string "true"."""
    fake = _fake_settings(APPLE_CLIENT_ID="com.eko.signin")
    claims = {"email": "User@Eko.com", "email_verified": "true", "sub": "abc"}
    fake_client = types.SimpleNamespace(
        get_signing_key_from_jwt=lambda _t: types.SimpleNamespace(key="pubkey")
    )
    with patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.services.auth._get_apple_jwk_client", return_value=fake_client), \
         patch("jwt.decode", return_value=claims):
        assert auth_svc.verify_apple_id_token("a.b.c") == "user@eko.com"


def test_verify_apple_id_token_rejects_unconfigured_and_unverified() -> None:
    with patch("app.services.auth.get_settings", return_value=_fake_settings(APPLE_CLIENT_ID="")):
        with pytest.raises(auth_svc.AppleAuthError) as ei:
            auth_svc.verify_apple_id_token("x")
        assert "apple_signin_not_configured" in str(ei.value)

    fake = _fake_settings(APPLE_CLIENT_ID="com.eko.signin")
    fake_client = types.SimpleNamespace(
        get_signing_key_from_jwt=lambda _t: types.SimpleNamespace(key="pubkey")
    )
    with patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.services.auth._get_apple_jwk_client", return_value=fake_client), \
         patch("jwt.decode", return_value={"email": "u@eko.com", "email_verified": False}):
        with pytest.raises(auth_svc.AppleAuthError) as ei:
            auth_svc.verify_apple_id_token("x")
        assert "email_not_verified" in str(ei.value)


@pytest.mark.asyncio
async def test_me_reports_apple_enabled_flag() -> None:
    """apple_signin_enabled is true only when APPLE_CLIENT_ID is set AND some
    allow-list source exists (shared with Google)."""
    fake = _fake_settings(
        APPLE_CLIENT_ID="com.eko.signin", google_admin_emails_list=["owner@eko.com"]
    )
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake):
        async with await _client() as c:
            me = (await c.get("/api/v1/auth/me")).json()
    assert me["apple_signin_enabled"] is True


@pytest.mark.asyncio
async def test_password_login_is_admin() -> None:
    fake = _fake_settings()
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake):
        async with await _client() as c:
            await c.post("/api/v1/auth/login", json={"password": "s3cret-pass"})
            me = (await c.get("/api/v1/auth/me")).json()
        assert me["role"] == "admin"


# ── Google sign-in: allow-list + role resolution (needs DB) ──────────────────


@pytest.mark.asyncio
async def test_google_login_pinned_admin(_needs_db: None) -> None:
    fake = _fake_settings(google_admin_emails_list=["owner@eko.com"])
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_google_id_token", return_value="owner@eko.com"):
        async with await _client() as c:
            r = await c.post("/api/v1/auth/login/google", json={"id_token": "x"})
            assert r.status_code == 200, r.text
            me = (await c.get("/api/v1/auth/me")).json()
        assert me["role"] == "admin"


@pytest.mark.asyncio
async def test_google_login_db_member_then_denied(_needs_db: None) -> None:
    fake = _fake_settings()  # no env allow-list
    await _clear_allowed("member@eko.com", "stranger@eko.com")
    await _seed_allowed("member@eko.com", "member")
    try:
        with patch("app.api.v1.auth.get_settings", return_value=fake), \
             patch("app.services.auth.get_settings", return_value=fake):
            # Allowed DB member → logs in as member.
            with patch("app.api.v1.auth.verify_google_id_token", return_value="member@eko.com"):
                async with await _client() as c:
                    r = await c.post("/api/v1/auth/login/google", json={"id_token": "x"})
                    assert r.status_code == 200, r.text
                    me = (await c.get("/api/v1/auth/me")).json()
                    assert me["role"] == "member"
                    # Member can use the data API but NOT the admin (team) API.
                    assert (await c.get("/api/v1/leads")).status_code == 200
                    assert (await c.get("/api/v1/team")).status_code == 403
            # Email on no list → denied.
            with patch("app.api.v1.auth.verify_google_id_token", return_value="stranger@eko.com"):
                async with await _client() as c:
                    r = await c.post("/api/v1/auth/login/google", json={"id_token": "x"})
                    assert r.status_code == 401
                    assert r.json()["detail"] == "email_not_in_allow_list"
    finally:
        await _clear_allowed("member@eko.com", "stranger@eko.com")


# ── Google redirect-mode callback (ux_mode=redirect) ─────────────────────────


@pytest.mark.asyncio
async def test_google_callback_success_redirects_to_leads() -> None:
    """Valid CSRF + token + allowed email → 303 to /leads with a session cookie.

    The email is pinned in GOOGLE_ADMIN_EMAILS rather than only granted by
    `resolve_email_access`: access and organization are resolved separately and
    both must succeed, so an email nobody has assigned to an agency is refused
    even when the access half says yes.
    """
    fake = _fake_settings(google_admin_emails_list=["owner@eko.com"])
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_google_id_token", return_value="owner@eko.com"), \
         patch("app.api.v1.auth.resolve_email_access", return_value="admin"):
        async with await _client() as c:
            r = await c.post(
                "/api/v1/auth/login/google/callback",
                data={"credential": "tok", "g_csrf_token": "csrf123"},
                cookies={"g_csrf_token": "csrf123"},
            )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/leads"
    assert "eko_auth=" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_google_callback_csrf_mismatch_redirects_to_login() -> None:
    """Body token != cookie token (or missing) → bounce to /login, no session."""
    fake = _fake_settings()
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake):
        async with await _client() as c:
            r = await c.post(
                "/api/v1/auth/login/google/callback",
                data={"credential": "tok", "g_csrf_token": "body-token"},
                cookies={"g_csrf_token": "different-cookie"},
            )
    assert r.status_code == 303
    assert r.headers["location"] == "/login?error=google_failed"
    assert "eko_auth=" not in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_google_callback_denied_email_redirects_with_flag() -> None:
    """Valid CSRF + token but email not on the allow-list → /login?error=google_denied."""
    fake = _fake_settings()
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_google_id_token", return_value="stranger@eko.com"), \
         patch("app.api.v1.auth.resolve_email_access", return_value=None):
        async with await _client() as c:
            r = await c.post(
                "/api/v1/auth/login/google/callback",
                data={"credential": "tok", "g_csrf_token": "csrf123"},
                cookies={"g_csrf_token": "csrf123"},
            )
    assert r.status_code == 303
    assert r.headers["location"] == "/login?error=google_denied"
    assert "eko_auth=" not in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_google_callback_invalid_token_redirects_to_login() -> None:
    """A bad ID token (verifier raises) → /login?error=google_failed, no session."""
    fake = _fake_settings()
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch(
             "app.api.v1.auth.verify_google_id_token",
             side_effect=auth_svc.GoogleAuthError("invalid_id_token"),
         ):
        async with await _client() as c:
            r = await c.post(
                "/api/v1/auth/login/google/callback",
                data={"credential": "bad", "g_csrf_token": "csrf123"},
                cookies={"g_csrf_token": "csrf123"},
            )
    assert r.status_code == 303
    assert r.headers["location"] == "/login?error=google_failed"
    assert "eko_auth=" not in r.headers.get("set-cookie", "")


# ── Apple sign-in: same allow-list + role resolution (needs DB) ──────────────


@pytest.mark.asyncio
async def test_apple_login_pinned_admin(_needs_db: None) -> None:
    fake = _fake_settings(
        APPLE_CLIENT_ID="com.eko.signin", google_admin_emails_list=["owner@eko.com"]
    )
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_apple_id_token", return_value="owner@eko.com"):
        async with await _client() as c:
            r = await c.post("/api/v1/auth/login/apple", json={"id_token": "x"})
            assert r.status_code == 200, r.text
            me = (await c.get("/api/v1/auth/me")).json()
        assert me["role"] == "admin"


@pytest.mark.asyncio
async def test_apple_login_db_member_then_denied(_needs_db: None) -> None:
    fake = _fake_settings(APPLE_CLIENT_ID="com.eko.signin")  # no env allow-list
    await _clear_allowed("amember@eko.com", "astranger@eko.com")
    await _seed_allowed("amember@eko.com", "member")
    try:
        with patch("app.api.v1.auth.get_settings", return_value=fake), \
             patch("app.services.auth.get_settings", return_value=fake):
            # Allowed DB member (added via Google) also logs in via Apple.
            with patch("app.api.v1.auth.verify_apple_id_token", return_value="amember@eko.com"):
                async with await _client() as c:
                    r = await c.post("/api/v1/auth/login/apple", json={"id_token": "x"})
                    assert r.status_code == 200, r.text
                    me = (await c.get("/api/v1/auth/me")).json()
                    assert me["role"] == "member"
            # Email on no list → denied (same message as Google).
            with patch("app.api.v1.auth.verify_apple_id_token", return_value="astranger@eko.com"):
                async with await _client() as c:
                    r = await c.post("/api/v1/auth/login/apple", json={"id_token": "x"})
                    assert r.status_code == 401
                    assert r.json()["detail"] == "email_not_in_allow_list"
    finally:
        await _clear_allowed("amember@eko.com", "astranger@eko.com")


def test_the_session_cookie_is_secure_behind_tls_and_usable_without_it() -> None:
    """`secure` used to come from APP_ENV, which cannot see how the request
    arrived.

    The same install is reached two ways: over TLS at its domain, and over plain
    http on the LAN. One environment flag has to answer for both — so marking it
    production made the browser refuse to keep the cookie on the LAN address and
    nobody could hold a session there, which is exactly why this install was
    left on `development` and was therefore sending session cookies over plain
    http on the domain as well.
    """
    from types import SimpleNamespace

    from app.api.v1.auth import _cookie_is_secure

    def _request(scheme: str, forwarded: str | None = None) -> object:
        return SimpleNamespace(
            url=SimpleNamespace(scheme=scheme),
            headers={"x-forwarded-proto": forwarded} if forwarded else {},
        )

    # Straight https, and the LAN address on plain http.
    assert _cookie_is_secure(_request("https")) is True
    assert _cookie_is_secure(_request("http")) is False

    # Behind the Cloudflare tunnel the app itself sees http; the header is what
    # says the browser used TLS. Missing this would ship a non-Secure cookie on
    # the very origin that has TLS.
    assert _cookie_is_secure(_request("http", "https")) is True
    # A proxy chain lists the client's protocol first.
    assert _cookie_is_secure(_request("http", "https, http")) is True
    assert _cookie_is_secure(_request("https", "http")) is False

    # No request to look at: take the strict answer rather than guessing.
    assert _cookie_is_secure(None) is True

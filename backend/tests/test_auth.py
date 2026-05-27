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
        # Google Sign In (defaults: feature configured, no env allow-list).
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        GOOGLE_ALLOWED_DOMAIN="",
        google_admin_emails_list=[],
        google_allowed_emails_list=[],
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

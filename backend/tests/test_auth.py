"""Tests for dashboard auth — token service + login/gate API."""
from __future__ import annotations

import types
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import auth as auth_svc


def _fake_settings(**over):
    base = dict(
        AUTH_ENABLED=True,
        DASHBOARD_PASSWORD="s3cret-pass",
        AUTH_SECRET="unit-test-secret",
        AUTH_TTL_HOURS=168,
        is_production=False,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


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

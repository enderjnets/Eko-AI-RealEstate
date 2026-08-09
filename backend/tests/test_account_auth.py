"""Self-registration (viewer accounts) — password hashing, register/login, read-only gate."""
from __future__ import annotations

import os
import types
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.services import auth as auth_svc


def _fake_settings(**over):
    base = dict(
        REGISTRATION_ENABLED=True,
        AUTH_ENABLED=True,
        DASHBOARD_PASSWORD="s3cret-pass",
        AUTH_SECRET="unit-test-secret",
        AUTH_TTL_HOURS=168,
        is_production=False,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — account auth tests need live Postgres")


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _clear(*emails: str) -> None:
    from app.db.base import get_session_factory
    from app.models import Account

    Session = get_session_factory()
    async with Session() as s:
        await s.execute(delete(Account).where(Account.email.in_(emails)))
        await s.commit()


# ── password hashing (pure) ─────────────────────────────────────────────────


def test_password_hash_roundtrip() -> None:
    h = auth_svc.hash_password("Sup3r-secret!")
    assert h.startswith("pbkdf2_sha256$")
    assert auth_svc.verify_password("Sup3r-secret!", h) is True
    assert auth_svc.verify_password("wrong", h) is False
    assert auth_svc.verify_password("x", "garbage") is False


# ── register + login (e2e) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_creates_viewer_and_logs_in(_needs_db: None) -> None:
    email = f"demo_{uuid.uuid4().hex[:8]}@example.com"
    try:
        async with await _client() as c:
            r = await c.post(
                "/api/v1/auth/register",
                json={"name": "Demo User", "email": email, "password": "view-only-123",
                      "phone": "+1 305 555 0000", "country": "USA", "state": "FL"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["role"] == "viewer"
            assert "eko_auth" in c.cookies  # auto-logged-in

            # Duplicate email → 409.
            dup = await c.post("/api/v1/auth/register",
                               json={"name": "X", "email": email.upper(), "password": "another-123"})
            assert dup.status_code == 409

            # Wrong password → 401; correct → 200.
            assert (await c.post("/api/v1/auth/login/account",
                                 json={"email": email, "password": "nope"})).status_code == 401
            ok = await c.post("/api/v1/auth/login/account",
                              json={"email": email, "password": "view-only-123"})
            assert ok.status_code == 200 and ok.json()["role"] == "viewer"
    finally:
        await _clear(email)


@pytest.mark.asyncio
async def test_register_invalid_email_400(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.post("/api/v1/auth/register",
                         json={"name": "X", "email": "not-an-email", "password": "view-only-123"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_register_short_password_422(_needs_db: None) -> None:
    async with await _client() as c:
        r = await c.post("/api/v1/auth/register",
                         json={"name": "X", "email": "a@b.com", "password": "short"})
    assert r.status_code == 422


# ── read-only gate (viewer can GET, cannot write) ───────────────────────────


@pytest.mark.asyncio
async def test_viewer_is_read_only(_needs_db: None) -> None:
    """With AUTH_ENABLED, a viewer session may GET protected routes but any write
    (POST/PUT/PATCH/DELETE) is rejected with 403."""
    email = f"ro_{uuid.uuid4().hex[:8]}@example.com"
    fake = _fake_settings()
    try:
        with patch("app.api.v1.auth.get_settings", return_value=fake), \
             patch("app.services.auth.get_settings", return_value=fake):
            async with await _client() as c:
                reg = await c.post("/api/v1/auth/register",
                                   json={"name": "RO", "email": email, "password": "view-only-123"})
                assert reg.status_code == 201, reg.text
                assert "eko_auth" in c.cookies

                # GET is allowed.
                assert (await c.get("/api/v1/leads")).status_code == 200
                # Writes are blocked with 403 (not 401 — they ARE authenticated).
                assert (await c.post("/api/v1/leads",
                                     json={"name": "x", "channel": "sms", "identifier": "+13050000000"})).status_code == 403
    finally:
        await _clear(email)

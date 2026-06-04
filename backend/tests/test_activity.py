"""Per-user activity tracking — device parsing, ip, middleware capture, role change."""
from __future__ import annotations

import os
import types
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.services import auth as auth_svc
from app.services.activity import client_ip, parse_device, section_for_path


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — activity tests need live Postgres")


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _clear_activity(*emails: str) -> None:
    from app.db.base import get_session_factory
    from app.models import UserActivity

    Session = get_session_factory()
    async with Session() as s:
        await s.execute(delete(UserActivity).where(UserActivity.email.in_(emails)))
        await s.commit()


async def _clear_accounts(*emails: str) -> None:
    from app.db.base import get_session_factory
    from app.models import Account

    Session = get_session_factory()
    async with Session() as s:
        await s.execute(delete(Account).where(Account.email.in_(emails)))
        await s.commit()


# ── pure ────────────────────────────────────────────────────────────────────


def test_parse_device() -> None:
    assert "Chrome" in parse_device("Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120 Safari/537")
    assert parse_device("Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120").endswith("macOS")
    assert "iPhone" in parse_device("Mozilla/5.0 (iPhone; CPU iPhone OS) Safari")
    assert parse_device(None) is None


def test_client_ip_prefers_forwarded() -> None:
    req = types.SimpleNamespace(
        headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"},
        client=types.SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "9.9.9.9"
    req2 = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="5.5.5.5"))
    assert client_ip(req2) == "5.5.5.5"


def test_section_for_path() -> None:
    assert section_for_path("/api/v1/leads/3") == "leads"
    assert section_for_path("/api/v1/visits/agenda") == "calendar"
    assert section_for_path("/api/v1/auth/me") is None
    assert section_for_path("/health") is None


# ── middleware capture (e2e) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_middleware_records_activity(_needs_db: None) -> None:
    """An authenticated request to a tracked section upserts the user's activity row."""
    email = f"stats_{uuid.uuid4().hex[:8]}@example.com"
    token = auth_svc.make_token(email=email, role="member")
    try:
        async with await _client() as c:
            c.cookies.set("eko_auth", token)
            await c.get("/api/v1/leads")

        from app.db.base import get_session_factory
        from app.models import UserActivity

        Session = get_session_factory()
        async with Session() as s:
            row = (
                await s.execute(select(UserActivity).where(UserActivity.email == email))
            ).scalar_one_or_none()
        assert row is not None
        assert row.request_count >= 1
        assert (row.sections or {}).get("leads", 0) >= 1
        assert row.active_days >= 1
    finally:
        await _clear_activity(email)


# ── account role change (e2e) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_role_change_viewer_to_member(_needs_db: None) -> None:
    email = f"role_{uuid.uuid4().hex[:8]}@example.com"
    try:
        async with await _client() as c:
            reg = await c.post(
                "/api/v1/auth/register",
                json={"name": "Role Test", "email": email, "password": "view-only-123"},
            )
            assert reg.status_code == 201 and reg.json()["role"] == "viewer"

            acct_id = next(
                a["id"] for a in (await c.get("/api/v1/team/accounts")).json() if a["email"] == email
            )
            up = await c.patch(f"/api/v1/team/accounts/{acct_id}", json={"role": "member"})
            assert up.status_code == 200 and up.json()["role"] == "member"

            # Logging in now yields a member session (not viewer).
            login = await c.post(
                "/api/v1/auth/login/account", json={"email": email, "password": "view-only-123"}
            )
            assert login.status_code == 200 and login.json()["role"] == "member"
    finally:
        await _clear_accounts(email)
        await _clear_activity(email)

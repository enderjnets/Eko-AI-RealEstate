"""Tests for the admin-only Team / access API (/api/v1/team).

With AUTH_ENABLED=false (the suite default) require_admin is a no-op, so these
exercise the CRUD + the lockout guards directly. The member-vs-admin gate (403)
is covered in test_auth.py via a real member session.
"""
from __future__ import annotations

import os
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.main import app


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — team API tests need live Postgres")


@pytest_asyncio.fixture(autouse=True)
async def _preserve_allowed_users():
    """Snapshot the WHOLE allowed_users table before each test and restore it after.

    These tests intentionally clear the table (via `_clear()`) to exercise the
    clean-slate / last-admin guards. Run against a live DB (as the ROG suite is),
    an unbounded clear would wipe REAL team config — so we snapshot + restore to
    guarantee no test in this file can destroy production data. No-op without a DB."""
    if not os.environ.get("DATABASE_URL"):
        yield
        return
    from app.db.base import get_session_factory
    from app.models import AllowedUser

    Session = get_session_factory()
    async with Session() as s:
        snapshot = [
            (r.email, r.role, r.added_by)
            for r in (await s.execute(select(AllowedUser))).scalars().all()
        ]
    try:
        yield
    finally:
        async with Session() as s:
            await s.execute(delete(AllowedUser))
            for email, role, added_by in snapshot:
                s.add(AllowedUser(email=email, role=role, added_by=added_by))
            await s.commit()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@asynccontextmanager
async def _operator_client() -> AsyncIterator[AsyncClient]:
    """A session carrying the platform-operator claim.

    The demo-account routes are operator-only: they read and delete signups that
    belong to no client agency. `require_platform_admin` used to stand down when
    AUTH_ENABLED was false, which made them anonymous in the compose default —
    so these tests passed without ever presenting a credential. It now refuses
    outright in that mode, because the signing key with auth off is a constant
    published in this repository, so a claim proves nothing. Hence the patched
    settings: this is the configuration the routes actually require.
    """
    from unittest.mock import patch as _patch

    from app.api.v1.auth import COOKIE_NAME
    from app.config import get_settings
    from app.models.organization import DEFAULT_ORG_ID
    from app.services.auth import make_token

    s = get_settings()
    with _patch.object(s, "AUTH_ENABLED", True), \
         _patch.object(s, "AUTH_SECRET", "operator-client-test-secret"), \
         _patch.object(s, "PLATFORM_ADMIN_EMAILS", "operator@eko.com"):
        token = make_token(
            email="operator@eko.com", role="admin", org_id=DEFAULT_ORG_ID,
            superuser=True,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={COOKIE_NAME: token},
        ) as client:
            yield client


async def _clear(*emails: str) -> None:
    from app.db.base import get_session_factory
    from app.models import AllowedUser

    Session = get_session_factory()
    async with Session() as s:
        if emails:
            await s.execute(delete(AllowedUser).where(AllowedUser.email.in_(emails)))
        else:
            await s.execute(delete(AllowedUser))
        await s.commit()


def _fake(**over):
    # `platform_admin_emails_list` too: the last-admin guard now counts the
    # operators, and only for the organization they actually belong to.
    base = dict(google_admin_emails_list=[], platform_admin_emails_list=[])
    base.update(over)
    return types.SimpleNamespace(**base)


async def _clear_accounts(*emails: str) -> None:
    from app.db.base import get_session_factory
    from app.models import Account

    Session = get_session_factory()
    async with Session() as s:
        await s.execute(delete(Account).where(Account.email.in_(emails)))
        await s.commit()


@pytest.mark.asyncio
async def test_demo_accounts_list_and_delete(_needs_db: None) -> None:
    """Admins can list self-registered (viewer) demo accounts + delete one."""
    import uuid

    email = f"reg_{uuid.uuid4().hex[:8]}@example.com"
    try:
        async with await _client() as c:
            reg = await c.post(
                "/api/v1/auth/register",
                json={"name": "Margie Demo", "email": email, "password": "view-only-123",
                      "company": "Acme Realty", "country": "USA"},
            )
            assert reg.status_code == 201, reg.text

        # Demo signups belong to no client agency, so only an operator lists or
        # deletes them.
        async with _operator_client() as op:
            listing = (await op.get("/api/v1/team/accounts")).json()
            mine = next((a for a in listing if a["email"] == email), None)
            assert mine is not None
            assert mine["name"] == "Margie Demo" and mine["company"] == "Acme Realty"
            assert mine["role"] == "viewer"

            acct_id = mine["id"]
            assert (await op.delete(f"/api/v1/team/accounts/{acct_id}")).status_code == 200
            # Gone now → 404 on re-delete; absent from the list.
            assert (await op.delete(f"/api/v1/team/accounts/{acct_id}")).status_code == 404
            after = (await op.get("/api/v1/team/accounts")).json()
            assert not any(a["email"] == email for a in after)
    finally:
        await _clear_accounts(email)


@pytest.mark.asyncio
async def test_team_crud_lifecycle(_needs_db: None) -> None:
    await _clear("agent@office.com", "backup@office.com")
    try:
        async with await _client() as c:
            r = await c.post("/api/v1/team", json={"email": "Agent@Office.com", "role": "member"})
            assert r.status_code == 201, r.text
            assert r.json()["email"] == "agent@office.com"  # normalized lowercase
            assert r.json()["immutable"] is False

            listing = (await c.get("/api/v1/team")).json()
            assert any(m["email"] == "agent@office.com" and m["role"] == "member" for m in listing)

            # Duplicate → 409.
            dup = await c.post("/api/v1/team", json={"email": "agent@office.com"})
            assert dup.status_code == 409

            # Promote member → admin.
            up = await c.patch("/api/v1/team/agent@office.com", json={"role": "admin"})
            assert up.status_code == 200 and up.json()["role"] == "admin"

            # A 2nd admin so the first isn't the "last admin" → then it can be removed.
            await c.post("/api/v1/team", json={"email": "backup@office.com", "role": "admin"})
            assert (await c.delete("/api/v1/team/agent@office.com")).status_code == 200

            after = (await c.get("/api/v1/team")).json()
            assert not any(m["email"] == "agent@office.com" for m in after)
            assert any(m["email"] == "backup@office.com" for m in after)
    finally:
        await _clear("agent@office.com", "backup@office.com")


@pytest.mark.asyncio
async def test_invalid_email_rejected(_needs_db: None) -> None:
    async with await _client() as c:
        # Invalid address → 400 (normalized + validated in the endpoint).
        assert (await c.post("/api/v1/team", json={"email": "not-an-email"})).status_code == 400


@pytest.mark.asyncio
async def test_pinned_admin_is_immutable(_needs_db: None) -> None:
    await _clear("owner@office.com")
    fake = _fake(google_admin_emails_list=["owner@office.com"])
    try:
        with patch("app.api.v1.team.get_settings", return_value=fake):
            async with await _client() as c:
                await c.post("/api/v1/team", json={"email": "owner@office.com", "role": "admin"})
                listing = (await c.get("/api/v1/team")).json()
                assert any(m["email"] == "owner@office.com" and m["immutable"] for m in listing)
                # Can't demote or remove the pinned admin.
                assert (
                    await c.patch("/api/v1/team/owner@office.com", json={"role": "member"})
                ).status_code == 400
                assert (await c.delete("/api/v1/team/owner@office.com")).status_code == 400
    finally:
        await _clear("owner@office.com")


@pytest.mark.asyncio
async def test_cannot_remove_last_admin(_needs_db: None) -> None:
    # No pinned admins + exactly one DB admin → it can't be removed or demoted.
    fake = _fake(google_admin_emails_list=[])
    await _clear()  # clean slate
    try:
        with patch("app.api.v1.team.get_settings", return_value=fake):
            async with await _client() as c:
                await c.post("/api/v1/team", json={"email": "solo@office.com", "role": "admin"})
                assert (await c.delete("/api/v1/team/solo@office.com")).status_code == 400
                assert (
                    await c.patch("/api/v1/team/solo@office.com", json={"role": "member"})
                ).status_code == 400
                # A second admin makes the first removable.
                await c.post("/api/v1/team", json={"email": "two@office.com", "role": "admin"})
                assert (await c.delete("/api/v1/team/solo@office.com")).status_code == 200
    finally:
        await _clear()

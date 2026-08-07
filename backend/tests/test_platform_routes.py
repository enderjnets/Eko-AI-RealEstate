"""Platform operator routes: tenant lifecycle and audited impersonation.

The gate here is the one that matters. These endpoints deliberately cross the
tenant boundary, so `require_admin` is the wrong check — every client agency has
an admin, and an earlier version of the demo-account routes was reachable by all
of them. `require_platform_admin` additionally pins the default organization.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.organization import DEFAULT_ORG_ID
from app.services import tenant_resolver
from app.services.auth import COOKIE_NAME, make_token

SLUG = "audit-test-agency"


def _client(org_id: int) -> AsyncClient:
    token = make_token(email=f"admin{org_id}@x.test", role="admin", org_id=org_id)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={COOKIE_NAME: token},
    )


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM organizations WHERE slug = :s"), {"s": SLUG})
        await db.execute(
            text("DELETE FROM user_activity WHERE email LIKE 'impersonation:%'")
        )
        await db.commit()
    tenant_resolver.reset_cache()


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch) -> object:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", True)
    monkeypatch.setattr(get_settings(), "AUTH_SECRET", "platform-test-secret")
    yield
    tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_a_client_agency_admin_cannot_reach_the_platform() -> None:
    """The whole point of the separate gate: an agency's own admin is an admin.

    The client org must genuinely EXIST and be active. An earlier version of
    this test used a made-up id, so the 403 came from the middleware rejecting
    an unknown organization and the assertion passed even with the wrong gate —
    caught by mutating require_platform_admin back to require_admin.
    """
    async with _client(org_id=DEFAULT_ORG_ID) as operator:
        created = await operator.post(
            "/api/v1/platform/organizations",
            json={"name": "Audit Test Agency", "slug": SLUG},
        )
        client_org_id = created.json()["id"]

    try:
        async with _client(org_id=client_org_id) as c:
            assert (await c.get("/api/v1/platform/organizations")).status_code == 403
            assert (
                await c.post(
                    "/api/v1/platform/organizations",
                    json={"name": "Sneaky", "slug": "sneaky-agency"},
                )
            ).status_code == 403
            assert (await c.post("/api/v1/platform/impersonate/1")).status_code == 403
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_operator_creates_and_suspends_a_tenant() -> None:
    try:
        async with _client(org_id=DEFAULT_ORG_ID) as c:
            created = await c.post(
                "/api/v1/platform/organizations",
                json={"name": "Audit Test Agency", "slug": SLUG},
            )
            assert created.status_code == 201, created.text
            org_id = created.json()["id"]
            assert created.json()["status"] == "active"

            # A duplicate slug must be a clean 409, not a 500 from the constraint.
            dup = await c.post(
                "/api/v1/platform/organizations",
                json={"name": "Other", "slug": SLUG},
            )
            assert dup.status_code == 409

            listed = await c.get("/api/v1/platform/organizations")
            assert org_id in [o["id"] for o in listed.json()]

            suspended = await c.patch(
                f"/api/v1/platform/organizations/{org_id}",
                json={"status": "suspended"},
            )
            assert suspended.status_code == 200
            assert suspended.json()["status"] == "suspended"

            # The resolver caches the org list; creating or suspending has to
            # invalidate it or a new tenant stays unroutable for the TTL.
            assert (await tenant_resolver.active_orgs())[org_id] == "suspended"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_impersonation_is_recorded_before_the_cookie_is_issued() -> None:
    """An operator who can read every tenant must leave a trail; otherwise there
    is no answer to 'who looked at our data?'."""
    try:
        async with _client(org_id=DEFAULT_ORG_ID) as c:
            created = await c.post(
                "/api/v1/platform/organizations",
                json={"name": "Audit Test Agency", "slug": SLUG},
            )
            org_id = created.json()["id"]

            resp = await c.post(f"/api/v1/platform/impersonate/{org_id}")
            assert resp.status_code == 200, resp.text
            assert resp.json()["org_id"] == org_id
            assert COOKIE_NAME in resp.cookies, "no session was issued"

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT org_id FROM user_activity WHERE email = :e"
                    ),
                    {"e": f"impersonation:org-{org_id}"},
                )
            ).first()
        assert row is not None, "impersonation left no audit row"
        assert row[0] == org_id
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_impersonating_a_missing_org_is_404_not_a_usable_session() -> None:
    async with _client(org_id=DEFAULT_ORG_ID) as c:
        resp = await c.post("/api/v1/platform/impersonate/424242")
    assert resp.status_code == 404
    assert COOKIE_NAME not in resp.cookies

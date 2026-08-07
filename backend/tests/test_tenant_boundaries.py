"""Boundaries that are not row-level: routing, suspension, and platform scope.

RLS protects rows once the acting organization is known. These cover the cases
where the *organization itself* is chosen wrongly, which RLS cannot catch — it
faithfully enforces whatever org it is handed.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.models.organization import DEFAULT_ORG_ID, DEMO_ORG_ID
from app.services import tenant_resolver
from app.services.auth import make_token
from app.services.tenant_resolver import (
    WebhookOrgUnresolved,
    resolve_org_for_request,
)

WEBHOOK_PATH = "/api/v1/webhooks/sms"


async def _set_org_status(org_id: int, status: str) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE organizations SET status = :s WHERE id = :i"),
            {"s": status, "i": org_id},
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _make_org(org_id: int, slug: str) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, :n, :s, 'active', 'pilot') ON CONFLICT (id) DO NOTHING"
            ),
            {"i": org_id, "n": slug, "s": slug},
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _drop_org(org_id: int) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org_id})
        await db.commit()
    tenant_resolver.reset_cache()


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch) -> object:
    """These paths only exist when auth is on; with it off everything is org 1."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", True)
    # Required once auth is on: minting refuses to sign with the constant this
    # repository would otherwise derive. That guard firing here is correct.
    monkeypatch.setattr(get_settings(), "AUTH_SECRET", "test-only-signing-secret")
    yield
    tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_inbound_webhook_refuses_rather_than_guessing_the_agency() -> None:
    """The defect this replaces filed agency B's leads — and their whole
    conversation transcript — into agency A's dashboard, while agency B saw
    nothing and their follow-ups never fired. Refusing is recoverable: the
    provider retries and the operator sees the error."""
    await _make_org(90, "second-agency")
    try:
        with pytest.raises(WebhookOrgUnresolved):
            await resolve_org_for_request(WEBHOOK_PATH, None)
    finally:
        await _drop_org(90)


@pytest.mark.asyncio
async def test_inbound_webhook_routes_while_there_is_one_real_tenant() -> None:
    """Refusing must not break the single-tenant case that works today."""
    assert await resolve_org_for_request(WEBHOOK_PATH, None) == DEFAULT_ORG_ID


@pytest.mark.asyncio
async def test_suspended_org_is_not_routable_for_inbound() -> None:
    await _set_org_status(DEFAULT_ORG_ID, "suspended")
    try:
        with pytest.raises(WebhookOrgUnresolved):
            await resolve_org_for_request(WEBHOOK_PATH, None)
    finally:
        await _set_org_status(DEFAULT_ORG_ID, "active")


@pytest.mark.asyncio
async def test_demo_org_never_receives_inbound_messages() -> None:
    """The demo org exists for /register signups, not to be handed real leads."""
    orgs = await tenant_resolver.active_orgs()
    assert DEMO_ORG_ID in orgs, "demo org missing — the fixture below proves nothing"
    assert await resolve_org_for_request(WEBHOOK_PATH, None) == DEFAULT_ORG_ID


@pytest.mark.asyncio
async def test_platform_routes_reject_a_client_agencys_admin() -> None:
    """require_admin authorises the admin of SOME organization, and every client
    agency has one — so on its own it let a client read and delete the
    operator's demo signups, which run on a bypass session."""
    from fastapi import HTTPException
    from starlette.datastructures import Headers
    from starlette.requests import Request

    from app.api.v1.auth import COOKIE_NAME, require_platform_admin

    def _request_as(org_id: int) -> Request:
        token = make_token(email="a@x.test", role="admin", org_id=org_id)
        headers = Headers({"cookie": f"{COOKIE_NAME}={token}"})
        return Request({"type": "http", "headers": headers.raw, "method": "GET", "path": "/"})

    await _make_org(91, "client-agency")
    try:
        with pytest.raises(HTTPException) as caught:
            await require_platform_admin(_request_as(91))
        assert caught.value.status_code == 403
        # The operator still gets through.
        await require_platform_admin(_request_as(DEFAULT_ORG_ID))
    finally:
        await _drop_org(91)

"""Whose message body may this organization ask for.

An agency on the operator's shared Resend account legitimately holds the shared
webhook secret, so it can sign a payload naming its own mailbox — which resolves
the org to itself — while pointing `data.id` at a message belonging to another
agency on that same account. The body would be fetched with the shared key and
stored inside theirs. Fixing *which* key is used did not fix *which ids* may be
named.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.models.channel_route import CHANNEL_EMAIL
from app.services import tenant_resolver
from app.services.email import fetch_inbound_email
from app.services.tenant_context import org_scope

ORG_A = 910
ORG_B = 911


async def _seed() -> None:
    async with get_bypass_session_factory()() as db:
        for org_id, slug, mailbox in (
            (ORG_A, "fetch-scope-a", "leads@fetch-a.test"),
            (ORG_B, "fetch-scope-b", "leads@fetch-b.test"),
        ):
            await db.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, status, plan) "
                    "VALUES (:i, :s, :s, 'active', 'pilot') ON CONFLICT DO NOTHING"
                ),
                {"i": org_id, "s": slug},
            )
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o, :c, :d) ON CONFLICT DO NOTHING"
                ),
                {"o": org_id, "c": CHANNEL_EMAIL, "d": mailbox},
            )
        await db.commit()
    tenant_resolver.reset_cache()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM channel_routes WHERE org_id IN (:a, :b)"),
            {"a": ORG_A, "b": ORG_B},
        )
        await db.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": ORG_A, "b": ORG_B},
        )
        await db.commit()
    tenant_resolver.reset_cache()


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, *_a, **_kw) -> _Resp:
        return _Resp(self._payload)


def _httpx_returning(payload: dict) -> SimpleNamespace:
    """A stand-in for the module's own `httpx` reference.

    Patching `httpx.AsyncClient` replaces the class globally, and anything that
    subclasses it while the patch is active dies with a confusing TypeError —
    the anthropic SDK does exactly that on a lazy import.
    """
    return SimpleNamespace(AsyncClient=lambda **_kw: _Client(payload))


@pytest.fixture(autouse=True)
def _real_email(monkeypatch) -> object:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "EMAIL_SIMULATED", False)
    monkeypatch.setattr(get_settings(), "RESEND_API_KEY", "shared-resend-key")
    yield
    tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_a_fetched_body_addressed_to_another_agency_is_refused() -> None:
    """Agency A asks for a message that belongs to agency B."""
    await _seed()
    theirs = {"id": "eml-b", "to": ["leads@fetch-b.test"], "text": "B's private body"}
    try:
        with org_scope(ORG_A), patch(
            "app.services.email.httpx", _httpx_returning(theirs)
        ):
            assert await fetch_inbound_email("eml-b") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_agency_can_still_fetch_its_own_message() -> None:
    """The check must not break the ordinary path it guards."""
    await _seed()
    mine = {"id": "eml-a", "to": ["leads@fetch-a.test"], "text": "A's own body"}
    try:
        with org_scope(ORG_A), patch(
            "app.services.email.httpx", _httpx_returning(mine)
        ):
            got = await fetch_inbound_email("eml-a")
        assert got is not None and got["text"] == "A's own body"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_body_with_no_readable_recipients_is_refused() -> None:
    """The check had nothing to compare against and waved it through.

    Reachable without any malformed input: the `To:` header of a BCC-only
    delivery is the literal `undisclosed-recipients:;`, which parses to no
    addresses at all. Naming another agency's message id and letting the
    recipient list come back empty walked straight past the guard.
    """
    await _seed()
    hidden = {
        "id": "eml-bcc",
        "to": "undisclosed-recipients:;",
        "text": "B's private body",
    }
    try:
        with org_scope(ORG_A), patch(
            "app.services.email.httpx", _httpx_returning(hidden)
        ):
            assert await fetch_inbound_email("eml-bcc") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_check_does_not_fire_before_a_second_agency_exists() -> None:
    """Nobody to impersonate, so nothing to refuse.

    A single-customer install must keep accepting every shape of header — the
    guard is about one agency borrowing another's message id, and until a second
    agency has an email route there is no other agency.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM channel_routes WHERE channel = :c"),
            {"c": CHANNEL_EMAIL},
        )
        await db.commit()
    tenant_resolver.reset_cache()
    unreadable = {"id": "eml-solo", "to": "undisclosed-recipients:;", "text": "hi"}
    with org_scope(1), patch(
        "app.services.email.httpx", _httpx_returning(unreadable)
    ):
        got = await fetch_inbound_email("eml-solo")
    assert got is not None and got["text"] == "hi"


@pytest.mark.asyncio
async def test_an_agency_without_its_own_route_cannot_fetch_a_hidden_message() -> None:
    """The case where the empty-recipients guard is the only thing standing.

    Agency A has no email route of its own — it is the single active tenant, so
    the fallback binds it — while agency B, suspended for non-payment, still has
    one and still has mail on the shared Resend account. With a body whose
    recipients do not parse, the "no route claims these addresses" branch asks
    whether *A* owns a route, finds none, and answers yes. Only refusing an
    unreadable recipient list closes it.
    """
    await _seed()
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM channel_routes WHERE org_id = :i"), {"i": ORG_A}
        )
        await db.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :i"),
            {"i": ORG_B},
        )
        await db.commit()
    tenant_resolver.reset_cache()
    hidden = {"id": "eml-hidden", "to": "undisclosed-recipients:;", "text": "B's mail"}
    try:
        with org_scope(ORG_A), patch(
            "app.services.email.httpx", _httpx_returning(hidden)
        ):
            assert await fetch_inbound_email("eml-hidden") is None
    finally:
        await _cleanup()

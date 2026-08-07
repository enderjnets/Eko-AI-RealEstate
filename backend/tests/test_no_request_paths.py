"""Code that reaches the database with no HTTP request behind it.

`conftest.py` binds the default org for every test, which mirrors what the ASGI
middleware does per request — and hides everything that runs *without* a
request. An audit found login, all three background workers and four CLI
scripts silently broken in production while 274 tests were green, precisely
because the fixture papered over the missing org.

Every test here therefore clears the org first with `org_scope(None)`, which is
the real production state for these paths. Without the fix they fail; with the
fixture's default binding left in place they would all pass for the wrong reason.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.models import AllowedUser, Lead
from app.models.lead import LeadStatus
from app.models.organization import DEFAULT_ORG_ID, DEMO_ORG_ID
from app.services.auth import resolve_email_access, resolve_email_org
from app.services.tenant_context import get_org_id, org_scope, run_for_every_org

SEEDED_EMAIL = "worker-probe@example.test"


async def _cleanup(*phones: str, email: str | None = None) -> None:
    async with get_bypass_session_factory()() as db:
        for phone in phones:
            await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": phone})
        if email:
            await db.execute(text("DELETE FROM allowed_users WHERE email = :e"), {"e": email})
        await db.commit()


@pytest.mark.asyncio
async def test_workers_visit_every_org_with_no_org_bound() -> None:
    """A worker with no org sees zero rows under default-deny and would run
    forever doing nothing. run_for_every_org is what makes that impossible."""
    async with get_bypass_session_factory()() as db:
        db.add(Lead(phone="+18880000001", status=LeadStatus.NEW, org_id=DEFAULT_ORG_ID))
        db.add(Lead(phone="+18880000002", status=LeadStatus.NEW, org_id=DEMO_ORG_ID))
        await db.commit()

    seen: dict[int, list[str]] = {}

    async def _collect(session) -> None:
        org = get_org_id()
        assert org is not None, "run_for_every_org must bind an org before the work runs"
        rows = (await session.execute(select(Lead))).scalars().all()
        seen[org] = [r.phone for r in rows]

    try:
        with org_scope(None):
            await run_for_every_org(_collect)

        assert DEFAULT_ORG_ID in seen and DEMO_ORG_ID in seen, (
            f"worker skipped an organization: visited {sorted(seen)}"
        )
        assert "+18880000001" in seen[DEFAULT_ORG_ID]
        assert "+18880000002" in seen[DEMO_ORG_ID]
        # The decisive part: each pass saw only its own tenant.
        assert "+18880000002" not in seen[DEFAULT_ORG_ID]
        assert "+18880000001" not in seen[DEMO_ORG_ID]
    finally:
        await _cleanup("+18880000001", "+18880000002")


@pytest.mark.asyncio
async def test_worker_restores_the_previous_org_afterwards() -> None:
    """org_scope must not leak the last tenant it touched into whatever runs next."""
    with org_scope(DEFAULT_ORG_ID):
        async def _noop(session) -> None:
            return None

        await run_for_every_org(_noop)
        assert get_org_id() == DEFAULT_ORG_ID


@pytest.mark.asyncio
async def test_login_lookup_finds_users_with_no_org_bound() -> None:
    """Login resolves *which* org a user belongs to, so it cannot already be
    scoped to one. Run under RLS it found nobody and denied every sign-in."""
    async with get_bypass_session_factory()() as db:
        db.add(
            AllowedUser(
                email=SEEDED_EMAIL, role="member", added_by="test", org_id=DEMO_ORG_ID
            )
        )
        await db.commit()

    try:
        with org_scope(None):
            async with get_bypass_session_factory()() as db:
                role = await resolve_email_access(SEEDED_EMAIL, db)
                org_id = await resolve_email_org(SEEDED_EMAIL, db)
        assert role == "member", "login denied a known user because it was org-scoped"
        assert org_id == DEMO_ORG_ID, (
            "login resolved the wrong org — the user would land in another agency's data"
        )
    finally:
        await _cleanup(email=SEEDED_EMAIL)


@pytest.mark.asyncio
async def test_token_carries_the_users_org() -> None:
    """The defect that defeated the whole isolation layer: no login path wrote
    the org into the token, so every session resolved to the default org."""
    from app.services.auth import make_token, token_org_id
    from app.services.tenant_resolver import resolve_org_for_path

    token = make_token(email="someone@example.test", role="viewer", org_id=DEMO_ORG_ID)
    assert token_org_id(token) == DEMO_ORG_ID
    assert resolve_org_for_path("/api/v1/leads", token) == DEMO_ORG_ID

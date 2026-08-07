"""The test that justifies the multi-tenant work: rows must not cross orgs.

Everything else in the suite would still pass if the RLS policies were dropped
tomorrow — they exercise one org and never look for a second. These do the
opposite: they seed two organizations and try, deliberately, to reach across.

The catastrophic failure being guarded against is Agency A reading or writing
Agency B's leads. This repo has a documented history of exactly this bug shape
in another service: a field that was declared but never consumed, which sent
content to the wrong channel four separate times because the tests asserted the
value was *declared* rather than *used*. So none of these assert that a policy
exists — they assert that a hostile query comes back empty.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_engine, get_session_factory
from app.models import Lead
from app.models.lead import LeadStatus
from app.services.tenant_context import org_scope, set_org_id

ORG_A = 1
ORG_B = 2


async def _seed(phone: str, org_id: int) -> int:
    """Insert a lead directly, bypassing RLS, so both orgs have data to leak."""
    async with get_bypass_session_factory()() as db:
        lead = Lead(phone=phone, status=LeadStatus.NEW, org_id=org_id)
        db.add(lead)
        await db.commit()
        return lead.id


async def _cleanup(*phones: str) -> None:
    async with get_bypass_session_factory()() as db:
        for phone in phones:
            await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": phone})
        await db.commit()


@pytest.mark.asyncio
async def test_app_role_is_not_a_superuser() -> None:
    """A superuser ignores RLS even with FORCE, turning every test below green for free.

    This is the guard against a false green: if DATABASE_URL_APP is ever pointed
    at the owner or a superuser, the isolation tests would still pass while
    isolating nothing at all.
    """
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    assert row.rolsuper is False, "the app connects as a superuser — RLS is not enforced"
    assert row.rolbypassrls is False, "the app role has BYPASSRLS — RLS is not enforced"


@pytest.mark.asyncio
async def test_unfiltered_select_never_returns_another_org() -> None:
    await _seed("+19990000001", ORG_A)
    await _seed("+19990000002", ORG_B)
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                # No WHERE clause on purpose: this is the forgotten-filter case.
                rows = (await db.execute(select(Lead))).scalars().all()
        orgs = {r.org_id for r in rows}
        assert orgs <= {ORG_A}, f"rows from another org leaked: {orgs}"
        assert any(r.phone == "+19990000001" for r in rows), "own row disappeared"
        assert not any(r.phone == "+19990000002" for r in rows), "other org's row visible"
    finally:
        await _cleanup("+19990000001", "+19990000002")


@pytest.mark.asyncio
async def test_no_org_set_sees_nothing_rather_than_everything() -> None:
    """Default-deny. An unset org must fail closed, which is what makes a
    forgotten scope safe instead of catastrophic."""
    await _seed("+19990000003", ORG_A)
    try:
        with org_scope(None):
            async with get_session_factory()() as db:
                rows = (await db.execute(select(Lead))).scalars().all()
        assert rows == [], f"unset org returned {len(rows)} rows instead of none"
    finally:
        await _cleanup("+19990000003")


@pytest.mark.asyncio
async def test_cannot_write_into_another_org() -> None:
    """USING alone filters reads but still permits writes — this covers WITH CHECK."""
    from sqlalchemy.exc import DBAPIError

    with org_scope(ORG_A):
        async with get_session_factory()() as db:
            db.add(Lead(phone="+19990000004", status=LeadStatus.NEW, org_id=ORG_B))
            with pytest.raises(DBAPIError):
                await db.commit()
    await _cleanup("+19990000004")


@pytest.mark.asyncio
async def test_update_cannot_reach_another_org() -> None:
    await _seed("+19990000005", ORG_B)
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                await db.execute(
                    text("UPDATE leads SET phone = '+hijacked' WHERE phone = :p"),
                    {"p": "+19990000005"},
                )
                await db.commit()
        async with get_bypass_session_factory()() as db:
            still_there = (
                await db.execute(text("SELECT count(*) FROM leads WHERE phone = :p"), {"p": "+19990000005"})
            ).scalar_one()
        assert still_there == 1, "org A rewrote a row belonging to org B"
    finally:
        await _cleanup("+19990000005", "+hijacked")


@pytest.mark.asyncio
async def test_org_survives_repeated_commits_in_one_session() -> None:
    """`set_config(..., true)` is transaction-local and dies at COMMIT.

    Real flows commit several times per request — conversation.py commits five
    times, listings.py four — so binding the org once per session would leave
    every statement after the first commit with no org, seeing nothing. This is
    the direct test of the after_begin hook.
    """
    await _seed("+19990000006", ORG_A)
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                for round_ in range(3):
                    rows = (await db.execute(select(Lead))).scalars().all()
                    assert any(r.phone == "+19990000006" for r in rows), (
                        f"org context lost after {round_} commit(s)"
                    )
                    await db.commit()
    finally:
        await _cleanup("+19990000006")


@pytest.mark.asyncio
async def test_new_rows_are_stamped_with_the_acting_org() -> None:
    """Callers never set org_id by hand; the session stamps it on flush."""
    try:
        with org_scope(ORG_B):
            async with get_session_factory()() as db:
                lead = Lead(phone="+19990000007", status=LeadStatus.NEW)
                db.add(lead)
                await db.commit()
                assert lead.org_id == ORG_B
    finally:
        set_org_id(None)
        await _cleanup("+19990000007")

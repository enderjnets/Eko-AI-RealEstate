"""The landing analytics obey the tenant boundary.

A new tenant table without an RLS policy is readable by every tenant, and the
mistake is invisible: the application keeps working and the isolation tests
that exist keep passing, because they are about other tables.

What leaks here if the boundary is missing is one agency's marketing
performance — how much traffic their videos bring, where it comes from, and how
much of it converts. In a product sold to competing agencies in the same city,
that is the most commercially sensitive thing on the install.

Checked in both directions on purpose: a policy with `USING` but no
`WITH CHECK` passes a read test and still lets one agency write rows into
another's account.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import LandingEvent, LandingSession
from app.services.tenant_context import org_scope

ORG_A = 1
ORG_B = 2

KEY_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
KEY_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
NOW = datetime.now(UTC)


async def _seed(key: str, org_id: int) -> int:
    """Insert past RLS, so both agencies have something to leak."""
    async with get_bypass_session_factory()() as db:
        row = LandingSession(
            org_id=org_id,
            session_key=key,
            first_seen_at=NOW,
            last_seen_at=NOW,
            source="tiktok",
        )
        db.add(row)
        await db.flush()
        db.add(
            LandingEvent(org_id=org_id, session_id=row.id, type="page_view", at=NOW)
        )
        await db.commit()
        return row.id


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM landing_sessions WHERE session_key IN (:a, :b)"),
            {"a": KEY_A, "b": KEY_B},
        )
        await db.commit()


@pytest.fixture(autouse=True)
async def _clean() -> object:
    await _cleanup()
    yield
    await _cleanup()


async def test_one_agency_cannot_read_anothers_sessions() -> None:
    await _seed(KEY_A, ORG_A)
    await _seed(KEY_B, ORG_B)

    with org_scope(ORG_A):
        async with get_session_factory()() as db:
            keys = (
                await db.execute(select(LandingSession.session_key))
            ).scalars().all()

    assert KEY_A in keys
    assert KEY_B not in keys


async def test_one_agency_cannot_read_anothers_events() -> None:
    await _seed(KEY_A, ORG_A)
    session_b = await _seed(KEY_B, ORG_B)

    with org_scope(ORG_A):
        async with get_session_factory()() as db:
            visible = (
                await db.execute(
                    select(LandingEvent.session_id).where(
                        LandingEvent.session_id == session_b
                    )
                )
            ).scalars().all()

    assert visible == []


async def test_writing_into_another_agency_is_refused() -> None:
    """The `WITH CHECK` half. Without it, a handler that got its own binding
    wrong would file a visit under whichever organization it named."""
    from sqlalchemy.exc import DBAPIError

    with org_scope(ORG_A):
        async with get_session_factory()() as db:
            db.add(
                LandingSession(
                    org_id=ORG_B,
                    session_key=KEY_B,
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                    source="direct",
                )
            )
            with pytest.raises(DBAPIError):
                await db.commit()

    async with get_bypass_session_factory()() as db:
        found = (
            await db.execute(
                text("SELECT count(*) FROM landing_sessions WHERE session_key = :k"),
                {"k": KEY_B},
            )
        ).scalar_one()
    assert found == 0


async def test_the_purge_only_reaches_the_acting_agency() -> None:
    """The purge runs per organization on a sweep. If the policy did not apply
    to DELETE, one agency's tick would erase every agency's raw events."""
    from app.services.landing_analytics import purge_landing_events

    await _seed(KEY_A, ORG_A)
    await _seed(KEY_B, ORG_B)
    async with get_bypass_session_factory()() as db:
        await db.execute(text("UPDATE landing_events SET at = now() - interval '400 days'"))
        await db.commit()

    with org_scope(ORG_A):
        async with get_session_factory()() as db:
            deleted = await purge_landing_events(db)

    assert deleted == 1
    async with get_bypass_session_factory()() as db:
        survivors = (
            await db.execute(
                text(
                    "SELECT s.org_id FROM landing_events e "
                    "JOIN landing_sessions s ON s.id = e.session_id "
                    "WHERE s.session_key IN (:a, :b)"
                ),
                {"a": KEY_A, "b": KEY_B},
            )
        ).scalars().all()
    assert survivors == [ORG_B]

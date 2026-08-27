"""The backfill runs against data, so it is tested against data.

036's backfill shipped a severe defect with full CI green, because every test
upgrade ran it against an empty `follow_ups`. These tests import the repair
migration and execute its actual statement — not a paraphrase of it — against
seeded rows: one honestly held for a fortnight, one poisoned by an error
episode, one already settled. The statement is the thing under test.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.models import FollowUp, FollowUpKind, FollowUpStatus, Lead

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260820_1400_consent_holds_repair.py"
)


def _corrective_sql() -> str:
    spec = importlib.util.spec_from_file_location("repair_038", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.CORRECTIVE_SQL


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — backfill tests need live Postgres")
    return url


async def _seed(
    phone: str,
    *,
    holds: int,
    scheduled_days_ago: float,
    status: FollowUpStatus = FollowUpStatus.PENDING,
) -> int:
    async with get_bypass_session_factory()() as db:
        lead = Lead(phone=phone, org_id=1)
        db.add(lead)
        await db.flush()
        fu = FollowUp(
            org_id=1,
            lead_id=lead.id,
            kind=FollowUpKind.POST_VISIT_24H,
            status=status,
            scheduled_for=datetime.now(UTC) - timedelta(days=scheduled_days_ago),
            consent_holds=holds,
            postponed_until=datetime.now(UTC) - timedelta(minutes=1),
        )
        db.add(fu)
        await db.commit()
        return fu.id


async def _holds_of(fu_id: int) -> int:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT consent_holds FROM follow_ups WHERE id = :i"),
                {"i": fu_id},
            )
        ).scalar_one()


async def _cleanup(*phones: str) -> None:
    async with get_bypass_session_factory()() as db:
        for phone in phones:
            await db.execute(
                text(
                    "DELETE FROM follow_ups WHERE lead_id IN "
                    "(SELECT id FROM leads WHERE phone = :p)"
                ),
                {"p": phone},
            )
            await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": phone})
        await db.commit()


@pytest.mark.asyncio
async def test_the_repair_clamps_poisoned_counts_and_keeps_honest_ones(
    database_url: str,
) -> None:
    # Poisoned: one real hold plus thirteen error increments, two days old.
    # Fourteen holds cannot have happened in two days.
    poisoned = await _seed("+13035557801", holds=14, scheduled_days_ago=2)
    # Honest: fourteen daily holds over fifteen days. The ceiling must not
    # touch it — repairing the poisoned rows by shaving the honest ones would
    # hand out fresh fortnights, the same silent product change mirrored.
    honest = await _seed("+13035557802", holds=14, scheduled_days_ago=15)
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(text(_corrective_sql()))
            await db.commit()

        assert await _holds_of(poisoned) <= 3, (
            "a two-day-old row kept a fortnight of holds it cannot have had"
        )
        assert await _holds_of(honest) == 14, (
            "an honestly held row lost holds to the repair"
        )
    finally:
        await _cleanup("+13035557801", "+13035557802")


@pytest.mark.asyncio
async def test_the_clamp_is_right_at_the_edges(database_url: str) -> None:
    """The boundaries the first backfill got wrong are the ones pinned.

    A row scheduled in the future cannot have been held at all (its ceiling is
    zero); a row due today can have been held exactly once. Off-by-one here is
    a day of grace granted or stolen from every mid-hold lead at once.
    """
    future = await _seed("+13035557805", holds=5, scheduled_days_ago=-3)
    # 0.001 days (~86s ago), NOT 0: `scheduled_days_ago=0` seeds the row at
    # Python's now(), which sits exactly on the FLOOR discontinuity of the
    # corrective SQL — `1 + FLOOR((NOW() - scheduled_for)/86400)`. Postgres
    # evaluates NOW() on ITS clock, and whenever it trails Python's by even a
    # millisecond the floor lands on -1 and the ceiling on 0 instead of 1.
    # Measured: one red in a full run, green in isolation and on rerun. The
    # test's claim is "a row due today caps at one hold", not "a row due at
    # this exact instant", so a minute of slack loses nothing.
    today = await _seed("+13035557806", holds=5, scheduled_days_ago=0.001)
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(text(_corrective_sql()))
            await db.commit()
        assert await _holds_of(future) == 0, (
            "a future row kept holds it cannot have had yet"
        )
        assert await _holds_of(today) == 1, (
            "a row due today can have been held exactly once"
        )
    finally:
        await _cleanup("+13035557805", "+13035557806")


@pytest.mark.asyncio
async def test_the_repair_leaves_settled_rows_alone(database_url: str) -> None:
    """A SKIPPED row's count is history, and history is not repaired."""
    settled = await _seed(
        "+13035557803",
        holds=14,
        scheduled_days_ago=2,
        status=FollowUpStatus.SKIPPED,
    )
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(text(_corrective_sql()))
            await db.commit()
        assert await _holds_of(settled) == 14
    finally:
        await _cleanup("+13035557803")


@pytest.mark.asyncio
async def test_after_the_repair_the_second_hold_is_not_the_fifteenth(
    database_url: str,
) -> None:
    """The customer-facing point of the whole exercise.

    Before the repair, the first sweep after migration turned the poisoned
    row's next hold into give-up number fifteen and took the sequence with
    it. After the repair the sequence survives and keeps waiting.
    """
    from unittest.mock import patch

    from sqlalchemy import select

    from app.db.base import get_session_factory
    from app.services.followups import process_due_followups
    from app.services.tenant_context import org_scope

    poisoned = await _seed("+13035557804", holds=14, scheduled_days_ago=2)
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(text(_corrective_sql()))
            await db.commit()

        async def _ok(channel, *, to, text, **kwargs):  # noqa: ANN001, ANN202
            return "sm.x", None

        with org_scope(1):
            async with get_session_factory()() as db:
                with patch("app.services.followups._dispatch_send", _ok):
                    await process_due_followups(db)

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(FollowUp).where(FollowUp.id == poisoned)
                )
            ).scalar_one()
        assert row.status is FollowUpStatus.PENDING, (
            f"the repaired row was settled as {row.status} on the first sweep "
            "— the poisoned count survived the repair"
        )
    finally:
        await _cleanup("+13035557804")

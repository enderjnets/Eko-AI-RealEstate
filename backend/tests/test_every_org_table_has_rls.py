"""Every tenant table is protected, and nobody has to remember to check.

The isolation tests in this suite are per feature: one for the content rail,
one for call logs, one for the landing analytics. Each was written because
somebody thought of it. This one needs nobody to think of it — it walks the
mapped tables, finds the ones carrying `org_id`, and asks Postgres whether each
is actually protected.

There are two ways a table can be safe here, and both are in use:

  * row-level security, enabled AND forced, with at least one policy — the
    normal case, and what every tenant-owned table does;
  * no grants at all for the application role — `channel_routes` does this
    deliberately (migration 021): routing is resolved on a bypass session
    before any tenant is bound, so the app role has no business reading it and
    RLS could not express the rule anyway.

FORCE matters and is not redundant: the application connects as a role that is
not the tables' owner today, so ENABLE alone would still protect it — but the
day somebody points `DATABASE_URL_APP` at the owner to fix a permissions
error, every policy silently stops applying. That is not hypothetical; the
project's own CLAUDE.md warns about exactly that change.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.db.base import Base, get_bypass_session_factory

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def _org_tables() -> list[str]:
    return sorted(
        name
        for name, table in Base.metadata.tables.items()
        if "org_id" in table.columns
    )


async def test_the_sweep_sees_the_tables_it_claims_to() -> None:
    """A guard that walks an empty list passes for the wrong reason."""
    tables = _org_tables()
    assert len(tables) >= 14, tables
    for expected in ("leads", "messages", "landing_sessions", "landing_events"):
        assert expected in tables


@pytest.mark.parametrize("table", _org_tables())
async def test_a_tenant_table_is_either_locked_down_or_unreachable(table: str) -> None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity,
                           (SELECT count(*) FROM pg_policies p
                             WHERE p.schemaname = 'public' AND p.tablename = c.relname),
                           (SELECT count(*) FROM information_schema.table_privileges tp
                             WHERE tp.table_schema = 'public'
                               AND tp.table_name = c.relname
                               AND tp.grantee = :role)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = :t
                    """
                ),
                {"t": table, "role": APP_ROLE},
            )
        ).first()

    assert row is not None, f"{table} is mapped but not in the database"
    enabled, forced, policies, grants = row

    if grants == 0:
        # Unreachable by the application role. Nothing to isolate.
        return

    assert enabled, f"{table} is readable by the app role with RLS off"
    assert forced, f"{table} has RLS but not FORCE — an owner connection bypasses it"
    assert policies >= 1, f"{table} has RLS enabled and no policy: it denies everything"

"""Index the expression the sweep actually filters on.

Migration 032 added an index on `postponed_until` and claimed in its own comment
that this, plus the existing index on `scheduled_for`, "covers the pair". It does
not: Postgres cannot use an index on either column for a predicate on
`COALESCE(a, b)`. Measured at 50k follow-ups, the due query fell back to scanning
every PENDING row with the COALESCE as a filter — about ten times slower than the
single-column form, and the cost grows with the held backlog that the consent
hold is designed to accumulate. The index 032 added is used by nothing.

Partial on `status = 'pending'` because that is the only status the sweep asks
about, which keeps the index the size of the live queue rather than of history.

Revision ID: 034_due_index
Revises: 033_backfill_postponed
"""
from __future__ import annotations

from alembic import op

revision = "034_due_index"
down_revision = "033_backfill_postponed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_follow_ups_due
            ON follow_ups ((COALESCE(postponed_until, scheduled_for)))
         WHERE status = 'pending'
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_follow_ups_postponed_until")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_follow_ups_postponed_until "
        "ON follow_ups (postponed_until)"
    )
    op.execute("DROP INDEX IF EXISTS ix_follow_ups_due")

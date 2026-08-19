"""Make the deferrals that predate 032 explicit.

Migration 032 added `postponed_until` and left it NULL everywhere, on the
reasoning that NULL means "never postponed" and that was the state of every
existing row. True of the column, false of the data: a row that had already
been held carries a hold date in `scheduled_for`, so the promise 032 makes —
that `scheduled_for` says when a message was *for* — does not hold retroactively
for exactly the rows that most need it.

The consequence was a conjunct: the staleness rule had to add `attempts == 0` to
avoid cancelling those rows, which handed `attempts` a fourth meaning ("has
anything ever touched this") on top of the three it already carries — hold
count, error count, dispatch count. That is the one-column-two-meanings defect
032 set out to delete, relocated rather than removed.

Marking the old deferrals explicitly lets that conjunct go. The original due
date of an already-held row is not recoverable and is not reconstructed here;
what this fixes is that such a row now *says* it was deferred.

Revision ID: 033_backfill_postponed
Revises: 032_postponed_until
"""
from __future__ import annotations

from alembic import op

revision = "033_backfill_postponed"
down_revision = "032_postponed_until"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE follow_ups
           SET postponed_until = scheduled_for
         WHERE status = 'pending'
           AND attempts > 0
           AND postponed_until IS NULL
        """
    )


def downgrade() -> None:
    # Cannot distinguish a backfilled value from one written since, and the
    # column is nullable, so the safe reverse of this is to leave the data
    # alone. Dropping the column is 032's job.
    pass

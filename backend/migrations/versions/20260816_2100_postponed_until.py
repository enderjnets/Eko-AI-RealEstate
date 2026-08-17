"""Give a postponement its own column, so `scheduled_for` means one thing.

`follow_ups.scheduled_for` carried two meanings at once: *when this message was
for*, and *when to look at this row again*. The consent hold and the per-sweep
cap both overwrite it, so the first meaning was destroyed by the second — and
six rounds of audit produced a patch each time the difference mattered:

- the staleness rule could not tell a row nobody had looked at in a month from
  one that was deliberately deferred yesterday, so it needed a slack term
  guessed from constants, which was sized for one visit and silently cancelled
  "how did the visit go?" for a lead with three visits on the same day;
- the operator console could not tell a postponed row from one that is simply
  not due yet, so widening its filter to show the first flooded it with every
  future booking in the system.

Both dissolve once the two meanings have two columns. `scheduled_for` is never
written again after enqueue; `postponed_until` holds "look again after this".

Additive and reversible: the column is nullable with no default, and NULL means
"never postponed", which is exactly the state of every existing row.

Revision ID: 032_postponed_until
Revises: 031_normalise_ids
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "032_postponed_until"
down_revision = "031_normalise_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "follow_ups",
        sa.Column("postponed_until", sa.DateTime(timezone=True), nullable=True),
    )
    # The sweep reads `COALESCE(postponed_until, scheduled_for)` to decide what
    # is due, and both halves are already indexed alone; this covers the pair.
    op.create_index(
        "ix_follow_ups_postponed_until",
        "follow_ups",
        ["postponed_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_follow_ups_postponed_until", table_name="follow_ups")
    op.drop_column("follow_ups", "postponed_until")

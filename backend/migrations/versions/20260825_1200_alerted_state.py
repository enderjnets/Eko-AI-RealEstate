"""monitor_state.alerted_state: what the operator was actually told

`state` is what the watchdog last SAW. This is what it last managed to SAY.
They were the same column, and that was the bug: the tick committed `state`
whether or not the email went out, so a transport failure at the wrong moment
made the next tick see "no change" and never retry. An outage could be detected
and then permanently unreported — the failure mode a watchdog exists to prevent,
reproduced inside the watchdog.

**Only healthy rows are backfilled**, and the reason is the bug itself. It is
tempting to write `alerted_state = state` for every row on the grounds that the
old code alerted on the way into each state — but it did not: `row.state =
status` sat outside every conditional, so it advanced even when the send was
never attempted or was rejected. Copying it wholesale would stamp an unreported
outage as reported and, on the very next tick, `status != previous` would be
false: the alarm this migration exists to restore would be buried permanently,
by the migration that restores it.

So a row already `ok` is marked as told (nothing is owed, and a healthy install
must not greet its operator with an alert). Any other row is left NULL, which
under the new rules reads as an outstanding debt and gets delivered on the next
tick — which is exactly right, because it was never delivered.

Revision ID: 042_alerted_state
Revises: 041_monitor_state
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "042_alerted_state"
down_revision = "041_monitor_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitor_state",
        sa.Column("alerted_state", sa.String(length=30), nullable=True),
    )
    # Healthy rows only — see the module docstring. A row in any other state may
    # be carrying an alert that was never delivered, and NULL is what makes the
    # next tick deliver it.
    op.execute("UPDATE monitor_state SET alerted_state = state WHERE state = 'ok'")


def downgrade() -> None:
    op.drop_column("monitor_state", "alerted_state")

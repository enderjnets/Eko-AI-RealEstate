"""monitor_state.last_heartbeat_at: a process that says it is alive.

Every watcher so far measured something the backend could see for itself — a
provider answering, a message carrying a fallback stamp. The render worker is
the first watched thing that runs on ANOTHER MACHINE, and nothing here can
observe it: an idle worker and a dead worker produce identical evidence.

So it reports in, and this column is where that lands.

Not `last_seen_fallback_at`, which already exists and would have worked
mechanically: it means "the newest canned-reply message this sweep has
accounted for", and storing a heartbeat there would leave two unrelated facts
sharing a name that describes one of them. The next person to read it would be
right to be confused, and a column that lies is how a monitor ends up watching
something other than what its name says.

Shared table, no `org_id`, no RLS — same as the rest of `monitor_state`, whose
subject is the machinery rather than any tenant's data.

Revision ID: 047_monitor_heartbeat
Revises: 046_render_jobs
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "047_monitor_heartbeat"
down_revision = "046_render_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no backfill: NULL means "has never checked in", which is
    # the truth for every existing row and the correct starting state for a
    # worker that has not been installed yet.
    op.add_column(
        "monitor_state",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    # No GRANT: `eko_app` holds table-level DML on monitor_state (041), and
    # table-level privileges cover columns added later.


def downgrade() -> None:
    op.drop_column("monitor_state", "last_heartbeat_at")

"""monitor_state: what the watchdog saw last time

Holds the previous reading of each watched thing so an alert can fire on a
CHANGE rather than on the state, and so the daily alert budget survives a
restart (a crash-looping process must not get a fresh budget every boot).

**Deliberately not tenant-owned**: no `org_id`, no RLS policy — the same
decision as `properties` and `sync_state`, and for the same reason. The health
of this installation's LLM chain belongs to the installation, not to any one
agency, and giving it an `org_id` would mean every tenant carrying a copy of a
fact none of them owns.

Because migration 019 removed default privileges, a new table grants the app
role nothing until this file says so. That is the point of the design: the
grant and the isolation decision have to sit next to each other where a
reviewer can see that both were made on purpose.

Revision ID: 041_monitor_state
Revises: 040_publication_org_fk
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "041_monitor_state"
down_revision = "040_publication_org_fk"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def upgrade() -> None:
    op.create_table(
        "monitor_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=True),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "alerts_today", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("alerts_day", sa.String(length=10), nullable=True),
        sa.Column("last_seen_fallback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_monitor_state_key", "monitor_state", ["key"], unique=True
    )

    # No ENABLE ROW LEVEL SECURITY here on purpose — see the module docstring.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE monitor_state TO {APP_ROLE}"
    )
    op.execute(
        f"GRANT USAGE, SELECT ON SEQUENCE monitor_state_id_seq TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_state_key", table_name="monitor_state")
    op.drop_table("monitor_state")

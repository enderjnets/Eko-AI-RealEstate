"""lead_events: what happened to a lead, and when, and who did it.

Today a lead has a `status` and nothing else. Whether it went from `new` to
`qualified` an hour after arriving or three weeks later, whether a person moved
it or a phone call did, whether anybody ever called back — none of it is
recorded anywhere. The status column is a photograph; this is the film.

The questions it exists to answer are the ones the owner asked for and that
`/analytics` cannot currently touch: how long from a lead arriving to somebody
answering, how many were called back at all, how many appointments were set and
how many happened, and how long a deal takes from first contact to closed.

**Append-only by intention.** Nothing here is ever updated: a wrong event is
followed by another event, never edited, because the value of a history is that
it did not change after the fact.

`actor` is a free-text label rather than a foreign key to a user. It holds an
email when a person did it, `"vapi"` when the call agent did, `"system"` when a
loop did — and staff come and go while the history has to outlive them. A
deleted user must not take the record of what they did with them.

`from_status`/`to_status` are text, not the enum. An enum here would mean a
migration every time the funnel gains a state, and worse, renaming a state
would silently rewrite what the past says happened.

Revision ID: 052_lead_events
Revises: 051_landing_sessions
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "052_lead_events"
down_revision = "051_landing_sessions"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "lead_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Text everywhere a value could grow: an `ended_reason` VAPI invents
        # next month must not become a 500 on a webhook nobody is watching.
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_lead_events_org_id", "lead_events", ["org_id"])
    op.create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])
    # The two shapes every report uses: a range for one agency, and one lead's
    # timeline. Without the second, a lead page scans the whole table.
    op.create_index("ix_lead_events_org_at", "lead_events", ["org_id", "at"])
    op.create_index("ix_lead_events_lead_at", "lead_events", ["lead_id", "at"])
    _rls("lead_events")


def downgrade() -> None:
    op.drop_index("ix_lead_events_lead_at", table_name="lead_events")
    op.drop_index("ix_lead_events_org_at", table_name="lead_events")
    op.drop_index("ix_lead_events_lead_id", table_name="lead_events")
    op.drop_index("ix_lead_events_org_id", table_name="lead_events")
    op.drop_table("lead_events")

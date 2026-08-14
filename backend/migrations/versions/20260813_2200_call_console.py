"""Call console — log a call, and let the outcome do the work.

Adds:
  * `call_logs`, one row per call the office logs, under default-deny RLS like
    every other tenant-owned table.
  * `leads.preferred_channel` — the channel the person asked for. It narrows
    the follow-up worker's candidates; it never widens them, and it is not
    consent.
  * `visits.property_id` — which listing a showing is for, so the post-visit
    message can name the house.
  * `follow_ups.call_log_id` plus UNIQUE(call_log_id, kind), which keeps
    `enqueue_after_call` idempotent for a *given* call row — the existing
    UNIQUE(visit_id, kind) cannot, because Postgres treats two NULLs as
    distinct and a call-anchored row has no visit.
    It does NOT stop a double-submit: each POST mints a new call_log_id, so two
    rapid identical submits are two calls and two nudges. That is handled in
    `calls.register_call`, which cancels the lead's outstanding call-tasks
    before queueing the new one.
  * `call_follow_up` on the follow_up_kind enum.

Additive throughout; nothing existing changes shape, and every new column is
nullable, so the running app keeps working until the code that reads them
deploys.

Revision ID: 029_call_console
Revises: 028_lead_opt_out
Create Date: 2026-08-13
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "029_call_console"
down_revision = "028_lead_opt_out"
branch_labels = None
depends_on = None

# Migration 017 revoked the blanket grants and set default privileges for this
# role instead, so a table created here inherits them. Granting explicitly
# anyway costs nothing and removes the dependency on which role happens to run
# the migration — get that wrong and the app cannot read its own new table.
APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

CALL_OUTCOMES = (
    "wants_listings",
    "booked_visit",
    "follow_up",
    "no_answer",
    "has_agent",
    "do_not_contact",
    "wrong_number",
)

PREFERRED_CHANNELS = ("sms", "email", "call")


def upgrade() -> None:
    # Created here, then referenced with create_type=False everywhere below.
    # sa.Enum silently ignores create_type, so leaving it to the column
    # definitions makes CREATE TYPE run twice and the migration abort.
    sa.Enum(*CALL_OUTCOMES, name="call_outcome").create(op.get_bind(), checkfirst=True)
    sa.Enum(*PREFERRED_CHANNELS, name="preferred_channel").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "call_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "org_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("logged_by", sa.String(length=254), nullable=True),
        sa.Column(
            "outcome",
            postgresql.ENUM(*CALL_OUTCOMES, name="call_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_call_logs_org_id", "call_logs", ["org_id"])
    op.create_index("ix_call_logs_lead_id", "call_logs", ["lead_id"])
    op.create_index("ix_call_logs_outcome", "call_logs", ["outcome"])

    # Default-deny isolation, same shape as every other tenant table. Without
    # this the table is readable by every agency on the install.
    op.execute("ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY call_logs_tenant_isolation ON call_logs
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE call_logs TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE call_logs_id_seq TO {APP_ROLE}")

    op.add_column(
        "leads",
        sa.Column(
            "preferred_channel",
            postgresql.ENUM(
                *PREFERRED_CHANNELS, name="preferred_channel", create_type=False
            ),
            nullable=True,
        ),
    )

    op.add_column(
        "visits",
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_visits_property_id", "visits", ["property_id"])

    op.add_column(
        "follow_ups",
        sa.Column(
            "call_log_id",
            sa.Integer(),
            sa.ForeignKey("call_logs.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_follow_ups_call_log_id", "follow_ups", ["call_log_id"])
    op.create_unique_constraint(
        "uq_followups_call_kind", "follow_ups", ["call_log_id", "kind"]
    )

    # Postgres allows ADD VALUE inside a transaction since 12; the new label
    # just cannot be *used* until this commits, and nothing here uses it.
    op.execute("ALTER TYPE follow_up_kind ADD VALUE IF NOT EXISTS 'call_follow_up'")


def downgrade() -> None:
    # Delete the call-anchored follow-ups BEFORE dropping the column that
    # anchors them. Dropping it first leaves rows whose `call_log_id` is gone;
    # re-applying this migration then re-adds the column as NULL, and a
    # `call_log_id != n` filter can never match NULL — so those rows become
    # permanently uncancellable while still being dispatchable. A down-and-up
    # cycle produced thirteen of them.
    op.execute("DELETE FROM follow_ups WHERE kind = 'call_follow_up'")

    op.drop_constraint("uq_followups_call_kind", "follow_ups", type_="unique")
    op.drop_index("ix_follow_ups_call_log_id", table_name="follow_ups")
    op.drop_column("follow_ups", "call_log_id")

    op.drop_index("ix_visits_property_id", table_name="visits")
    op.drop_column("visits", "property_id")

    op.drop_column("leads", "preferred_channel")

    op.drop_index("ix_call_logs_outcome", table_name="call_logs")
    op.drop_index("ix_call_logs_lead_id", table_name="call_logs")
    op.drop_index("ix_call_logs_org_id", table_name="call_logs")
    op.drop_table("call_logs")

    sa.Enum(name="call_outcome").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="preferred_channel").drop(op.get_bind(), checkfirst=True)

    # `call_follow_up` stays on follow_up_kind. Postgres cannot remove an enum
    # label, and rebuilding the type would mean rewriting every follow_ups row
    # — a destructive operation to undo an additive one. A label nothing writes
    # is inert; leaving it is the safe end of that trade.

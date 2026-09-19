"""The ask for options, as a row a person can work.

We have no MLS API. REcolorado's data leaves Matrix by hand, under Natalia's own
subscription, against an allowance this migration's author read off her screen
on 2026-09-19: 500 records every 30 days, 0 spent, and the fine for abusing it
lands on her licence rather than on this software. So "send me some options"
cannot be a function call — it is a piece of work with a state, and this is the
table that holds it.

The partial unique index is the load-bearing part. One open ask per lead, in the
database, because the alternative is that whoever is writing to `hello@` decides
how much of her allowance gets spent: four emails in four minutes would be four
searches. Code that checks first is not enough on its own — two workers race,
and the index is what makes the rule true anyway.

Revision ID: 064_listing_requests
Revises: 063_content_rejections
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "064_listing_requests"
down_revision = "063_content_rejections"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

STATUSES = (
    "open",
    "sent",
    "more_requested",
    "callback_requested",
    "cancelled",
)


def _isolate(table: str) -> None:
    """The same default-deny policy every tenant table here carries."""
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
    status = postgresql.ENUM(*STATUSES, name="listing_request_status")
    status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "listing_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.BigInteger(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="listing_request_status", create_type=False),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "origin", sa.String(length=20), server_default="message", nullable=False
        ),
        # Ids only. The listing facts live in `properties`; a copy here would be
        # a second, stale, unattributed copy of another broker's data.
        sa.Column(
            "selected_property_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("callback_text", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_listing_requests_lead_id", "listing_requests", ["lead_id"])
    op.create_index("ix_listing_requests_status", "listing_requests", ["status"])
    op.create_index(
        "ix_listing_requests_org_created", "listing_requests", ["org_id", "created_at"]
    )
    # The rule, in the database. Not per-org on purpose: a lead belongs to one
    # organization, so `lead_id` alone is the right grain, and scoping it wider
    # would let the same lead hold two open asks under two tenants.
    op.execute(
        "CREATE UNIQUE INDEX uq_listing_requests_one_open "
        "ON listing_requests (lead_id) WHERE status = 'open'"
    )
    _isolate("listing_requests")


def downgrade() -> None:
    op.drop_table("listing_requests")
    postgresql.ENUM(name="listing_request_status").drop(op.get_bind(), checkfirst=True)

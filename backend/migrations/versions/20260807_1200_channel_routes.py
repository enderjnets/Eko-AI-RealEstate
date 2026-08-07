"""channel_routes: attribute inbound messages to the right agency

Without this, `tenant_resolver` had nothing to route on and every inbound
message went to the default organization — a second agency's leads and their
whole conversation transcript landed in the first agency's dashboard, while the
real recipient saw nothing and their follow-ups never fired. It now refuses
rather than guessing, which is safe but also means a second tenant cannot be
onboarded until a mapping exists. This is that mapping.

RLS deliberately does NOT cover this table. Routing has to be resolved before
any organization is bound — that is the whole problem it solves — so it is read
on the bypass session, and only platform operators can write it. Uniqueness is
global per channel: a phone number belongs to exactly one agency, and two
claiming it is the ambiguity the table exists to prevent.

Revision ID: 020_channel_routes
Revises: 019_default_privs_closed
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "020_channel_routes"
down_revision = "019_default_privs_closed"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def upgrade() -> None:
    op.create_table(
        "channel_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "org_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("destination", sa.String(length=254), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_channel_routes_org_id", "channel_routes", ["org_id"])
    op.create_index(
        "uq_channel_routes_dest", "channel_routes", ["channel", "destination"], unique=True
    )
    # Migration 019 removed default privileges, so grants are stated beside the
    # table that needs them. Read-only for the app role: routes are platform
    # configuration, written through the operator's bypass session.
    op.execute(f"GRANT SELECT ON channel_routes TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("uq_channel_routes_dest", table_name="channel_routes")
    op.drop_index("ix_channel_routes_org_id", table_name="channel_routes")
    op.drop_table("channel_routes")

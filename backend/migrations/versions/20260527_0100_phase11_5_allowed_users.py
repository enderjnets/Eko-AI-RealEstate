"""allowed_users — DB-backed access list for Google Sign In (email + role)

Moves the Google Sign In allow-list out of env vars into a table so admins can
manage who logs in (and with what role) from the Settings → Team panel without a
redeploy. Bootstrap admins (GOOGLE_ADMIN_EMAILS) are seeded here on startup.

Revision ID: 008_allowed_users
Revises: 007_phase12_widen_phone
Create Date: 2026-05-27 01:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_allowed_users"
down_revision: Union[str, None] = "007_phase12_widen_phone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allowed_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("added_by", sa.String(length=254), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_allowed_users_email", "allowed_users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_allowed_users_email", table_name="allowed_users")
    op.drop_table("allowed_users")

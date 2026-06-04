"""user_activity — per-user engagement aggregate (email-keyed)

One row per known user (session email). Lightweight middleware + login hooks
update it. Aggregate only, so admins can see logins / last seen / sections /
device per registered user.

Revision ID: 013_user_activity
Revises: 012_accounts
Create Date: 2026-06-04 15:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_user_activity"
down_revision: Union[str, None] = "012_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_active_day", sa.Date(), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_ip", sa.String(length=64), nullable=True),
        sa.Column("last_user_agent", sa.String(length=400), nullable=True),
        sa.Column("device", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_activity_email", "user_activity", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_activity_email", table_name="user_activity")
    op.drop_table("user_activity")

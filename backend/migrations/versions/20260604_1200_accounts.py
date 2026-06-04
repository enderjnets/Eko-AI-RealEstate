"""accounts — self-registered read-only ("viewer") demo users (email + password)

Public /register creates a row here so prospective clients can sign in and browse
the dashboard read-only. Separate from allowed_users (the Google/Apple allow-list,
no password).

Revision ID: 012_accounts
Revises: 011_visit_manual_events
Create Date: 2026-06-04 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_accounts"
down_revision: Union[str, None] = "011_visit_manual_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="viewer"),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("address", sa.String(length=280), nullable=True),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_accounts_email", table_name="accounts")
    op.drop_table("accounts")

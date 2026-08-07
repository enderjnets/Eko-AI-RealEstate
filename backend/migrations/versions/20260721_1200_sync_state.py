"""sync_state — replication cursor + run metadata for external data feeds

One row per feed source (e.g. "reso"). The listings sync worker persists the last
processed ModificationTimestamp here so it can fetch only the delta (MLS Grid
replication) and resume crash-safely from the last durable point.

Revision ID: 014_sync_state
Revises: 013_user_activity
Create Date: 2026-07-21 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_sync_state"
down_revision: Union[str, None] = "013_user_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("cursor_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_state_source", "sync_state", ["source"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sync_state_source", table_name="sync_state")
    op.drop_table("sync_state")

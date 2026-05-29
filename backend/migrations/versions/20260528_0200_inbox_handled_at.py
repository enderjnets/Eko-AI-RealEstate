"""inbox handled state — add leads.inbox_handled_at (move out of meta JSON)

Replaces the meta["inbox"]["handled_at"] JSON blob with a real, typed column so
marking a lead handled never races with other writers to meta (e.g. discovery
enrichment) via whole-dict reassignment. Backfills the column from any existing
meta value.

Revision ID: 009_inbox_handled_at
Revises: 008_allowed_users
Create Date: 2026-05-28 02:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_inbox_handled_at"
down_revision: Union[str, None] = "008_allowed_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("inbox_handled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill from the legacy meta JSON (json `->>` works on the json column).
    op.execute(
        """
        UPDATE leads
        SET inbox_handled_at = (meta -> 'inbox' ->> 'handled_at')::timestamptz
        WHERE meta -> 'inbox' ->> 'handled_at' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("leads", "inbox_handled_at")

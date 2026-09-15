"""A post that went out and is no longer visible.

Five videos — pieces 52 to 56, the "Renting at $X a month" series — were set to
private on YouTube by the owner on 15-sep-2026 because their figures did not
reproduce. The rows still read `published` with a live `external_url`, so the
count said twenty-three published where five could not be opened by anybody,
and the follow-up comment pointed at a page from a video nobody can watch.

`published` stays true: they were published, and rewriting that would lose the
fact that they were public for three days carrying a wrong number. What was
missing is the second fact, which is about the present rather than the past.

Nullable and per publication, not per piece: the same piece is private on
YouTube and still live on TikTok, so a flag on the piece would be false on two
platforms out of three.

Revision ID: 062_publication_withdrawn
Revises: 061_piece_calculator_check
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "062_publication_withdrawn"
down_revision = "061_piece_calculator_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_publications",
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "content_publications",
        sa.Column("withdrawn_reason", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_publications", "withdrawn_reason")
    op.drop_column("content_publications", "withdrawn_at")

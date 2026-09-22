"""Persist the editorial line and date without rewriting the live Buffer queue.

Revision ID: 067_content_series
Revises: 066_request_suggestions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "067_content_series"
down_revision = "066_request_suggestions"
branch_labels = None
depends_on = None

VALUES = (
    "conversion",
    "denver_decoded",
    "denver_weekend",
    "denver_market_no_hype",
    "ask_denver_home_story",
)


def upgrade() -> None:
    series = postgresql.ENUM(*VALUES, name="content_series")
    series.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "content_pieces",
        sa.Column("series", series, nullable=False, server_default="conversion"),
    )
    op.add_column("content_pieces", sa.Column("editorial_date", sa.Date(), nullable=True))
    op.add_column(
        "content_pieces",
        sa.Column("source", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_content_pieces_series", "content_pieces", ["series"])
    op.create_index(
        "ix_content_pieces_editorial_date", "content_pieces", ["editorial_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_content_pieces_editorial_date", table_name="content_pieces")
    op.drop_index("ix_content_pieces_series", table_name="content_pieces")
    op.drop_column("content_pieces", "source")
    op.drop_column("content_pieces", "editorial_date")
    op.drop_column("content_pieces", "series")
    postgresql.ENUM(*VALUES, name="content_series").drop(op.get_bind(), checkfirst=True)

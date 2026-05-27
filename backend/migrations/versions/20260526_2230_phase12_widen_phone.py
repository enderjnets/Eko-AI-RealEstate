"""widen leads.phone 32 → 254 to match the model (generic identifier)

The `phone` column is a generic lead identifier (Phase 3): phone numbers,
emails, websites, or — for discovery-sourced businesses with no contact — a
synthetic key. The model declared String(254) since Phase 3 but no migration
ever actually altered the column, which stayed VARCHAR(32). Discovery imports
of LinkedIn URLs / synthetic keys exceed 32 chars and raised
StringDataRightTruncationError. This aligns the DB with the model.

Revision ID: 007_phase12_widen_phone
Revises: 006_phase10_followups
Create Date: 2026-05-26 22:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_phase12_widen_phone"
down_revision: Union[str, None] = "006_phase10_followups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "leads", "phone",
        existing_type=sa.String(length=32),
        type_=sa.String(length=254),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "leads", "phone",
        existing_type=sa.String(length=254),
        type_=sa.String(length=32),
        existing_nullable=False,
    )

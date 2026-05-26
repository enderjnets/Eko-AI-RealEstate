"""phase8 lead score — add leads.score + score_breakdown for lead intelligence

Revision ID: 005_phase8_lead_score
Revises: 004_phase7_properties
Create Date: 2026-05-26 00:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_phase8_lead_score"
down_revision: Union[str, None] = "004_phase7_properties"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("score", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "leads",
        sa.Column("score_breakdown", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_leads_score", "leads", ["score"], unique=False)
    # Drop the server_defaults now that existing rows are backfilled — the ORM
    # supplies the values going forward.
    op.alter_column("leads", "score", server_default=None)
    op.alter_column("leads", "score_breakdown", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_leads_score", table_name="leads")
    op.drop_column("leads", "score_breakdown")
    op.drop_column("leads", "score")

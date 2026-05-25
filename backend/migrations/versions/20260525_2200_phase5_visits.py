"""phase5 visits — visits table for property-visit bookings

Revision ID: 003_phase5_visits
Revises: 002_phase3_multichannel
Create Date: 2026-05-25 22:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_phase5_visits"
down_revision: Union[str, None] = "002_phase3_multichannel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("calendar_provider", sa.String(length=20), nullable=False),
        sa.Column("external_booking_id", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum("scheduled", "confirmed", "cancelled", "completed", "no_show", name="visit_status"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=50), nullable=False),
        sa.Column("property_address", sa.String(length=280), nullable=True),
        sa.Column("meeting_url", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_booking_id", name="uq_visits_external_booking_id"),
    )
    op.create_index("ix_visits_lead_id", "visits", ["lead_id"], unique=False)
    op.create_index("ix_visits_status", "visits", ["status"], unique=False)
    op.create_index("ix_visits_scheduled_at", "visits", ["scheduled_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_visits_scheduled_at", table_name="visits")
    op.drop_index("ix_visits_status", table_name="visits")
    op.drop_index("ix_visits_lead_id", table_name="visits")
    op.drop_table("visits")
    op.execute("DROP TYPE IF EXISTS visit_status")

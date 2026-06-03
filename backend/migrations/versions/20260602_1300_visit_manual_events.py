"""visits: nullable lead_id + title — support manual calendar events

A manual calendar event (open house, team meeting, ...) created by the realtor
from the Calendar tab is a Visit with no lead and a free-text title. Lead
property-visits keep their lead_id. Makes leads.lead_id nullable + adds title.

Revision ID: 011_visit_manual_events
Revises: 010_agent_settings_timezone
Create Date: 2026-06-02 13:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_visit_manual_events"
down_revision: Union[str, None] = "010_agent_settings_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("visits", sa.Column("title", sa.String(length=200), nullable=True))
    op.alter_column("visits", "lead_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Remove manual events (no lead) before restoring the NOT NULL constraint.
    op.execute("DELETE FROM visits WHERE lead_id IS NULL")
    op.alter_column("visits", "lead_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("visits", "title")

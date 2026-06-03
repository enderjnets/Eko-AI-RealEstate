"""agent_settings.timezone — office IANA timezone for booking + display

The voice agent hears local times ("2 PM") and visits are shown to the realtor;
both need the office timezone so "2 PM" is stored as 2 PM local (not UTC) and
rendered consistently. Adds a NOT NULL column defaulting to "UTC"; the Settings
page auto-detects the browser tz on first load.

Revision ID: 010_agent_settings_timezone
Revises: 009_inbox_handled_at
Create Date: 2026-06-02 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_agent_settings_timezone"
down_revision: Union[str, None] = "009_inbox_handled_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_settings",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
    )
    # Drop the server_default so the model's app-level default governs new rows.
    op.alter_column("agent_settings", "timezone", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_settings", "timezone")

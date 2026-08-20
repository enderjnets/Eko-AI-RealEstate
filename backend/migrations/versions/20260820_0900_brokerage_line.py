"""Somewhere to put the brokerage identification advertising has to carry.

Colorado requires a licensed agent's advertising to identify the brokerage they
work under. That is not decoration on a video, it is the condition on which the
video is allowed to exist, and the exposure lands on the agent's licence rather
than on ours.

Nullable with no default, deliberately. The exact wording is a legal question
the brokerage answers; a placeholder would read as an answer and ship as one.
The publish gate refuses while it is NULL, so an unanswered question stops
content rather than releasing it unlabelled.

Revision ID: 037_brokerage_line
Revises: 036_consent_holds
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "037_brokerage_line"
down_revision = "036_consent_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_settings",
        sa.Column("brokerage_line", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_settings", "brokerage_line")

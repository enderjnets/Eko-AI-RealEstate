"""Persist conservative traffic classification without rewriting history.

The raw user agent is deliberately discarded when a landing session is
created. Classification therefore belongs on that first insert: retaining only
the result lets Analytics omit unequivocal automation while preserving the
privacy boundary of the original table.

Existing sessions stay ``unknown`` and remain counted. No behavior, geography,
event count, or scroll heuristic can safely distinguish automation; a prior
form bug made six real sessions record exactly 37 starts. Only explicit QA and
closed automated signals get a class other than ``unknown``.

Revision ID: 060_landing_traffic_class
Revises: 059_partner_briefs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "060_landing_traffic_class"
down_revision = "059_partner_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "landing_sessions",
        sa.Column(
            "traffic_class",
            sa.Text(),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "landing_sessions",
        sa.Column("traffic_class_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "landing_sessions",
        sa.Column("traffic_classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_landing_sessions_traffic_class",
        "landing_sessions",
        "traffic_class IN ('unknown', 'automated', 'test')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_landing_sessions_traffic_class",
        "landing_sessions",
        type_="check",
    )
    op.drop_column("landing_sessions", "traffic_classified_at")
    op.drop_column("landing_sessions", "traffic_class_reason")
    op.drop_column("landing_sessions", "traffic_class")

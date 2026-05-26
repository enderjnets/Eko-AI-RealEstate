"""phase10 follow_ups — scheduled nurture messages (post-visit + reminders)

Revision ID: 006_phase10_followups
Revises: 005_phase8_lead_score
Create Date: 2026-05-26 04:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_phase10_followups"
down_revision: Union[str, None] = "005_phase8_lead_score"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = ("reminder_24h", "post_visit_24h", "post_visit_72h", "post_visit_7d")
_STATUSES = ("pending", "sent", "skipped", "cancelled", "failed")


def upgrade() -> None:
    bind = op.get_bind()
    kind = postgresql.ENUM(*_KINDS, name="follow_up_kind")
    status = postgresql.ENUM(*_STATUSES, name="follow_up_status")
    kind.create(bind, checkfirst=True)
    status.create(bind, checkfirst=True)

    op.create_table(
        "follow_ups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=True),
        sa.Column("kind", postgresql.ENUM(*_KINDS, name="follow_up_kind", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM(*_STATUSES, name="follow_up_status", create_type=False), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("visit_id", "kind", name="uq_followups_visit_kind"),
    )
    op.create_index("ix_follow_ups_lead_id", "follow_ups", ["lead_id"], unique=False)
    op.create_index("ix_follow_ups_visit_id", "follow_ups", ["visit_id"], unique=False)
    op.create_index("ix_follow_ups_status", "follow_ups", ["status"], unique=False)
    op.create_index("ix_follow_ups_scheduled_for", "follow_ups", ["scheduled_for"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_follow_ups_scheduled_for", table_name="follow_ups")
    op.drop_index("ix_follow_ups_status", table_name="follow_ups")
    op.drop_index("ix_follow_ups_visit_id", table_name="follow_ups")
    op.drop_index("ix_follow_ups_lead_id", table_name="follow_ups")
    op.drop_table("follow_ups")
    op.execute("DROP TYPE IF EXISTS follow_up_status")
    op.execute("DROP TYPE IF EXISTS follow_up_kind")

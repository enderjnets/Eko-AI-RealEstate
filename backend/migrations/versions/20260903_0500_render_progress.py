"""render_jobs.stage/progress + monitor_state.detail: what the render is doing.

The console said "the video is still being made" whether the job was queued,
claimed, or waiting for the render machine's hour window — so the owner watched
a spinner for an hour while nothing was, in fact, being made. These columns let
the panel say which of those three is true, and how far along.

Revision ID: 049_render_progress
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "049_render_progress"
down_revision = "048_content_scenes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable and unbackfilled on purpose: NULL means "this job never reported
    # a stage", which is the truth for every row that predates this.
    op.add_column("render_jobs", sa.Column("stage", sa.String(40), nullable=True))
    op.add_column("render_jobs", sa.Column("progress", sa.SmallInteger(), nullable=True))
    # Shared, unscoped table — like the rest of monitor_state. Holds what the
    # worker says about itself: whether this tick fell inside its hours, and
    # which hours those are, so the panel can name the wait instead of hiding it.
    op.add_column(
        "monitor_state",
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitor_state", "detail")
    op.drop_column("render_jobs", "progress")
    op.drop_column("render_jobs", "stage")

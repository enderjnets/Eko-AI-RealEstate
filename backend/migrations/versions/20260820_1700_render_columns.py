"""Where a render records that it happened, or why it could not.

`rendered_at` is what stops the render loop reprocessing the same clip for
ever: NULL means "not rendered yet", and nothing else does — inferring it from
the filename or the piece's status would put the answer somewhere a person
editing the piece could accidentally change it.

`render_error` is the failure surfaced instead of buried. A clip the renderer
cannot process (truncated file, no video stream, forty minutes long) must show
its reason in the console next to the piece; a log line on the ROG is where
that information goes to die. A row with `rendered_at` set AND `render_error`
set means "tried, failed, not worth retrying until the file changes" — the
loop skips it, a person reads the reason and replaces the clip.

Additive and nullable; every existing row means "never rendered", which is
true.

Revision ID: 039_render_columns
Revises: 038_consent_holds_repair
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "039_render_columns"
down_revision = "038_consent_holds_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_pieces",
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "content_pieces",
        sa.Column("render_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_pieces", "render_error")
    op.drop_column("content_pieces", "rendered_at")

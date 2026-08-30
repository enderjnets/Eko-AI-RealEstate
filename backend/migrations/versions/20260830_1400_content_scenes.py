"""content_pieces.scenes: the shot list a generated video is built from.

Lane A takes a clip somebody filmed. Lane B has no clip — it has a script, and
something has to decide what is ON SCREEN while that script is read. That plan
is written when the draft is written, by the same model, under the same gates:
each `visual_prompt` passes the Fair Housing phrase filter AND a denylist of
person descriptors, because housing advertising is regulated in pictures too
and a video whose every frame shows one kind of household says who is welcome
without a sentence anybody could edit in review.

JSONB and not a table. These rows are read whole, written whole, and never
queried across pieces; a `render_scenes` table would buy joins nobody needs and
a second thing to keep in step with the draft it belongs to.

NULL means "no plan", which is the honest state for every piece that exists
today and for any clip somebody films: lane A does not need one.

Revision ID: 048_content_scenes
Revises: 047_monitor_heartbeat
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "048_content_scenes"
down_revision = "047_monitor_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_pieces", sa.Column("scenes", JSONB(), nullable=True))
    # No GRANT and no policy: `content_pieces` already carries the org policy,
    # and `eko_app` holds table-level DML on it, which covers a new column.

    # And the repair that comes with it. `violations` was declared without
    # `none_as_null`, so a piece with nothing wrong stored the JSON value
    # `null` rather than SQL NULL. Reading the row back gives None either way —
    # which is why it went unnoticed — but `violations IS NULL` matched zero
    # rows, and the sweep that queues a video for a clean draft therefore found
    # nothing to do, forever. The model now sets the flag; these are the rows
    # written before it did.
    op.execute("UPDATE content_pieces SET violations = NULL WHERE violations = 'null'::jsonb")


def downgrade() -> None:
    op.drop_column("content_pieces", "scenes")

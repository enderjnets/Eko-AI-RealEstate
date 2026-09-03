"""content_publications: scheduled_at + external_url, and a SCHEDULED status.

Until now an approved piece went out with `shareNow` on the next tick of the
publish loop, so "when will this be published?" had no answer to give: on
3-sep six posts left in 107 seconds. The console cannot show a date until one
exists, and one only exists if there is a queue. `scheduled_at` is that date.

`external_url` arrives with it because the same Buffer query that tells us a
post went out also returns the real platform link, and a piece that has been
published with nowhere to click is a piece that vanishes from the console.

Revision ID: 050_publication_schedule
"""

from alembic import op
import sqlalchemy as sa

revision = "050_publication_schedule"
down_revision = "049_render_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A row that Buffer has accepted and holds for a future time. It is NOT a
    # terminal state: `_close_piece` keeps the piece in PUBLISHING until Buffer
    # confirms, which is also what stops anyone editing the text out from under
    # a post that is already queued.
    #
    # `ADD VALUE` outside a transaction block is only required when the new
    # label is USED in the same transaction, which it is not here — the column
    # below is added empty and the first write happens in a later request.
    op.execute("ALTER TYPE publication_status ADD VALUE IF NOT EXISTS 'scheduled'")

    # Nullable and unbackfilled: NULL means "this row was never scheduled",
    # which is the truth for the fifteen rows that went out with shareNow.
    op.add_column(
        "content_publications",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Text for the same reason `external_id` is Text: the platform decides this
    # length, and a clipped URL is a wrong URL rather than a short one.
    op.add_column(
        "content_publications", sa.Column("external_url", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("content_publications", "external_url")
    op.drop_column("content_publications", "scheduled_at")
    # The enum label stays. Postgres cannot DROP a value from an enum type, and
    # rebuilding the type to remove one would have to rewrite every row of a
    # table this migration did not create.

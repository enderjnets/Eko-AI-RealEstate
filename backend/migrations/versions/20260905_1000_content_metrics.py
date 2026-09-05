"""content_metrics: how many people actually watched each video.

Everything the funnel knows today starts at the landing page. What happened
*before* the visit — whether a video was seen a hundred times or four — is
invisible, so a piece that reached nobody and a piece that reached thousands
and persuaded nobody look identical from here. They are opposite problems and
they need opposite fixes.

**A row per publication per day, not a running column on the publication.** A
single `views` column would answer "how many now" and destroy the only
interesting question: whether a video is still being watched a week later.
Shorts get most of their reach in the first days, so the shape of the curve is
the signal, and a curve needs history. `UNIQUE (publication_id, captured_on)`
makes the day the unit: a tick that runs four times a day overwrites its own
snapshot instead of inventing four data points.

`captured_on` is a **date in the agency's zone**, not a timestamp. It is the
label of a bucket ("what YouTube said on the 5th"), and the count itself is
cumulative-since-publication, so the precise instant of the reading carries no
information worth the confusion of a timestamp.

`source` separates what a machine read from what a person typed. TikTok and
Instagram do not expose view counts to anything short of a first-party app with
platform review, so those numbers are hand-entered and must never be presented
with the same confidence as YouTube's. A mixed column with no provenance is how
a hand-typed guess ends up in a report as a measurement.

`views/likes/comments` are all nullable: YouTube omits `likeCount` when a
channel hides likes and `commentCount` when comments are off. Nullable says
"not published by the platform"; a zero would say "nobody liked it", and those
are different facts.

Revision ID: 054_content_metrics
Revises: 053_deal_columns
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "054_content_metrics"
down_revision = "053_deal_columns"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "content_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "publication_id",
            sa.BigInteger(),
            sa.ForeignKey("content_publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_on", sa.Date(), nullable=False),
        # BigInteger and not Integer: a viral Short outliving a 32-bit column is
        # unlikely and free to allow for.
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "publication_id", "captured_on", name="uq_content_metrics_pub_day"
        ),
    )
    op.create_index("ix_content_metrics_org_id", "content_metrics", ["org_id"])
    op.create_index(
        "ix_content_metrics_publication_id", "content_metrics", ["publication_id"]
    )
    # The read the console does on every piece: the newest snapshot of one
    # publication. Descending, because "latest" is the only one ever wanted.
    op.create_index(
        "ix_content_metrics_pub_day",
        "content_metrics",
        ["publication_id", sa.text("captured_on DESC")],
    )
    _rls("content_metrics")


def downgrade() -> None:
    op.drop_index("ix_content_metrics_pub_day", table_name="content_metrics")
    op.drop_index("ix_content_metrics_publication_id", table_name="content_metrics")
    op.drop_index("ix_content_metrics_org_id", table_name="content_metrics")
    op.drop_table("content_metrics")

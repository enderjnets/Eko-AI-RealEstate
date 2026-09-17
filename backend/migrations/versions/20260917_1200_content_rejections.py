"""What a rejection said, and what the writer is supposed to learn from it.

Until now a rejection wrote one string, `content_pieces.rejected_reason`, and
nothing ever read it back. Measured on the live rail: the owner rejected four
pieces for the same defect — 66, 70, 71 and 73, "there is not call to action at
the end", "NO esta cerrando con un CTA", "CTA missing" — over three days, and
the fifth came out with the same defect, because the reason was a note to
nobody.

Two tables rather than one. A rejection is an EVENT about a piece and its
snapshot is history; a lesson is STANDING guidance that outlives the piece that
produced it, is capped, and a person can revoke. Folding them together would
mean either no history or lessons that resurrect with every re-read of an old
row.

`snapshot` exists because the correction reuses the SAME row — a new row would
shift `next_topic` and the sign-off rotation, which both count rows. So the
text that was rejected is overwritten, and this is the only place it survives.

Revision ID: 063_content_rejections
Revises: 062_publication_withdrawn
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "063_content_rejections"
down_revision = "062_publication_withdrawn"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def _isolate(table: str) -> None:
    """The same default-deny policy every tenant table here carries."""
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
        "content_rejections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "piece_id",
            sa.BigInteger(),
            sa.ForeignKey("content_pieces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        # Filled by the sweep, not by the endpoint: classifying can cost an LLM
        # call, and a person pressing Reject should not wait on a provider.
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("finding", postgresql.JSONB(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_content_rejections_org_id", "content_rejections", ["org_id"])
    op.create_index(
        "ix_content_rejections_piece", "content_rejections", ["piece_id", "created_at"]
    )
    # The sweep's own query: everything still to act on, for this tenant.
    op.create_index(
        "ix_content_rejections_open",
        "content_rejections",
        ["org_id", "resolved_at"],
    )
    _isolate("content_rejections")

    op.create_table(
        "content_lessons",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        # Short on purpose: a lesson is an instruction to a model, and a
        # paragraph pasted into every prompt is a paragraph that eventually
        # contradicts `_SYSTEM`.
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column(
            "source_piece_id",
            sa.BigInteger(),
            sa.ForeignKey("content_pieces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_content_lessons_org_id", "content_lessons", ["org_id"])
    op.create_index(
        "ix_content_lessons_live", "content_lessons", ["org_id", "active", "created_at"]
    )
    _isolate("content_lessons")


def downgrade() -> None:
    op.drop_table("content_lessons")
    op.drop_table("content_rejections")

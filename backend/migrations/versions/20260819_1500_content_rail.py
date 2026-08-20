"""The content rail: pieces and their publications, tenant-isolated.

Two tables for the Content Studio. Both belong to an agency, so both carry
`org_id` and a default-deny RLS policy — a new tenant table without one is
readable by every tenant, and the app connects as a role without BYPASSRLS
precisely so that omission cannot pass unnoticed.

`content_publications` carries UNIQUE (piece_id, platform). Idempotency belongs
in the database rather than in the publisher: a retry, a second worker and a
double click all arrive as the same insert, and the database is the only
participant that sees all three. Without it, "publish" is one crash away from
posting the same video twice to a client's channel.

Purely additive — two new tables and five new enum types, nothing existing is
touched — so it is safe to run ahead of the code that uses it.

Revision ID: 035_content_rail
Revises: 034_due_index
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Defined here rather than imported from app code: a migration has to keep
# describing what it did on the day it ran, and app constants move.
APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "035_content_rail"
down_revision = "034_due_index"
branch_labels = None
depends_on = None


# `create_type=False`: they are created explicitly in `upgrade()` so that a
# failure creating a type is not indistinguishable from a failure creating a
# table. Without it `create_table` tries to create them a second time and the
# migration dies on DuplicateObjectError.
def _enum(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


CONTENT_KIND = _enum("generated", "recorded", name="content_kind")
CONTENT_LANGUAGE = _enum("en", "es", name="content_language")
CONTENT_STATUS = _enum(
    "draft",
    "needs_approval",
    "approved",
    "publishing",
    "published",
    "rejected",
    "failed",
    name="content_status",
)
PUBLICATION_PLATFORM = _enum(
    "youtube", "tiktok", "instagram", name="publication_platform"
)
PUBLICATION_STATUS = _enum(
    "pending", "publishing", "published", "failed", name="publication_status"
)


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
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {APP_ROLE}")


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        CONTENT_KIND,
        CONTENT_LANGUAGE,
        CONTENT_STATUS,
        PUBLICATION_PLATFORM,
        PUBLICATION_STATUS,
    ):
        postgresql.ENUM(
            *enum_type.enums, name=enum_type.name
        ).create(bind, checkfirst=True)

    op.create_table(
        "content_pieces",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", CONTENT_KIND, nullable=False),
        sa.Column("language", CONTENT_LANGUAGE, nullable=False),
        sa.Column("status", CONTENT_STATUS, nullable=False, server_default="draft"),
        sa.Column("hook", sa.String(length=300), nullable=True),
        sa.Column("script", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("media_path", sa.String(length=500), nullable=True),
        sa.Column("violations", postgresql.JSONB(), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_content_pieces_org_id", "content_pieces", ["org_id"])
    # The approval queue is the only listing this table has, and it is read on
    # every load of the console tab.
    op.create_index(
        "ix_content_pieces_org_status", "content_pieces", ["org_id", "status"]
    )
    _isolate("content_pieces")

    op.create_table(
        "content_publications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
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
        sa.Column("platform", PUBLICATION_PLATFORM, nullable=False),
        sa.Column(
            "status", PUBLICATION_STATUS, nullable=False, server_default="pending"
        ),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("piece_id", "platform", name="uq_content_publication"),
    )
    op.create_index(
        "ix_content_publications_org_id", "content_publications", ["org_id"]
    )
    op.create_index(
        "ix_content_publications_piece_id", "content_publications", ["piece_id"]
    )
    _isolate("content_publications")


def downgrade() -> None:
    op.drop_table("content_publications")
    op.drop_table("content_pieces")
    bind = op.get_bind()
    for enum_type in (
        PUBLICATION_STATUS,
        PUBLICATION_PLATFORM,
        CONTENT_STATUS,
        CONTENT_LANGUAGE,
        CONTENT_KIND,
    ):
        enum_type.drop(bind, checkfirst=True)

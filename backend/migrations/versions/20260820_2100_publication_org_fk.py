"""A publication may only reference its own organisation's piece.

The audit reproduced this as org 96: INSERT a `content_publications` row with
`org_id = 96` pointing at a piece belonging to org 95 — and it succeeded,
because the foreign key only checked that the piece EXISTS, and foreign keys
are validated with the referenced table's row security out of the picture.
Org 96 cannot read piece 67, but it could reference it.

Two consequences once a publisher exists: an existence oracle (the insert
succeeds only for piece ids that exist somewhere, letting one tenant probe
another's id space), and a denial of service through UNIQUE (piece_id,
platform) — a foreign row occupying (67, 'instagram') blocks the piece's real
owner from ever recording its own publication there.

The composite foreign key makes the database itself require that the
publication's org and the piece's org are the same row's. No application code
can forget it, which is the standard this repo holds tenant boundaries to.

Revision ID: 040_publication_org_fk
Revises: 039_render_columns
"""
from __future__ import annotations

from alembic import op

revision = "040_publication_org_fk"
down_revision = "039_render_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The composite FK needs a matching unique target on the parent.
    op.create_unique_constraint(
        "uq_content_pieces_id_org", "content_pieces", ["id", "org_id"]
    )
    # The single-column FK is subsumed by the composite one.
    op.drop_constraint(
        "content_publications_piece_id_fkey",
        "content_publications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_content_publications_piece_org",
        "content_publications",
        "content_pieces",
        ["piece_id", "org_id"],
        ["id", "org_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_content_publications_piece_org",
        "content_publications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "content_publications_piece_id_fkey",
        "content_publications",
        "content_pieces",
        ["piece_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_content_pieces_id_org", "content_pieces", type_="unique"
    )

"""What the buyer actually asked for, as something a comparison can read.

A person who writes "DTC, 2 bedrooms, an office, a garage for two SUVs, buying
in six months" has told us five facts. Until this migration the system kept two
of them — the neighbourhood and the timeline — and the rest survived only as a
sentence in `messages.content`, which nothing can compare against. So the
shortlist that went back was "everything active in that area, cheapest first",
and a careful description bought the sender exactly nothing.

Four typed columns rather than one JSONB bag, and the deciding reason is
`baths_min`: it is compared against `properties.bathrooms`, which is
NUMERIC(3,1) because half-baths exist. A number that round-trips through JSON
comes back a float, and this codebase has already paid for float-against-Decimal
once. The other three follow it so that four requirements do not live in two
different shapes.

`wants_office` is deliberately a plain boolean and deliberately NOT matchable:
the REcolorado Full export has no office or den column — verified against the
real 394-column header — so a shortlist reports it as unchecked rather than
pretending to have compared it. NULL and false mean the same thing here and
only true is ever written.

Revision ID: 065_lead_requirements
Revises: 064_listing_requests
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "065_lead_requirements"
down_revision = "064_listing_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("beds_min", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("baths_min", sa.Numeric(3, 1), nullable=True))
    op.add_column("leads", sa.Column("garage_min", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("wants_office", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "wants_office")
    op.drop_column("leads", "garage_min")
    op.drop_column("leads", "baths_min")
    op.drop_column("leads", "beds_min")

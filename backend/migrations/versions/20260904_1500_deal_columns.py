"""What kind of deal was closed, and what it was worth.

`status = won` is a fact with no content. It cannot answer the question the
owner actually asks — "what business are we closing?" — because a listing that
sold, a buyer who bought and a rental all look identical, and they are different
businesses with different economics.

Four columns on `leads`, not a table: a lead closes once. A second sale to the
same person years later is a new lead, which is also how the funnel counts it.

`won_kind` is text with a constant beside it rather than a Postgres enum. The
set will change — the agency will want to split "referral", or add "lease
renewal" — and an enum turns that into a migration. Worse, renaming a value
would rewrite what the past says was closed.

`won_value` is nullable **and stays nullable in most rows**. The commission is
often not known the day a deal closes, and forcing a number would produce a
column of guesses that later gets averaged as if it were fact.

Nothing here feeds our invoice, and it must not: Colorado forbids sharing a
commission with anyone who is not licensed. This is the agency's own record of
their own business, and it lives here because the analytics has to end
somewhere real.

Revision ID: 053_deal_columns
Revises: 052_lead_events
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "053_deal_columns"
down_revision = "052_lead_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("won_kind", sa.Text(), nullable=True))
    # NUMERIC(12,2), the same shape as the budget columns beside it: ten digits
    # before the point is a house, not a rounding error.
    op.add_column("leads", sa.Column("won_value", sa.Numeric(12, 2), nullable=True))
    op.add_column(
        "leads", sa.Column("won_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("leads", sa.Column("lost_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "lost_reason")
    op.drop_column("leads", "won_at")
    op.drop_column("leads", "won_value")
    op.drop_column("leads", "won_kind")

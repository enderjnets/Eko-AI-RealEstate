"""The shortlist the system proposes, and the words that go with it.

Until now a `listing_requests` row said only that somebody had asked. The
operator opened it to a list of everything active in the area, cheapest first,
and had to hold the buyer's sentence in her head while she read it — which is
the same work the system could have done, done worse, and done again for every
request.

Five columns, and the split between two of them is the point:

* `suggestions` is machine-generated and disposable. It is recomputed WHOLESALE
  every time the request is opened or a new export is imported, so it is never
  the authority on anything — the listing facts in it are a cache of a
  comparison, regenerable from `checks` and the live `properties` row.
* `sent_reasons` is what a person wrote, and it must survive that recompute
  untouched. An import landing between "she edits the reason" and "she presses
  send" must not quietly discard her sentence.

`requirements_snapshot` exists so the arithmetic in the notice stays checkable:
"2 matched of 8 active" has to mean what the agent was told at the time, not
drift because a later message changed the lead.

None of this reaches the public token page. REcolorado §11.2 lets a Participant
distribute listing information to a prospective purchaser and forbids
publishing it; the page a stranger can open still carries a name and nothing
else, and a test asserts it.

Revision ID: 066_request_suggestions
Revises: 065_lead_requirements
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "066_request_suggestions"
down_revision = "065_lead_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listing_requests",
        sa.Column(
            "suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "listing_requests",
        sa.Column(
            "requirements_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "listing_requests",
        sa.Column(
            "sent_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "listing_requests",
        sa.Column("match_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "listing_requests",
        sa.Column("suggested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("listing_requests", "suggested_at")
    op.drop_column("listing_requests", "match_summary")
    op.drop_column("listing_requests", "sent_reasons")
    op.drop_column("listing_requests", "requirements_snapshot")
    op.drop_column("listing_requests", "suggestions")

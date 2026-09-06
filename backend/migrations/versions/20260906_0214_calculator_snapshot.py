"""What the visitor calculated before they left their email.

`/calculator` shows a rent-to-price estimate before asking for anything. When
the visitor then fills the form, the browser sends the three inputs and the
sliders they moved; the server recomputes them (`services/calculator.py`) and
stores the whole picture here — inputs, assumptions and result, versioned — so
the agent reads what the visitor saw, not what a browser claimed.

One JSONB column on `leads`, not a table: the snapshot belongs to the lead the
way its attribution does, it is read on the lead's own screen, and the last
calculation wins (someone who recalculates and resubmits updates it).

Nullable, no default, on purpose. An INSERT that does not mention the column
is still valid, so code that predates this revision keeps working against a
database that has it — the sibling branch asked for exactly that, to be able
to roll its own code back with this migration applied. The same property makes
the deploy order forgiving in one direction only: migrate first, then start
the code that knows the column; the container does not migrate on start.
Rolling code back does not require `downgrade`, and `downgrade` destroys every
snapshot captured; it exists for symmetry, not for rollback.

No policy and no grant: row-level security on `leads` is per row and covers
every column, and the app role's grants are per table.

Revision ID: 055_calculator_snapshot
Revises: 054_content_metrics
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "055_calculator_snapshot"
down_revision = "054_content_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("calculator_snapshot", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "calculator_snapshot")

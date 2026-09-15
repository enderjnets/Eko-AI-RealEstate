"""Record what a published figure was computed from, so it can be re-checked.

Five videos went out saying "Renting at $2,600 a month? — Buying is ~$21,000
ahead in five years." The calculator the same caption links to answers $52,210
for that rent under the assumptions the page actually uses. The figure was not
invented — it reproduces at a flat 2% appreciation against the page's 3.75% —
but nothing recorded which assumptions were used, so nobody could tell until
the owner watched them and took all five down.

The root cause is one line long: **nothing in content generation has ever
called the calculator.** `app/services/calculator.py` is imported by
`capture.py` and `lead_notify.py` and by nothing else. The numbers in a hook
arrive as prose, from a model, and the only moment the claim and the
calculator can be put side by side is when a person approves the piece.

Hence a column rather than a check constraint: what has to be stored is the
inputs, not a verdict. A verdict computed once is a verdict that stops being
true when a default rate moves, and the written instruction of 14-sep-2026
(`docs/content/calculator-consistency.md`) requires exactly the opposite —
"si cambian fórmulas o valores predeterminados, recalcular los ejemplos de
publicaciones pendientes afectadas antes de publicarlas".

Nullable, and every existing row keeps NULL: a piece that states no figure
needs no record, and backfilling a guess would be inventing the evidence this
column exists to demand.

Revision ID: 061_piece_calculator_check
Revises: 060_landing_traffic_class
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "061_piece_calculator_check"
down_revision = "060_landing_traffic_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_pieces",
        sa.Column(
            "calculator_check",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("content_pieces", "calculator_check")

"""messages.fair_housing_flags: what the filter saw on the way out

The Fair Housing filter has existed since v0.52 and, until now, ran only on the
video rail: `api/v1/content.py`, `services/content_studio.py` and
`services/content_writer.py`. The lane that actually talks to leads today —
`services/conversation.py`, over SMS, email and WhatsApp — never called it. The
protection was built where it was easy rather than where the exposure is.

NULL means "never checked", which is the truth about every row written before
this migration, and it is why there is no backfill. Writing `'[]'` across the
table would assert that those replies were reviewed and found clean; they were
not reviewed at all. That distinction is the whole value of the column: a
regulator asking "was this screened?" gets a different answer from NULL than
from an empty list, and only one of them is honest.

JSONB rather than a bounded string on purpose — the payload is
`find_violations`' own shape, `[{"phrase": ..., "category": ...}]`, and it is
therefore exempt from the `clip_string_columns` list on the model, which trims
bounded text columns.

Revision ID: 043_fair_housing_flags
Revises: 042_alerted_state
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "043_fair_housing_flags"
down_revision = "042_alerted_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No backfill, no RLS policy and no GRANT, each for a checked reason:
    # `messages` is already covered by an org policy, and `eko_app` holds
    # table-level DML on it (information_schema.table_privileges), so a new
    # column is reachable without a new grant. See the module docstring for
    # why every existing row stays NULL.
    op.add_column(
        "messages",
        sa.Column("fair_housing_flags", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "fair_housing_flags")

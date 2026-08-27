"""messages.internal: a row in the lead's thread that is NOT a message to them

The appointment invitation is emailed twice — once to the lead, once to the
agency's booking address. Both belong in the lead's file: opening a conversation
should show that the visit was confirmed and that the agent was told. Only one
of them is a message TO the lead.

Without this column there is no way to write the second one down safely, and
"safely" is not decoration. Two machines walk the messages table by shape:

  * `delivery.py::_still_owed` re-sends any OUTBOUND row that has no
    `external_id` and is PENDING/FAILED. An agency note landing there would be
    delivered TO THE LEAD.
  * `conversation.py` builds the LLM's context from every row in the
    conversation. An internal note would enter the prompt as a conversational
    turn and could be quoted back at the lead.

Both gain an `internal IS false` filter in the same commit as this column. The
column is the fact; those two filters are what make the fact harmless.

Existing rows are `false` via the server default, which is the truth: every
message written before today was addressed to the lead. This is the opposite of
043's reasoning — there NULL meant "never checked" and a backfill would have
lied; here `false` is a verified statement about every existing row, so the
server default IS the backfill.

Revision ID: 044_message_internal
Revises: 043_fair_housing_flags
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "044_message_internal"
down_revision = "043_fair_housing_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No RLS policy and no GRANT, for the reason checked in 043: `messages` is
    # already covered by an org policy and `eko_app` holds table-level DML on
    # it, so a new column is reachable without a new grant.
    #
    # NOT NULL with a server default rather than nullable: "we do not know
    # whether this was internal" is not a state this column should be able to
    # express. Every row is one or the other, and a NULL here would make both
    # filters above silently ambiguous.
    op.add_column(
        "messages",
        sa.Column(
            "internal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "internal")

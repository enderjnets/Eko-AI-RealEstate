"""Give the consent fortnight its own counter, so an outage cannot spend it.

`follow_ups.attempts` carried three unrelated things at once: how many days we
have waited for permission to write to this lead, how many times choosing a
channel raised, and how many times a dispatch was tried. Only the first is
supposed to bound the fortnight of daily retries, but any of the three could
spend it.

The bill came in as: an exception inside channel selection increments `attempts`
and — unlike the consent hold — writes no `postponed_until`, so the row falls
due again on the next five-minute sweep. Thirteen sweeps of a one-hour blip put
`attempts` at 13; two ordinary sweeps later the consent give-up fires, and since
v0.51.0 that give-up takes the rest of the sequence with it. A lead who viewed a
property on the 3rd gets none of the three post-visit messages and the sequence
is dead on the 5th, with the two other rows never having been held at all.

Backfilled from `attempts` rather than zeroed: a row PENDING right now with a
`postponed_until` stamp got that stamp from the consent hold, so its `attempts`
IS its hold count. Zeroing would hand every currently-held lead a fresh
fortnight, which is the same silent product change in the other direction.

Revision ID: 036_consent_holds
Revises: 035_content_rail
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_consent_holds"
down_revision = "035_content_rail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "follow_ups",
        sa.Column(
            "consent_holds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Only rows that are actually mid-hold: PENDING, deferred, and with a
    # counter on them. Anything else has no hold history worth carrying over,
    # and copying `attempts` onto a SENT row would invent one.
    op.execute(
        """
        UPDATE follow_ups
           SET consent_holds = attempts
         WHERE status = 'pending'
           AND postponed_until IS NOT NULL
           AND attempts > 0
        """
    )


def downgrade() -> None:
    op.drop_column("follow_ups", "consent_holds")

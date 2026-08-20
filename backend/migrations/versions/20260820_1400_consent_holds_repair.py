"""Repair the hold counts 036 backfilled from a poisoned source.

036 split the consent fortnight out of `attempts` and backfilled
`consent_holds = attempts` for rows mid-hold, on the claim that for those rows
"its `attempts` IS its hold count". That claim is false for exactly the rows
the split existed to protect: under the old code a channel-selection error
also incremented `attempts`, so a row that had been held once and then sat
through a one-hour blip arrived here with `attempts = 14` — and the backfill
promoted the whole poisoned total. Its second real hold became give-up
number fifteen, and since v0.51.0 the give-up takes the rest of the sequence
with it. The migration that shipped the fix re-armed the bug.

The split cannot be recovered from `attempts` alone; what can be known is a
ceiling: holds happen at most once per day, and none before the row was due.
`LEAST(count, days elapsed since scheduled_for + 1)` therefore keeps an
honestly-held row's count exactly (14 daily holds imply ≥14 days elapsed) and
clamps a poisoned one to the days it has actually lived — a lead held once
two days ago goes from 14 back to at most 3, and keeps most of the fortnight
it is owed.

Runs correctly whether or not the damage has already been served: it only
ever lowers counts, and a count at or under its day-ceiling is untouched.

Revision ID: 038_consent_holds_repair
Revises: 037_brokerage_line
"""
from __future__ import annotations

from alembic import op

revision = "038_consent_holds_repair"
down_revision = "037_brokerage_line"
branch_labels = None
depends_on = None

# Module-level and importable, so a test can execute the exact statement
# against seeded data. 036's riskiest lines had zero coverage — every CI
# upgrade ran them against an empty table — and that is how the poisoned
# backfill shipped.
CORRECTIVE_SQL = """
UPDATE follow_ups
   SET consent_holds = LEAST(
       consent_holds,
       GREATEST(
           0,
           1 + FLOOR(
               EXTRACT(EPOCH FROM (NOW() - scheduled_for)) / 86400
           )::int
       )
   )
 WHERE status = 'pending'
   AND consent_holds > 0
"""


def upgrade() -> None:
    op.execute(CORRECTIVE_SQL)


def downgrade() -> None:
    # Nothing to restore: the poisoned totals were never information.
    pass

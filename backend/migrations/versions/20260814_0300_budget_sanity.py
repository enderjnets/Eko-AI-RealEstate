"""Budget ranges that cannot be inverted, negative, or overflowing.

Revision ID: 030_budget_sanity
Revises: 029_call_console
Create Date: 2026-08-14

Three audit rounds found the same defect at a different route each time: the
call console, then `PATCH /leads/{id}`, then `POST /leads` — and a fourth,
`conversation.py`, writes these columns straight from the language model's
extraction with no check at all. Each round I closed one door and the next round
found the next one, which is the signature of a rule kept in the wrong place.

An inverted range is not a validation nicety. The lead silently stops matching
any listing for ever: `/matches` returns 200 with zero results and says nothing
about why, so it reads as "nothing on the market" rather than "this record is
broken". A negative budget is meaningless, and anything past ten digits
overflows NUMERIC(12,2) and surfaces as a driver error — a 500 with no body.

Constraints hold for every writer, including the ones nobody has written yet.
The routes keep their own checks so the message stays a readable 400 rather than
a constraint violation, but they are now the courtesy, not the guarantee.

Production was verified clean before this was written: 38 leads, none inverted,
none negative. Should this ever fail to apply, look for the rows first —
`SELECT id, budget_min, budget_max FROM leads WHERE budget_min > budget_max` —
because a range that is backwards is a record somebody has to look at, not a row
to quietly repair.
"""

from alembic import op

revision = "030_budget_sanity"
down_revision = "029_call_console"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL is allowed on both sides — most leads arrive without a budget, and
    # "unknown" is a legitimate state. The comparison only bites when both are
    # present, which is exactly when it can be wrong.
    op.create_check_constraint(
        "ck_leads_budget_not_inverted",
        "leads",
        "budget_min IS NULL OR budget_max IS NULL OR budget_min <= budget_max",
    )
    op.create_check_constraint(
        "ck_leads_budget_non_negative",
        "leads",
        "(budget_min IS NULL OR budget_min >= 0) "
        "AND (budget_max IS NULL OR budget_max >= 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_leads_budget_non_negative", "leads", type_="check")
    op.drop_constraint("ck_leads_budget_not_inverted", "leads", type_="check")

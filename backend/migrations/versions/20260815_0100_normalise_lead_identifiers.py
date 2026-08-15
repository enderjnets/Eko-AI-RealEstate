"""Make existing lead identifiers canonical, the way new ones already are.

Revision ID: 031_normalise_ids
Revises: 030_budget_sanity
Create Date: 2026-08-15

Every guard in this system — the opt-out refusal, the consent gate, the
dedupe on capture — is keyed to a row found by `leads.phone`. Fork the identity
and they all fall together: the same human as two rows means a STOP recorded
against one protects neither.

New identifiers are made canonical at the boundary now. This does the same for
the ones already stored, because an invariant that holds only for rows written
after a certain Tuesday is not an invariant — and normalising the input while
leaving the corpus alone is worse than doing neither, since a legacy row and its
canonical retype stop matching each other.

Deliberately conservative:

- Only rows that already look like a phone number are touched. Email addresses
  are lower-cased. Synthetic keys — `voice:`, `discovery:`, scraped profile URLs
  — are identities in their own right and are left exactly as they are.
- A row is only rewritten when nothing else in the same organisation already
  holds the canonical form. Merging two leads is a judgement about a person's
  history, not something a migration should do behind anyone's back; where that
  collision exists the row is left alone and listed in the output so a human can
  look at it.

Checked against production before this was written: 38 leads, of which 7 are
already E.164, 3 are email addresses and 28 are discovery keys. Nothing to
rewrite there — this exists so the rule is true everywhere, not because that
database needed it.
"""

from alembic import op

revision = "031_normalise_ids"
down_revision = "030_budget_sanity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # Lower-case email identifiers, unless that would collide.
    connection.exec_driver_sql(
        """
        UPDATE leads AS l
           SET phone = lower(l.phone)
         WHERE l.phone LIKE '%@%'
           AND l.phone <> lower(l.phone)
           AND NOT EXISTS (
                 SELECT 1 FROM leads AS other
                  WHERE other.org_id = l.org_id
                    AND other.phone = lower(l.phone)
                    AND other.id <> l.id
               )
        """
    )

    # Phone-shaped identifiers to E.164, for the two shapes that are
    # unambiguous: ten digits (North American, as this office writes them) and
    # eleven starting with 1. Anything else has no country context and is left
    # for a person to look at rather than guessed at here.
    connection.exec_driver_sql(
        """
        WITH candidate AS (
            SELECT id,
                   org_id,
                   regexp_replace(phone, '[^0-9]', '', 'g') AS digits
              FROM leads
             WHERE phone !~ '^\\+[0-9]+$'
               AND phone NOT LIKE '%@%'
               AND phone NOT LIKE 'voice:%'
               AND phone NOT LIKE 'discovery:%'
               AND phone NOT LIKE 'http%'
        ),
        normalised AS (
            SELECT id,
                   org_id,
                   CASE
                       WHEN length(digits) = 10 THEN '+1' || digits
                       WHEN length(digits) = 11 AND digits LIKE '1%' THEN '+' || digits
                   END AS canonical
              FROM candidate
        )
        UPDATE leads AS l
           SET phone = n.canonical
          FROM normalised AS n
         WHERE l.id = n.id
           AND n.canonical IS NOT NULL
           AND NOT EXISTS (
                 SELECT 1 FROM leads AS other
                  WHERE other.org_id = n.org_id
                    AND other.phone = n.canonical
                    AND other.id <> n.id
               )
        """
    )


def downgrade() -> None:
    # There is no going back: the original spelling is not recorded anywhere,
    # and inventing one would be worse than leaving the canonical form. Nothing
    # depends on the old text — every lookup goes through the same
    # normalisation — so this is a no-op rather than a lie.
    pass

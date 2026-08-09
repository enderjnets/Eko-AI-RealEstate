"""identity is global, business data is per-tenant

Migration 016 scoped every natural key to the organization. That was right for
business data and wrong for identity, and the mistake was worse than the leak it
closed.

An email address identifies a *person*, and login has to resolve one person
without already knowing their org — that is the whole reason the login path runs
on a bypass session. Once the same email could exist in two organizations, the
four lookups behind sign-in (`resolve_email_org`, `resolve_email_access`,
`login_account`, `register`) each hit `scalar_one_or_none()` on an unscoped query
and raised `MultipleResultsFound`, unhandled. Reaching it needed no attack:
agency B's admin adds a person via `POST /api/v1/team`, whose own duplicate check
is RLS-scoped and cannot see agency A's row. That person is then locked out of
agency A permanently, across Google, Apple and password login, with nothing in
either admin's UI explaining why.

So identity tables go back to globally unique — one email, one person, one
organization — and business data stays scoped:

  global:    allowed_users.email, accounts.email, user_activity.email
  per-org:   leads.phone, messages.external_id, visits.external_booking_id

`visits.external_booking_id` is added to the scoped set here: two agencies on one
Cal.com account collide on it today, which is both a booking failure and the same
existence oracle.

Revision ID: 018_identity_is_global
Revises: 017_lock_down_organizations
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018_identity_is_global"
down_revision = "017_lock_down_organizations"
branch_labels = None
depends_on = None

# Back to global uniqueness: these identify a person, not a row inside a tenant.
IDENTITY_INDEXES = (
    ("ix_accounts_email", "accounts", ["email"]),
    ("ix_allowed_users_email", "allowed_users", ["email"]),
)


def _dedupe_before_unique(table: str) -> None:
    """Collapse duplicate emails, keeping the earliest row.

    Without this the migration cannot run on the only deployments that need it.
    Migrations 016/017 made duplicate emails legal, so any install that ran them
    long enough for the lockout to happen already holds duplicates — and
    `CREATE UNIQUE INDEX` then fails, leaving the fix undeployable on exactly
    the systems it was written for.

    Keeping the lowest id keeps the original organization's membership and drops
    the later claim. That does remove someone's access to the newer agency, so
    the removals are printed: an operator has to be able to re-add them, and a
    silent delete of team access would be worse than the lockout.
    """
    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT email, array_agg(id ORDER BY id) AS ids,
                   array_agg(org_id ORDER BY id) AS orgs
              FROM {table}
             GROUP BY email HAVING count(*) > 1
            """
        )
    ).fetchall()
    if not rows:
        return
    for row in rows:
        print(
            f"  [018] {table}: '{row.email}' existed in orgs {list(row.orgs)}; "
            f"keeping id={row.ids[0]} (org {row.orgs[0]}), removing {list(row.ids[1:])}"
        )
    op.get_bind().execute(
        sa.text(
            f"""
            DELETE FROM {table} a
             USING {table} b
             WHERE a.email = b.email AND a.id > b.id
            """
        )
    )


def upgrade() -> None:
    for name, table, cols in IDENTITY_INDEXES:
        # Migration 015 put FORCE ROW LEVEL SECURITY on these tables with a
        # default-deny policy, and `app.current_org_id` is unset here. A
        # superuser bypasses that — the local Postgres image runs as one, which
        # is why this looked fine — but on a managed database where the
        # migration role owns the table and is not a superuser the dedup would
        # touch zero rows and the CREATE UNIQUE INDEX below would then abort on
        # the duplicates it was meant to clear. Lifting FORCE for the statement
        # is something the owner can always do; migration 022 does the same.
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        _dedupe_before_unique(table)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.drop_index(name, table_name=table)
        op.create_index(name, table, cols, unique=True)

    # Business data the 016 pass missed.
    op.drop_constraint("uq_visits_external_booking_id", "visits", type_="unique")
    op.create_unique_constraint(
        "uq_visits_external_booking_id", "visits", ["org_id", "external_booking_id"]
    )

    # Telemetry, not identity: the operator's own bootstrap account can be
    # active in more than one organization, and a global unique here meant only
    # the first org could ever hold a row for a given email — everyone else
    # silently overwrote it, leaking last_ip and device across tenants.
    op.drop_index("ix_user_activity_email", table_name="user_activity")
    op.create_index(
        "ix_user_activity_email", "user_activity", ["org_id", "email"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_user_activity_email", table_name="user_activity")
    op.create_index("ix_user_activity_email", "user_activity", ["email"], unique=True)

    op.drop_constraint("uq_visits_external_booking_id", "visits", type_="unique")
    op.create_unique_constraint(
        "uq_visits_external_booking_id", "visits", ["external_booking_id"]
    )

    for name, table, cols in IDENTITY_INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, ["org_id", *cols], unique=True)

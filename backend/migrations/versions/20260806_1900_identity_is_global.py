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


def upgrade() -> None:
    for name, table, cols in IDENTITY_INDEXES:
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

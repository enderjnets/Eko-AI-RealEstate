"""scope natural-key unique indexes to the organization

The multi-tenant migration added `org_id` and RLS but left every natural-key
unique index globally unique. That leaks across the tenant boundary through the
error channel: agency B inserts a phone number, gets
`duplicate key value violates unique constraint "ix_leads_phone"`, and has just
learned that agency A holds that contact — while RLS correctly reports zero rows
for the same query.

It is also plainly wrong functionally. Two agencies can each have the same
prospect, the same person can sit on two teams, and the same MLS listing can be
booked by both. Global uniqueness makes the second one impossible instead of
returning the intended 409.

Revision ID: 016_scope_unique_indexes
Revises: 015_multi_tenant
"""
from __future__ import annotations

from alembic import op

revision = "016_scope_unique_indexes"
down_revision = "015_multi_tenant"
branch_labels = None
depends_on = None

# (index name, table, columns) — each becomes UNIQUE(org_id, *columns).
SCOPED_INDEXES = (
    ("ix_leads_phone", "leads", ["phone"]),
    ("ix_accounts_email", "accounts", ["email"]),
    ("ix_allowed_users_email", "allowed_users", ["email"]),
)

# Declared as a UNIQUE CONSTRAINT rather than a bare index, so it has to be
# dropped as one. It backs the WhatsApp/SMS idempotency guard: Meta retries
# deliveries, and the duplicate must be caught per organization now.
SCOPED_CONSTRAINTS = (("uq_messages_external_id", "messages", ["external_id"]),)


def upgrade() -> None:
    for name, table, cols in SCOPED_INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, ["org_id", *cols], unique=True)

    for name, table, cols in SCOPED_CONSTRAINTS:
        op.drop_constraint(name, table, type_="unique")
        op.create_unique_constraint(name, table, ["org_id", *cols])


def downgrade() -> None:
    for name, table, cols in SCOPED_CONSTRAINTS:
        op.drop_constraint(name, table, type_="unique")
        op.create_unique_constraint(name, table, cols)

    for name, table, cols in SCOPED_INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, cols, unique=True)

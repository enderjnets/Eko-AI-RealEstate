"""restrict the organizations table to read-your-own-row

Two problems the multi-tenant migration left open.

`organizations` had no RLS at all, so the application role could list every
tenant's name, slug, plan and status — not a data leak through any endpoint
today (nothing exposes the table), but the whole point of the design is that
the boundary does not depend on which endpoints happen to exist.

Worse, it was granted full DML, and every org_id foreign key is ON DELETE
CASCADE. One stray DELETE from the request path would erase an entire agency's
leads, conversations, visits and settings. Tenant lifecycle is the platform
operator's job, so the app role now gets SELECT only, scoped to its own row.

Revision ID: 017_lock_down_organizations
Revises: 016_scope_unique_indexes
"""
from __future__ import annotations

import os

from alembic import op

revision = "017_lock_down_organizations"
down_revision = "016_scope_unique_indexes"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY organizations_read_own ON organizations
            FOR SELECT
            USING (id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON organizations FROM {APP_ROLE}")
    # Creating and suspending tenants runs on the bypass connection, which owns
    # the table; the request path never needs to write here.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(f"GRANT INSERT, UPDATE, DELETE ON organizations TO {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS organizations_read_own ON organizations")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations DISABLE ROW LEVEL SECURITY")

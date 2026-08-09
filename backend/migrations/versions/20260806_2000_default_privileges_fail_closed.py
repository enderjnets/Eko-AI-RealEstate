"""future tables must not grant the app role DML automatically

Migration 015 left `ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE,
DELETE ON TABLES TO eko_app` in place, and 017's REVOKE-then-GRANT pair restored
the same thing — a no-op that reads like a lockdown.

The consequence is fail-open exactly where the design says fail-closed: any
table created later by the owner hands the request path full DML the moment it
exists. A new tenant-owned table whose RLS policy has not been written yet is
therefore readable and writable across every organization, and nothing warns.

Default privileges are removed instead. Grants for new tables now have to be
stated in the migration that creates them, next to the policy — which is the
only place a reviewer can check that both were done.

Revision ID: 019_default_privs_closed
Revises: 018_identity_is_global
"""
from __future__ import annotations

import os

from alembic import op

revision = "019_default_privs_closed"
down_revision = "018_identity_is_global"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def upgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    # Sequences stay: a table the app may INSERT into is useless without its
    # sequence, and a sequence grants no access to anyone else's rows.


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )

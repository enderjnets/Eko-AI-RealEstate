"""Rotate the RLS role's password.

Migration 015 creates `eko_app` with `CREATE ROLE IF NOT EXISTS`, so on every
database where it has already run — which is every multi-tenant deployment, and
every dev stack with a persisted volume — the role keeps the password published
in this repository. Passing `APP_DB_PASSWORD` into the container fixed the
plumbing and not the idempotency: setting a real password afterwards left
`DATABASE_URL_APP` unable to authenticate while `/health` stayed green, which is
exactly the failure that change was written to prevent.

That role is `NOBYPASSRLS`, but the policy reads a setting the role can set for
itself, so anyone who reaches Postgres with it reads and writes every tenant.

Revision ID: 024_role_password_and_refs
Revises: 023_route_outbound_identity
"""
from __future__ import annotations

import os

from alembic import op

revision = "024_role_password_and_refs"
down_revision = "023_route_outbound_identity"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")
APP_PASSWORD = os.environ.get("APP_DB_PASSWORD", "")


def upgrade() -> None:
    if not APP_PASSWORD:
        # Deliberately not fatal. Dev and CI both run on the published default,
        # and refusing here would block them; a real deployment is told by the
        # role check at startup.
        print(
            f"  APP_DB_PASSWORD not set — role {APP_ROLE} keeps whatever "
            "password it has, which for a database first migrated before this "
            "revision is the literal published in this repository."
        )
        return

    exists = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM pg_roles WHERE rolname = %(role)s", {"role": APP_ROLE}
    ).first()
    if exists is None:
        # Happens only when APP_DB_ROLE was changed after 015 ran: 015 will not
        # re-run, so no role by the new name was ever created. Aborting the
        # whole chain over a password rotation is worse than saying so.
        print(
            f"  role {APP_ROLE} does not exist — APP_DB_ROLE was changed after "
            "the initial migration. Create it manually, or set APP_DB_ROLE back."
        )
        return

    # Quoted, not interpolated: this is a password and a stray quote would
    # otherwise be SQL. The role name is validated against pg_roles above.
    escaped = APP_PASSWORD.replace("'", "''")
    op.execute(f'ALTER ROLE "{APP_ROLE}" WITH PASSWORD \'{escaped}\'')


def downgrade() -> None:
    # The password is not rolled back. Restoring a known-published one would be
    # a downgrade that leaves the database less safe than it found it.
    pass

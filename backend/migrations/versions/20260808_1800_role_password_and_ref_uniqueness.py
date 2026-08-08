"""Rotate the RLS role's password, and make credential refs unique in the schema.

Two things migration 015 and the route-identity work each left half done.

**The role password.** 015 creates `eko_app` with `CREATE ROLE IF NOT EXISTS`,
so on every database where it has already run — which is every multi-tenant
deployment, and every dev stack with a persisted volume — the role keeps the
password published in this repository. Passing `APP_DB_PASSWORD` into the
container fixed the plumbing and not the idempotency: setting a real password
afterwards left `DATABASE_URL_APP` unable to authenticate while `/health`
stayed green, which is exactly the failure that change was written to prevent.
That role is `NOBYPASSRLS`, but the policy reads a setting the role can set for
itself, so anyone who reaches Postgres with it reads and writes every tenant.

**Credential uniqueness.** `_refs_claimed_elsewhere` is a check-then-act with
nothing behind it, so two concurrent onboarding calls could both claim the same
environment variable for different agencies — leaving one holding the secret
that authenticates the other's inbound messages. A unique index is the part
that actually holds.

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

# One index per column rather than one across all four: an agency legitimately
# points `credential_ref` and `inbound_secret_ref` at the SAME variable — for
# Twilio the auth token is both — so uniqueness has to be per role, not per row.
REF_COLUMNS = (
    "provider_account_ref",
    "credential_ref",
    "inbound_secret_ref",
    "verify_token_ref",
)


def upgrade() -> None:
    if APP_PASSWORD:
        # Quoted rather than interpolated: this is a password, and a stray
        # quote in it would otherwise be SQL.
        escaped = APP_PASSWORD.replace("'", "''")
        op.execute(f"ALTER ROLE {APP_ROLE} WITH PASSWORD '{escaped}'")
    else:
        # Deliberately not fatal. A dev stack and CI both run on the published
        # default, and refusing here would block them; the startup role check
        # is where a real deployment gets told.
        print(
            f"  APP_DB_PASSWORD not set — role {APP_ROLE} keeps whatever "
            "password it has, which for a database first migrated before this "
            "revision is the literal published in this repository."
        )

    for column in REF_COLUMNS:
        # Partial: NULL means "use the global configuration" and any number of
        # routes may say that.
        op.execute(
            f"CREATE UNIQUE INDEX uq_channel_routes_{column} "
            f"ON channel_routes ({column}) WHERE {column} IS NOT NULL"
        )


def downgrade() -> None:
    for column in REF_COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS uq_channel_routes_{column}")
    # The password is not rolled back. Restoring a known-published one would be
    # a downgrade that makes the database less safe than it was.

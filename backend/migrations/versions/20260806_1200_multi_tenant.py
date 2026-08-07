"""multi-tenant: organizations + org_id + row level security

Turns a one-deploy-per-agency product into the mother system: one install, many
client agencies, each seeing only its own rows.

Isolation is enforced by Postgres, not by application discipline. Every tenant
table gets a policy keyed on `app.current_org_id`, which `db/base.py` stamps onto
each transaction. Three details make it hold:

- FORCE ROW LEVEL SECURITY — without FORCE the table owner silently ignores
  policies, so the app and its tests would pass while isolating nothing.
- NULLIF(current_setting(...), '')::bigint — an unset variable yields NULL, and
  `org_id = NULL` is never true, so the default is zero rows rather than all of
  them. A forgotten scope fails closed.
- WITH CHECK as well as USING — USING alone filters reads but still lets a
  session WRITE into another org.

A dedicated `eko_app` role exists because Postgres superusers bypass RLS even
with FORCE. Pointing the app at a superuser would make every isolation test
green while enforcing nothing.

Revision ID: 015_multi_tenant
Revises: 014_sync_state
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "015_multi_tenant"
down_revision = "014_sync_state"
branch_labels = None
depends_on = None

# Every table that belongs to exactly one agency. `properties` and `sync_state`
# are deliberately absent: one REcolorado feed, one shared copy of the listings.
OWNED_TABLES = (
    "leads",
    "conversations",
    "messages",
    "visits",
    "follow_ups",
    "agent_settings",
    "allowed_users",
    "accounts",
    "user_activity",
)

DEFAULT_ORG_ID = 1
DEMO_ORG_ID = 2

APP_ROLE = "eko_app"
# Dev/CI convenience only. A real deployment sets APP_DB_PASSWORD before running
# migrations — otherwise the role that guards every tenant boundary ships with a
# password that is published in this repository.
APP_PASSWORD = os.environ.get("APP_DB_PASSWORD", "eko_app_local_pass")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(length=24), nullable=False, server_default="pilot"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.execute(
        sa.text(
            """
            INSERT INTO organizations (id, name, slug, status, plan) VALUES
                (:d, 'Robbie & Natalia', 'client-zero', 'active', 'pilot'),
                (:m, 'Demo', 'demo', 'trial', 'pilot')
            """
        ).bindparams(d=DEFAULT_ORG_ID, m=DEMO_ORG_ID)
    )
    # The explicit ids above bypassed the sequence; without this the first
    # self-service org would collide with DEFAULT_ORG_ID.
    op.execute("SELECT setval('organizations_id_seq', (SELECT MAX(id) FROM organizations))")

    for table in OWNED_TABLES:
        # server_default backfills existing rows, then is dropped so future
        # inserts must state their org explicitly — a silent default here would
        # quietly funnel another tenant's writes into org 1.
        op.add_column(
            table,
            sa.Column(
                "org_id",
                sa.Integer(),
                nullable=False,
                server_default=str(DEFAULT_ORG_ID),
            ),
        )
        op.alter_column(table, "org_id", server_default=None)
        op.create_foreign_key(
            f"fk_{table}_org_id", table, "organizations", ["org_id"], ["id"], ondelete="CASCADE"
        )
        if table == "agent_settings":
            op.create_index(f"uq_{table}_org_id", table, ["org_id"], unique=True)
        else:
            op.create_index(f"ix_{table}_org_id", table, ["org_id"])

    # Public /register demo accounts belong to the demo org, not to client zero.
    op.execute(
        sa.text("UPDATE accounts SET org_id = :m WHERE role = 'viewer'").bindparams(m=DEMO_ORG_ID)
    )

    _create_app_role()

    for table in OWNED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
                WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            """
        )


def downgrade() -> None:
    for table in OWNED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in OWNED_TABLES:
        index = f"uq_{table}_org_id" if table == "agent_settings" else f"ix_{table}_org_id"
        op.drop_index(index, table_name=table)
        op.drop_constraint(f"fk_{table}_org_id", table, type_="foreignkey")
        op.drop_column(table, "org_id")

    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")


def _create_app_role() -> None:
    """Non-superuser role the application connects as, so policies actually bind."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

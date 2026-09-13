"""partner_briefs: the ask stops being an email with a list at the bottom.

Every request we had for the two agents this product is built around arrived as
prose with a numbered list, and the reply we needed back was a person retyping
nine names into a mail client on a phone. That reply never comes, and it was
never reasonable to expect it.

`partner_briefs` is one row per link we hand them. `payload` is what the page
renders, `answers` is what they tapped back. Both are JSONB and that is the
decision worth defending here: a brief is written once, read for a week, and
never again. Hardcoding one means a deploy per campaign and a migration per
question; by Christmas there will be nine of these and no two the same shape.
What the table guarantees is not the shape of a brief, it is that an answer
stays attached to the brief it answers, under the org that owns both.

`token` is the credential — there is no login on that page and there must not
be, since the whole point is that somebody outside this product answers in one
tap. Unique globally rather than per-org, so two tenants cannot collide into
each other's brief.

Nullable `opened_at` / `answered_at` are the only state this table has, and the
distinction matters when you are deciding whether to phone somebody: "hasn't
opened it" and "opened it and had nothing to say" are different conversations.

Revision ID: 059_partner_briefs
Revises: 058_form_error_count
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "059_partner_briefs"
down_revision = "058_form_error_count"
branch_labels = None
depends_on = None


def _isolate(table: str) -> None:
    """The same default-deny policy every tenant table in this schema carries."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "partner_briefs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 64 rather than the 43 characters `token_urlsafe(32)` produces: the
        # length of the credential is an implementation detail that will change
        # the day somebody wants a longer one, and a column that has to be
        # migrated to allow it is a column that will not be.
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "recipient", sa.String(length=200), nullable=False, server_default=""
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Globally unique, NOT unique-per-org. The public endpoint looks a brief up
    # by token alone — it has no org to scope by, because the person holding
    # the link does not have a session. If two orgs could hold the same token,
    # that lookup would have to pick one.
    op.create_index(
        "ix_partner_briefs_token", "partner_briefs", ["token"], unique=True
    )
    op.create_index(
        "ix_partner_briefs_org_created", "partner_briefs", ["org_id", "created_at"]
    )

    _isolate("partner_briefs")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS partner_briefs_tenant_isolation ON partner_briefs")
    op.drop_index("ix_partner_briefs_org_created", table_name="partner_briefs")
    op.drop_index("ix_partner_briefs_token", table_name="partner_briefs")
    op.drop_table("partner_briefs")

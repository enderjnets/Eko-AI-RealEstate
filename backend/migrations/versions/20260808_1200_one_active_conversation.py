"""One active conversation per lead per channel, enforced.

The model's docstring has always said "one per (lead, channel)" and nothing
enforced it, which was survivable only because a concurrent second first-contact
used to blow up the whole transaction before it could create the second row.
Now that the lead get-or-create resolves that race instead of aborting, two
simultaneous inbound messages would each add an ACTIVE conversation — and the
lookup that reads them uses `scalar_one_or_none()`, so from that moment on
*every* message from that lead raises MultipleResultsFound. A permanent,
unexplained break for one lead, caused by two messages arriving together.

Partial rather than plain: closed and archived conversations are history, and a
lead who comes back months later legitimately gets a new one.

Revision ID: 022_one_active_conversation
Revises: 021_routes_no_app_read
"""
from __future__ import annotations

from alembic import op

revision = "022_one_active_conversation"
down_revision = "021_routes_no_app_read"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_conversations_active_per_lead_channel"


def upgrade() -> None:
    # Deduplicate first: this cannot be added to a database that already has
    # the rows it forbids, and the databases most likely to have them are the
    # live ones. Keep the oldest — it owns the message history — and archive the
    # rest rather than deleting, so nothing is silently thrown away.
    # Migration 015 put FORCE ROW LEVEL SECURITY on this table, and the policy
    # is default-deny when `app.current_org_id` is unset — which it is here. A
    # superuser bypasses that, and the local Postgres image runs as one, so this
    # dedup appears to work. On any managed database where the migration role
    # owns the table but is not a superuser it would silently update zero rows
    # and the CREATE UNIQUE INDEX below would then abort on the duplicates it
    # was supposed to have cleared. Lifting FORCE for the statement is something
    # the owner can always do, and it is restored immediately.
    op.execute("ALTER TABLE conversations NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY org_id, lead_id, channel
                       ORDER BY started_at, id
                   ) AS rn
            FROM conversations
            WHERE status = 'active'
        )
        UPDATE conversations c
        SET status = 'archived'
        FROM ranked r
        WHERE c.id = r.id AND r.rn > 1
        """
    )
    op.execute("ALTER TABLE conversations FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX_NAME} "
        "ON conversations (org_id, lead_id, channel) "
        "WHERE status = 'active'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

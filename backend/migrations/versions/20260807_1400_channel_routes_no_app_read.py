"""channel_routes: the app role does not need to read it

Migration 020 granted SELECT to the application role out of caution. Checking
the call sites afterwards shows nothing on the request path reads this table:
`resolve_org_by_destination` uses the bypass session precisely because routing
is resolved before any organization is bound, and the CRUD endpoints are
platform-operator routes that also run on bypass.

So the grant only widened what a tenant-scoped session could reach. The table
has no RLS — it cannot have any, for the same reason — which means an
unfiltered read would return every agency's phone numbers and mailboxes. No
endpoint exposes that today; removing the grant means none can start to by
accident either.

Revision ID: 021_routes_no_app_read
Revises: 020_channel_routes
"""
from __future__ import annotations

import os

from alembic import op

revision = "021_routes_no_app_read"
down_revision = "020_channel_routes"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")


def upgrade() -> None:
    op.execute(f"REVOKE ALL ON channel_routes FROM {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT SELECT ON channel_routes TO {APP_ROLE}")

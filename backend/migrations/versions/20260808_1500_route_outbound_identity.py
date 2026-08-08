"""Per-organization sending identity on channel_routes.

Inbound has been routed by destination since migration 020, but outbound still
had one global identity per channel: one Twilio number, one WhatsApp phone-number
id, one Resend from-address. So agency B's lead was answered from agency A's
number, replied to A's number, and the remainder of their conversation was
written into A's tenant. Nothing malicious — that is simply how it worked, and
it is why onboarding a second agency was blocked.

The columns hold the NAME of an environment variable, not the secret. Keys stay
in `.env` (the repo's standing rule) and the database holds only the mapping.
NULL means "fall back to the global configuration", which is what lets a
single-customer install keep running with nothing but its .env.

Revision ID: 023_route_outbound_identity
Revises: 022_one_active_conversation
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "023_route_outbound_identity"
down_revision = "022_one_active_conversation"
branch_labels = None
depends_on = None

COLUMNS = (
    ("provider_account_ref", sa.String(120)),
    ("credential_ref", sa.String(120)),
    ("inbound_secret_ref", sa.String(120)),
    ("verify_token_ref", sa.String(120)),
    ("sender_override", sa.String(254)),
    ("webhook_url", sa.String(500)),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("channel_routes", sa.Column(name, type_, nullable=True))

    # Migration 021 took the app role's read of this table away deliberately:
    # it is resolved on the bypass session before any organization is bound, so
    # nothing running under RLS has a reason to see it. That matters more now
    # that the rows name credentials — re-assert it rather than assume, since an
    # ALTER TABLE is exactly the kind of change that quietly restores a grant.
    op.execute(f"REVOKE ALL ON channel_routes FROM {APP_ROLE}")


def downgrade() -> None:
    for name, _type in reversed(COLUMNS):
        op.drop_column("channel_routes", name)

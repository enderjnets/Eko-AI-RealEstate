"""When a lead told us to stop.

The capture form's disclosure — the wording stored verbatim as the consent
record — says "reply STOP to opt out". Nothing implemented it. That is not
merely a missing feature: because the consent gate treats any inbound message
on a channel as consumer-initiated contact, replying STOP made a previously
blocked lead SENDABLE. The one word a person uses to make it stop was the word
that started it.

A column rather than a `meta` key for the same reason as consent: this is the
record you produce when someone asks why they kept receiving messages, and it
has to be answerable in one query across every lead.

Nullable with no backfill. NULL means "never asked us to stop", which is the
truthful answer for every row that exists today — nobody could have opted out
through a mechanism that did not exist.

Revision ID: 028_lead_opt_out
Revises: 027_lead_consent
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028_lead_opt_out"
down_revision = "027_lead_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads", sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True)
    )
    # The channel they said it on and the word they used. Opt-out is
    # channel-specific under TCPA — "stop texting me" is not "never email me
    # again" — and keeping the exact word is the same evidentiary logic as
    # keeping the consent wording.
    op.add_column("leads", sa.Column("opted_out_channel", sa.String(16), nullable=True))
    op.add_column("leads", sa.Column("opted_out_keyword", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "opted_out_keyword")
    op.drop_column("leads", "opted_out_channel")
    op.drop_column("leads", "opted_out_at")

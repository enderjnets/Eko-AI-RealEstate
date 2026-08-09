"""Let a failed reply be sent again.

A reply that hit a Meta 503 or a Twilio 429 was stamped FAILED and forgotten:
one POST, no retry, and no worker anywhere that looks for messages stuck
PENDING or FAILED. The AI's answer to a hot lead was silently lost.

Two columns to make a retry sweep possible: how many times we have tried, and
when to try next. `next_attempt_at` rather than a plain interval so the backoff
lives in the row and the sweep query stays a simple index scan.

Revision ID: 026_message_retry
Revises: 025_lead_email_contact
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "026_message_retry"
down_revision = "025_lead_email_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "messages",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("messages", sa.Column("last_error", sa.String(length=500), nullable=True))
    # Partial: the sweep only ever asks for outbound messages that still owe a
    # delivery, which is a tiny slice of a table that grows without bound.
    op.execute(
        "CREATE INDEX ix_messages_retryable ON messages (next_attempt_at) "
        "WHERE delivery_status IN ('pending', 'failed') AND direction = 'outbound'"
    )
    # Everything already FAILED predates the retry sweep. Leave it alone rather
    # than replaying days-old replies at leads who have moved on.


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_retryable")
    op.drop_column("messages", "last_error")
    op.drop_column("messages", "next_attempt_at")
    op.drop_column("messages", "send_attempts")

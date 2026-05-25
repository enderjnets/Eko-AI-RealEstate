"""phase3 multichannel — rename wa_* → external_*, add messages.subject

Revision ID: 002_phase3_multichannel
Revises: 001_phase1_baseline
Create Date: 2026-05-25 20:30:00.000000

Generalizes WhatsApp-specific columns to channel-agnostic names so SMS / Email
/ Voice can share the same Message + Conversation tables. Existing rows survive
the rename intact.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_phase3_multichannel"
down_revision: Union[str, None] = "001_phase1_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── messages ───────────────────────────────────────────────────────
    op.drop_constraint("uq_messages_wa_message_id", "messages", type_="unique")
    op.alter_column(
        "messages",
        "wa_message_id",
        new_column_name="external_id",
        type_=sa.String(length=255),  # bump 120 → 255 for RFC 822 Message-IDs / Twilio SIDs
        existing_type=sa.String(length=120),
    )
    op.alter_column("messages", "wa_status", new_column_name="delivery_status")
    op.create_unique_constraint("uq_messages_external_id", "messages", ["external_id"])
    op.add_column("messages", sa.Column("subject", sa.String(length=500), nullable=True))

    # ── leads.phone widened 32 → 254 (emails as identifiers in multichannel) ──
    op.alter_column(
        "leads",
        "phone",
        type_=sa.String(length=254),
        existing_type=sa.String(length=32),
    )
    op.alter_column(
        "leads",
        "name",
        type_=sa.String(length=160),
        existing_type=sa.String(length=120),
    )

    # ── conversations ──────────────────────────────────────────────────
    op.drop_index("ix_conversations_wa_thread_id", table_name="conversations")
    op.alter_column(
        "conversations",
        "wa_thread_id",
        new_column_name="external_thread_id",
        type_=sa.String(length=255),
        existing_type=sa.String(length=80),
    )
    op.create_index(
        "ix_conversations_external_thread_id",
        "conversations",
        ["external_thread_id"],
        unique=False,
    )
    op.create_index("ix_conversations_channel", "conversations", ["channel"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_conversations_channel", table_name="conversations")
    op.drop_index("ix_conversations_external_thread_id", table_name="conversations")
    op.alter_column(
        "conversations",
        "external_thread_id",
        new_column_name="wa_thread_id",
        type_=sa.String(length=80),
        existing_type=sa.String(length=255),
    )
    op.create_index("ix_conversations_wa_thread_id", "conversations", ["wa_thread_id"], unique=False)

    op.drop_column("messages", "subject")
    op.drop_constraint("uq_messages_external_id", "messages", type_="unique")
    op.alter_column(
        "messages",
        "external_id",
        new_column_name="wa_message_id",
        type_=sa.String(length=120),
        existing_type=sa.String(length=255),
    )
    op.alter_column("messages", "delivery_status", new_column_name="wa_status")
    op.create_unique_constraint("uq_messages_wa_message_id", "messages", ["wa_message_id"])

    op.alter_column(
        "leads",
        "name",
        type_=sa.String(length=120),
        existing_type=sa.String(length=160),
    )
    op.alter_column(
        "leads",
        "phone",
        type_=sa.String(length=32),
        existing_type=sa.String(length=254),
    )

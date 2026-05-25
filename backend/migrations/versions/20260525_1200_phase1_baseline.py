"""phase1 baseline — 5 tables: leads, conversations, messages, properties, agent_settings

Revision ID: 001_phase1_baseline
Revises:
Create Date: 2026-05-25 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_phase1_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── leads ────────────────────────────────────────────────────────
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new", "qualified", "visiting", "post_visit", "won", "lost", "paused",
                name="lead_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "intent",
            sa.Enum("rent", "buy", "valuation", "other", name="lead_intent"),
            nullable=True,
        ),
        sa.Column("budget_min", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("budget_max", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("zone", sa.String(length=160), nullable=True),
        sa.Column("property_type", sa.String(length=60), nullable=True),
        sa.Column("urgency", sa.String(length=40), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("human_takeover", sa.Boolean(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_phone", "leads", ["phone"], unique=True)
    op.create_index("ix_leads_status", "leads", ["status"], unique=False)
    op.create_index("ix_leads_last_message_at", "leads", ["last_message_at"], unique=False)
    op.create_index("ix_leads_status_last_message_at", "leads", ["status", "last_message_at"], unique=False)

    # ── conversations ───────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("wa_thread_id", sa.String(length=80), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="conversation_status"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_lead_id", "conversations", ["lead_id"], unique=False)
    op.create_index("ix_conversations_wa_thread_id", "conversations", ["wa_thread_id"], unique=False)
    op.create_index("ix_conversations_last_at", "conversations", ["last_at"], unique=False)

    # ── messages ────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", name="message_direction"),
            nullable=False,
        ),
        sa.Column(
            "sender",
            sa.Enum("lead", "agent", "human", name="message_sender"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("wa_message_id", sa.String(length=120), nullable=True),
        sa.Column(
            "wa_status",
            sa.Enum("pending", "sent", "delivered", "read", "failed", name="message_status"),
            nullable=False,
        ),
        sa.Column("llm_provider", sa.String(length=20), nullable=True),
        sa.Column("llm_model", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wa_message_id", name="uq_messages_wa_message_id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
    op.create_index("ix_messages_created_at", "messages", ["created_at"], unique=False)

    # ── properties ──────────────────────────────────────────────────
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("idealista", "fotocasa", "manual", name="property_source"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=280), nullable=False),
        sa.Column("zone", sa.String(length=160), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rooms", sa.Integer(), nullable=True),
        sa.Column("m2", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_properties_source_external_id"),
    )
    op.create_index("ix_properties_source", "properties", ["source"], unique=False)
    op.create_index("ix_properties_zone", "properties", ["zone"], unique=False)

    # ── agent_settings ──────────────────────────────────────────────
    op.create_table(
        "agent_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_name", sa.String(length=160), nullable=False),
        sa.Column("agency_phone", sa.String(length=32), nullable=True),
        sa.Column("agent_persona", sa.Text(), nullable=False),
        sa.Column("greeting_template", sa.Text(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("business_hours", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("agent_settings")
    op.drop_index("ix_properties_zone", table_name="properties")
    op.drop_index("ix_properties_source", table_name="properties")
    op.drop_table("properties")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_last_at", table_name="conversations")
    op.drop_index("ix_conversations_wa_thread_id", table_name="conversations")
    op.drop_index("ix_conversations_lead_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_leads_status_last_message_at", table_name="leads")
    op.drop_index("ix_leads_last_message_at", table_name="leads")
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_phone", table_name="leads")
    op.drop_table("leads")

    # Drop the enum types last (PostgreSQL keeps them around otherwise).
    for enum_name in (
        "message_status", "message_sender", "message_direction",
        "conversation_status", "lead_intent", "lead_status",
        "property_source",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

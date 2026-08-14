"""Conversation — one per (lead, channel). Holds a thread of Messages."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum
from app.db.text_limits import clip_string_columns

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.message import Message


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Declared so `alembic revision --autogenerate` does not propose
        # dropping what migration 022 created. Partial on purpose: closed
        # conversations are history, and a lead who returns months later
        # legitimately gets a new one.
        Index(
            "uq_conversations_active_per_lead_channel",
            "org_id",
            "lead_id",
            "channel",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Channel: "whatsapp" | "email" | "sms" | "voice" | …
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", nullable=False, index=True)
    # Channel-agnostic thread id (email uses In-Reply-To / Message-ID, WhatsApp uses
    # Meta thread id, SMS conversations have no thread so it's null).
    external_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    status: Mapped[ConversationStatus] = mapped_column(
        pg_enum(ConversationStatus, name="conversation_status"),
        default=ConversationStatus.ACTIVE,
        nullable=False,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )

    lead: Mapped["Lead"] = relationship("Lead", back_populates="conversations", lazy="joined")
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} lead_id={self.lead_id} channel={self.channel}>"

    # `external_thread_id` is the live one: on email it holds the provider's
    # thread key, which on a long forwarded chain of `References` headers runs
    # past 255. This row is written in the same transaction as the customer's
    # message, so refusing it loses the message rather than the field.
    _clip = clip_string_columns("channel", "external_thread_id", "status")


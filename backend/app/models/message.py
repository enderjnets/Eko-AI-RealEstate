"""Message — one row per WhatsApp message (inbound or outbound) inside a Conversation."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageSender(str, enum.Enum):
    LEAD = "lead"
    AGENT = "agent"  # the AI agent
    HUMAN = "human"  # human realtor takeover


class MessageStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    direction: Mapped[MessageDirection] = mapped_column(
        pg_enum(MessageDirection, name="message_direction"), nullable=False
    )
    sender: Mapped[MessageSender] = mapped_column(
        pg_enum(MessageSender, name="message_sender"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Channel-agnostic external identifier. Populated by:
    #   whatsapp → Meta wamid (e.g., "wamid.HBgM...")
    #   email    → Resend message id or RFC 822 Message-ID
    #   sms      → Twilio MessageSid (e.g., "SM…")
    #   voice    → Provider call_id
    # UNIQUE constraint enforces webhook idempotency (any provider may retry).
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    delivery_status: Mapped[MessageStatus] = mapped_column(
        pg_enum(MessageStatus, name="message_status"),
        default=MessageStatus.PENDING,
        nullable=False,
    )

    # Email-only (NULL for other channels).
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Provenance for outbound messages — which LLM generated this reply.
    llm_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages", lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_messages_external_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} conv={self.conversation_id} "
            f"dir={self.direction.value} sender={self.sender.value}>"
        )

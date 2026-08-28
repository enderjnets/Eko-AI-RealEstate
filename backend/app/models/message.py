"""Message — one row per WhatsApp message (inbound or outbound) inside a Conversation."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, pg_enum
from app.db.text_limits import clip_string_columns

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
    # Delivery is one HTTP POST to a provider that can be down, rate-limiting,
    # or slow. Without these a 503 meant the reply was stamped FAILED and
    # forgotten — no retry, and no worker looking for the ones left behind.
    send_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Email-only (NULL for other channels).
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Provenance for outbound messages — which LLM generated this reply.
    llm_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # What the Fair Housing filter found in this message on its way out, in
    # `find_violations` shape: [{"phrase": ..., "category": ...}].
    #
    # NULL and [] are different answers and both are used: NULL means the text
    # never went through the filter (every row written before v0.56, and the
    # inbound side, which is the lead's own words and not ours to police); []
    # means it WAS screened and came back clean, and it is stored as a real
    # empty JSON array, not as NULL.
    #
    # An earlier version of this comment said the caller wrote `[]` as NULL "to
    # keep the column sparse". That was the first design, and it was dropped
    # precisely because it destroys the distinction this column exists for — on
    # the one field whose whole value is telling "clean" apart from "never
    # looked". The code, the migration docstring and
    # `test_a_screened_clean_reply_is_an_empty_list_not_null` have always
    # agreed; only this comment disagreed.
    #
    # Deliberately NOT in `_clip` below: that list trims bounded strings and
    # this is JSONB.
    #
    # `none_as_null=True` is load-bearing, not tidiness. SQLAlchemy's default
    # for JSON columns stores a Python `None` as the JSON value `null`, which
    # is NOT SQL NULL — so `fair_housing_flags IS NOT NULL` matched every clean
    # reply, and the watcher reported a flagged day every day. An alarm that
    # fires on all-clear is worse than none: it is ignored within a week.
    fair_housing_flags: Mapped[list | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # A row that belongs in the lead's file but is NOT addressed to the lead —
    # today, the copy of the appointment invitation that goes to the agency's
    # booking mailbox. It lives in their thread so opening a conversation shows
    # that the agent was told, and when.
    #
    # Two machines walk this table by shape and BOTH must skip these rows:
    # `delivery.py::_still_owed` would re-send it TO THE LEAD, and the two
    # history builders in `conversation.py` would feed it to the LLM as a
    # conversational turn. The column alone is not the protection; those two
    # filters are, and each has a mutation test behind it.
    internal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages", lazy="joined"
    )

    __table_args__ = (
        # Per organization: the idempotency guard against Meta's delivery
        # retries only has to hold within one tenant's inbox.
        UniqueConstraint("org_id", "external_id", name="uq_messages_external_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} conv={self.conversation_id} "
            f"dir={self.direction.value} sender={self.sender.value}>"
        )

    # Every bounded string on `messages`, trimmed on write. `subject` is the live one: an email Subject header has no length limit and this column is 500.
    #
    # Postgres refuses an over-long value rather than truncating it, and on the
    # inbound paths that refusal rolls back the transaction holding what the
    # customer actually said. See `app/db/text_limits.py`. A test walks this
    # table and fails if a bounded column is missing from the list, because
    # forgetting one is exactly how this kept happening.
    # `external_id` is deliberately absent from this list: it is the
    # idempotency key, UNIQUE per organisation, so a plain slice makes two
    # distinct provider ids collide and the second message is filed as a
    # duplicate that never happened. It gets the digest treatment below.
    _clip = clip_string_columns(
        "direction",
        "sender",
        "delivery_status",
        "last_error",
        "subject",
        "llm_provider",
        "llm_model",
    )

    @validates("external_id")
    def _clip_external_id(self, _key: str, value: object) -> object:
        """Keep two different provider ids two different messages.

        This is the idempotency key. Truncating it means a message whose id
        shares a prefix with another is silently filed as already-seen — the
        customer wrote, we answered nothing, and there is no error anywhere.
        """
        from app.services._common import clip_identifier  # local: avoids a cycle

        return clip_identifier(value) if isinstance(value, str) else value

def chronological():
    """The one true reading order for a conversation, exported so the endpoints
    cannot drift apart.

    `created_at` alone is not an order. A voice call writes its whole transcript
    when the caller hangs up, so every turn shares one timestamp to the
    microsecond — a real call left 27 rows on 2 distinct values — and Postgres
    is then free to return them however the plan happens to produce them. The
    realtor opened the file and read the answer above the question.

    Exported for the same reason `inbox.reached_somebody()` is: two endpoints
    render the same thread and one of them had been updated and the other not.
    One expression, imported by both, and a single place to put this comment.

    Deliberately a function, not a module-level tuple: SQLAlchemy order
    criteria are reusable, but a mutable module global that several queries
    append to is a trap, and a fresh tuple per call costs nothing.
    """
    return (Message.created_at.asc(), Message.id.asc())

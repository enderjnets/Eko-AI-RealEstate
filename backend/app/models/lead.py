"""Lead — one row per real-estate prospect that contacted us on WhatsApp."""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum
from app.db.text_limits import clip_string_columns

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.visit import Visit


class LeadStatus(str, enum.Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    VISITING = "visiting"
    POST_VISIT = "post_visit"
    WON = "won"
    LOST = "lost"
    PAUSED = "paused"


class LeadIntent(str, enum.Enum):
    RENT = "rent"
    BUY = "buy"
    VALUATION = "valuation"
    OTHER = "other"


class PreferredChannel(str, enum.Enum):
    """The channel this person asked to be reached on.

    Only SMS has an automated sender behind it. The other two are honoured by a
    human working the console's list, and that is a deliberate limit rather
    than an omission:

    * `CALL` — there is no voice provider wired up (Phase 13 is deferred), and
      an automated call to a mobile is the thing TCPA exists to punish.
    * `EMAIL` — `services/email.py` sends no unsubscribe header and no physical
      address, and `optout.py` does not recognise email at all. Automated
      commercial email without a working opt-out is a CAN-SPAM violation, so
      the sender stays human until those three exist.

    A follow-up for either becomes a task, never an outbound message. See
    `followups.AUTOMATED_PREFERENCES`.
    """

    SMS = "sms"
    EMAIL = "email"
    CALL = "call"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # `phone` historically held a phone number, but Phase 3 multichannel uses it
    # as a generic identifier: phone numbers for whatsapp/sms/voice, email
    # addresses for email. Widened to 254 chars (RFC 5321 max email length).
    # A future migration will rename it to `identifier`.
    # Unique per organization, not globally: two agencies may legitimately work
    # the same prospect. The composite index lives in __table_args__ so
    # autogenerate does not "helpfully" restore the global one.
    phone: Mapped[str] = mapped_column(String(254), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # Nullable, and usually null: a WhatsApp or SMS lead gives a phone and
    # nothing else. Kept because a real address is worth having when we do get
    # one — from the email channel, from a discovery import, or from the lead
    # telling us — and because a booking that has one can send the client their
    # own confirmation instead of only the agency's.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[LeadStatus] = mapped_column(
        pg_enum(LeadStatus, name="lead_status"),
        default=LeadStatus.NEW,
        nullable=False,
        index=True,
    )
    intent: Mapped[LeadIntent | None] = mapped_column(
        pg_enum(LeadIntent, name="lead_intent"),
        nullable=True,
    )

    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(160), nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(40), nullable=True)

    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    human_takeover: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Lead intelligence (Phase 8): 0-100 priority score + an explainable breakdown
    # of the signals that produced it. Recomputed after each inbound turn.
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # How this person asked to be contacted, when they said so on a call. It
    # narrows the channels the follow-up worker may pick and never widens them:
    # a preference is not permission. Someone who says "text me" but has no
    # `consent_at` is still held, exactly as before — see
    # `followups.process_due_followups`.
    preferred_channel: Mapped[PreferredChannel | None] = mapped_column(
        pg_enum(PreferredChannel, name="preferred_channel"), nullable=True
    )

    # TCPA: what this lead agreed to, and where they were when they agreed.
    # Set by the public capture form and by the call console when the person
    # asks on the phone to be sent something; never cleared, and never
    # overwritten once present — consent is a historical fact and the first
    # record of it is the one that was actually shown or spoken.
    # `consent_text` is the disclosure exactly as rendered,
    # because the obligation is to show what the person was reading, not to
    # assert that something was shown. Columns rather than `meta` keys so an
    # audit is one query and so enrichment writers cannot clobber them.
    consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    consent_user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    # When they told us to stop, on which channel, and with which word. Set by
    # the inbound path, never by the form. Outranks `consent_at` everywhere:
    # consent is permission to start, this is an instruction to stop, and an
    # instruction to stop is the more recent statement of what they want.
    opted_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opted_out_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    opted_out_keyword: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Inbox triage: when a realtor marked this lead handled. A lead is "pending"
    # if its last message is inbound and this is null or older than that message.
    # A dedicated column (not meta JSON) so marking handled never races with other
    # writers to meta (e.g. discovery enrichment).
    inbox_handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    visits: Mapped[list["Visit"]] = relationship(
        "Visit",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="Visit.scheduled_at",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_leads_status_last_message_at", "status", "last_message_at"),
        Index("ix_leads_phone", "org_id", "phone", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Lead id={self.id} phone={self.phone} status={self.status.value}>"

    # Every bounded string on `leads`, trimmed on write.
    #
    # Postgres refuses an over-long value rather than truncating it, and on the
    # inbound paths that refusal rolls back the transaction holding what the
    # customer actually said. See `app/db/text_limits.py`. A test walks this
    # table and fails if a bounded column is missing from the list, because
    # forgetting one is exactly how this kept happening.
    _clip = clip_string_columns(
        "phone",
        "name",
        "email",
        "status",
        "intent",
        "zone",
        "property_type",
        "urgency",
        "preferred_channel",
        "consent_ip",
        "consent_user_agent",
        "opted_out_channel",
        "opted_out_keyword",
    )


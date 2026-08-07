"""Which organization owns an inbound destination.

Inbound messages carry no session, so the only thing that can attribute them to
an agency is where they arrived: the Twilio number that was texted, the
WhatsApp phone-number id, the mailbox. Without this table every webhook
defaulted to the first organization — which meant a second agency's leads and
entire conversation transcripts were written into the first agency's dashboard
while the real recipient saw nothing.

`destination` is unique per channel ACROSS organizations, not within one: a
phone number belongs to exactly one agency, and two agencies claiming the same
number is the ambiguity this exists to prevent. That is why the uniqueness is
global here while `leads.phone` is per-org — this is routing, not business data.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_SMS = "sms"
CHANNEL_EMAIL = "email"
CHANNEL_VOICE = "voice"

CHANNELS = (CHANNEL_WHATSAPP, CHANNEL_SMS, CHANNEL_EMAIL, CHANNEL_VOICE)


def normalize_destination(value: str | None) -> str:
    """Compare destinations the way providers vary them, not byte-for-byte.

    Twilio sends `+15551234567`, a form post may arrive as `15551234567`, and an
    address as `Sales@Agency.COM`. Storing and looking up a normalised form is
    what stops a routing miss from silently becoming a 503.
    """
    v = (value or "").strip().lower()
    if "@" in v:
        return v
    return "".join(ch for ch in v if ch.isdigit())


class ChannelRoute(Base):
    __tablename__ = "channel_routes"
    __table_args__ = (
        Index("uq_channel_routes_dest", "channel", "destination", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    # Already normalised — callers go through normalize_destination().
    destination: Mapped[str] = mapped_column(String(254), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ChannelRoute {self.channel}:{self.destination} → org {self.org_id}>"

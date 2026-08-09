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
# Not an inbound channel: nothing is ever delivered TO it. It rides here so a
# calendar gets the same per-organization credential handling as the rest —
# without it every agency booked visits onto the operator's own Cal.com,
# putting their leads' names, emails and phone numbers in front of another
# agency's realtors.
CHANNEL_CALENDAR = "calendar"

CHANNELS = (
    CHANNEL_WHATSAPP,
    CHANNEL_SMS,
    CHANNEL_EMAIL,
    CHANNEL_VOICE,
    CHANNEL_CALENDAR,
)
# The ones a provider actually delivers to.
INBOUND_CHANNELS = (CHANNEL_WHATSAPP, CHANNEL_SMS, CHANNEL_EMAIL, CHANNEL_VOICE)


def normalize_destination(value: str | None) -> str:
    """Compare destinations the way providers vary them, not byte-for-byte.

    Twilio sends `+15551234567`, a form post may arrive as `15551234567`, and an
    address as `Sales@Agency.COM`. Storing and looking up a normalised form is
    what stops a routing miss from silently becoming a 503.
    """
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "@" in v:
        return v

    # Extensions first: they carry letters (`;ext=`) that would otherwise make
    # a perfectly ordinary number look like an opaque id.
    for sep in (";ext=", ";", ",", " x"):
        if sep in v:
            v = v.split(sep, 1)[0]

    # A provider id (VAPI phone-number UUID, WhatsApp phone_number_id) is an
    # opaque token, not a number — reducing it to digits collided distinct ids.
    # Formatting characters common in phone numbers are not evidence of one.
    if any(ch.isalpha() or ch == "_" for ch in v):
        return v.strip()

    digits = "".join(ch for ch in v if ch.isdigit())
    # 0019995550001, +19995550001 and 19995550001 are one destination.
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


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

    # ── Outbound identity ────────────────────────────────────────────────
    # For SMS, WhatsApp and email the `destination` above IS the sending
    # identity: the number that was texted is the number that replies, the
    # mailbox that received is the mailbox that answers. What is missing per
    # agency is the *credentials* to send as it, and the secret to verify what
    # it receives. Without them a second agency's lead got a reply from the
    # first agency's number, answered that number, and the rest of their
    # conversation was written into the first agency's tenant. No adversary
    # required — that was simply how it worked.
    #
    # These hold the NAME of an environment variable, never the secret itself.
    # Keys stay in `.env`, which is the repo's standing rule, and the database
    # holds only the mapping: org 2's Twilio token lives in
    # TWILIO_AUTH_TOKEN_ACME and this row says so. Encrypting secrets at rest
    # would let agencies self-serve their own credentials; that is a later
    # decision, and this shape does not block it.
    #
    # NULL means "use the global configuration", which is what keeps a
    # single-customer install working with nothing but a .env file.
    provider_account_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inbound_secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verify_token_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Not a secret: a messaging-service SID, a `Name <addr>` display form, or a
    # VAPI assistant id — whatever the channel sends *as* beyond the bare
    # destination.
    sender_override: Mapped[str | None] = mapped_column(String(254), nullable=True)
    # The exact public URL the provider signs. Two agencies on different
    # tunnels or paths cannot share one, and a mismatch fails every signature.
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ChannelRoute {self.channel}:{self.destination} → org {self.org_id}>"

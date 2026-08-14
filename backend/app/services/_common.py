"""Shared types across channel services (WhatsApp, Email, SMS, Voice)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ChannelName = Literal["whatsapp", "email", "sms", "voice"]


@dataclass(frozen=True)
class ParsedMessage:
    """Channel-agnostic representation of one inbound message after parsing.

    Populated by each channel's webhook handler (whatsapp.parse_inbound_message,
    email.parse_inbound_email, sms.parse_inbound_sms, …) and consumed by the
    orchestrator (services/conversation.py).

    `from_identifier` is whatever the channel uses to address a person:
      whatsapp / sms / voice → phone number (E.164 or raw digits)
      email                  → email address
    """

    channel: ChannelName
    external_id: str
    from_identifier: str
    from_name: str | None
    content: str
    msg_type: str = "text"  # text | image | audio | video | document | location | …
    subject: str | None = None  # email only
    thread_id: str | None = None  # email threading (In-Reply-To / References)
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Clip the identifier here, where the message enters the system.

        `leads.phone` is 254 characters and UNIQUE per organisation, and it is
        the key everything looks a person up by. Trimming it at the model — as
        the text limits do for free-text columns — makes the write and the
        lookup disagree: the first message stores a 254-character row, the
        second searches for the original 280-character value, finds nothing,
        tries to insert, and hits the unique index. That turns "the first
        message is lost" into "every message after the first is lost", which is
        worse for being harder to notice.

        An identifier is identity, not prose, so it gets normalised once, at the
        boundary, and everything downstream agrees by construction.
        """
        if len(self.from_identifier) > 254:
            object.__setattr__(self, "from_identifier", self.from_identifier[:254])


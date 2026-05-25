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

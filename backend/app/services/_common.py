"""Shared types across channel services (WhatsApp, Email, SMS, Voice)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

ChannelName = Literal["whatsapp", "email", "sms", "voice"]


def clip_identifier(identifier: str) -> str:
    """Make an identifier fit `leads.phone` (254, UNIQUE) without losing who it is.

    Kept whole it can fail the write and roll back the transaction holding the
    customer's words; truncated, two senders sharing a prefix collapse into one
    lead and one person's messages land in another's thread. A readable head
    plus a digest of the whole value is neither.
    """
    if len(identifier) <= 254:
        return identifier
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:40]
    return f"{identifier[:213]}~{digest}"


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
        """Make the identifier fit the column without losing who it is.

        `leads.phone` is 254 characters and UNIQUE per organisation, and it is
        the key everything looks a person up by. Two failures live here and
        they pull in opposite directions:

        - Store it whole and Postgres refuses the write, which rolls back the
          transaction holding the customer's message. The provider replays an
          identical payload, so every retry fails the same way.
        - Truncate it and two senders sharing a 254-character prefix become one
          lead. That is worse than losing a message: one person's words land in
          another person's thread, and it can be arranged deliberately.

        So an over-long identifier keeps a readable head and a digest of the
        whole thing. It fits, it is deterministic, and two different senders
        stay two different people. Nothing can reply to an address that long
        anyway — it is already invalid under RFC 5321, whose own limit is 254.
        """
        object.__setattr__(
            self, "from_identifier", clip_identifier(self.from_identifier)
        )
        # The provider's message id is the idempotency key, and the lookup that
        # decides "have we seen this already?" happens before the row is
        # written — so it has to be normalised here too, or the search and the
        # stored value disagree and every replay looks new.
        object.__setattr__(self, "external_id", clip_identifier(self.external_id))


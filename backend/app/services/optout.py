"""Recognising "stop", and honouring it.

The capture form tells every visitor, in both languages, that they can reply
STOP to opt out. That sentence is stored verbatim as their consent record, so
it is not marketing copy — it is a term of the agreement the record documents.

Deliberately keyword matching and not the LLM. Three reasons, in order:

- A revocation must be recognised when the model is down, out of quota, or
  answering slowly. `_fallback_reply` exists precisely because that happens.
- It must be recognised identically every time. A probabilistic opt-out is one
  that occasionally does not happen, and the failure is invisible.
- The carriers implement it this way. On the US networks STOP is intercepted at
  the aggregator regardless of what the application does, so an app that
  disagrees with the keyword list ends up with its own state out of step with
  the carrier's — believing it may send to somebody the network will not
  deliver to.
"""
from __future__ import annotations

# The CTIA short-code keywords, plus the Spanish a bilingual Denver audience
# actually types. Matched on the whole message, not as substrings: "stop by the
# open house on Sunday?" is a question about a viewing, and treating it as a
# revocation loses a live buyer.
STOP_WORDS = frozenset(
    {
        "stop",
        "stopall",
        "unsubscribe",
        "cancel",
        "end",
        "quit",
        "optout",
        "opt-out",
        "revoke",
        "parar",
        "para",
        "baja",
        "cancelar",
        "detener",
        "eliminar",
    }
)

# CTIA requires a way back in, and it must be as simple as the way out.
START_WORDS = frozenset(
    {
        "start",
        "unstop",
        "yes",
        "resume",
        "subscribe",
        "optin",
        "opt-in",
        "alta",
        "empezar",
        "reanudar",
        "si",
        "sí",
    }
)

# Only these carry a legal opt-out meaning. Email unsubscribes are a link and a
# List-Unsubscribe header, not a one-word reply, and treating a one-word email
# as a revocation would silence a lead who simply wrote "cancel" about a
# viewing appointment.
OPT_OUT_CHANNELS = frozenset({"sms", "whatsapp", "voice"})


def _normalise(text: str | None) -> str:
    """Lowercase, strip punctuation and whitespace, collapse to one token."""
    cleaned = (text or "").strip().lower()
    # Carriers ignore surrounding punctuation: "STOP." and "(stop)" both count.
    return cleaned.strip(".,!¡?¿;:'\"()[]{}- \t\n\r")


def opt_out_keyword(text: str | None, channel: str) -> str | None:
    """The stop word this message is, or None. Whole message only."""
    if channel not in OPT_OUT_CHANNELS:
        return None
    token = _normalise(text)
    return token if token in STOP_WORDS else None


def opt_in_keyword(text: str | None, channel: str) -> str | None:
    """The resume word this message is, or None."""
    if channel not in OPT_OUT_CHANNELS:
        return None
    token = _normalise(text)
    return token if token in START_WORDS else None


# The single message CTIA requires after a STOP, and the only one that may be
# sent afterwards. Kept short and free of any offer: a confirmation that sells
# something is a marketing message to somebody who just said stop.
CONFIRMATION = {
    "en": "You're unsubscribed and won't get any more automated messages from us. Reply START to resume.",
    "es": "Te has dado de baja y no recibirás más mensajes automáticos. Responde ALTA para volver a activarlos.",
}

RESUMED = {
    "en": "You're subscribed again. Reply STOP at any time to opt out.",
    "es": "Te has vuelto a suscribir. Responde STOP en cualquier momento para darte de baja.",
}

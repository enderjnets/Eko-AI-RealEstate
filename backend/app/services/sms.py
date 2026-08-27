"""SMS channel — Twilio Programmable Messaging + inbound webhook.

Inbound flow:
  Twilio POSTs `application/x-www-form-urlencoded` to our webhook → we validate
  the `X-Twilio-Signature` (HMAC-SHA1 over the request URL + sorted POST params,
  keyed by the auth token) → parse_inbound_sms() returns a ParsedMessage
  (channel="sms") → the orchestrator routes it like every other channel.

Outbound flow:
  send_sms(to, body) POSTs to the Twilio REST API. When SMS_SIMULATED=true
  (dev default), it LOGS the payload and returns a synthetic sid — so SMS works
  end to end without a Twilio account.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any
from uuid import uuid4

import httpx

from app.config import get_settings
from app.models.channel_route import CHANNEL_SMS, mask_destination
from app.services._common import ParsedMessage
from app.services.channel_identity import resolve_outbound_identity

log = logging.getLogger(__name__)

__all__ = ["verify_twilio_signature", "parse_inbound_sms", "send_sms", "twilio_status_to_delivery"]

_TWILIO_API_ROOT = "https://api.twilio.com/2010-04-01"

# Twilio MessageStatus → our MessageStatus enum VALUE (lowercase string).
_STATUS_MAP = {
    "queued": "pending",
    "sending": "pending",
    "accepted": "pending",
    "scheduled": "pending",
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "undelivered": "failed",
    "failed": "failed",
}


def twilio_status_to_delivery(twilio_status: str) -> str | None:
    """Map a Twilio MessageStatus to our delivery_status value (or None if unknown)."""
    return _STATUS_MAP.get((twilio_status or "").lower())


# ── Signature verification ─────────────────────────────────────────────────


def verify_twilio_signature(url: str, params: dict[str, str], signature: str | None, *, auth_token: str) -> bool:
    """Validate a Twilio webhook `X-Twilio-Signature`.

    Twilio builds the signature as:
      base64( HMAC-SHA1( auth_token, url + concat(sorted POST params as k+v) ) )
    where `url` is the exact public URL Twilio requested (incl. any query string).
    Empty auth_token / signature → False (the route allows unsigned only when
    SMS_SIMULATED).
    """
    if not (signature and auth_token):
        return False
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


# ── Inbound payload parsing ────────────────────────────────────────────────


def parse_inbound_sms(form: dict[str, str]) -> ParsedMessage | None:
    """Build a ParsedMessage from a Twilio inbound-SMS form payload.

    Twilio form fields we use: MessageSid, From (E.164 sender), Body, To.
    SMS carries no display name. Returns None if essential fields are missing.
    """
    sid = form.get("MessageSid") or form.get("SmsSid") or ""
    from_number = form.get("From") or ""
    body = (form.get("Body") or "").strip()
    if not sid or not from_number:
        log.warning("Inbound SMS missing MessageSid/From — skipping: %r", form)
        return None

    return ParsedMessage(
        channel="sms",
        external_id=sid,
        from_identifier=from_number,
        from_name=None,
        content=body,
        msg_type="text",
        extra={"to": form.get("To")},
    )


# ── Outbound send ──────────────────────────────────────────────────────────


async def send_sms(*, to: str, body: str) -> dict[str, Any]:
    """Send an SMS via Twilio, or LOG when SMS_SIMULATED=true.

    Returns `{"sid": "<message sid>", "simulated": bool}`.
    """
    s = get_settings()

    if s.SMS_SIMULATED:
        # Random, not a millisecond timestamp. Two replies dispatched in the
        # same millisecond produced the same "unique" id and collided on
        # uq_messages_external_id, which took the whole inbound turn down with
        # it — in the demo and dev modes, which is where nobody is watching.
        fake_sid = f"SM_SIMULATED_{uuid4().hex}"
        log.info(
            "SMS SIMULATED outbound to=%s body_len=%d (would-be sid=%s)",
            mask_destination(to),
            len(body),
            fake_sid,
        )
        return {"sid": fake_sid, "simulated": True}

    # Which agency is speaking. Falls back to the global .env configuration when
    # this organization has no account of its own, so a single-customer install
    # is unaffected — but when it does have one, the reply must leave from THEIR
    # number. It used to leave from the first agency's, so the lead answered the
    # wrong agency and the rest of the conversation landed in the wrong tenant.
    identity = await resolve_outbound_identity(CHANNEL_SMS)
    account_sid = identity.provider_account
    auth_token = identity.credential
    # Basic-auth username. With a Twilio API Key configured this is the key's
    # own `SK…` SID; otherwise it is the Account SID, exactly as before. The
    # account in the URL path below does NOT change either way — that is always
    # the Account SID, which is why the two are kept apart here.
    auth_user = identity.credential_user or account_sid
    messaging_service = identity.sender_override
    from_number = identity.destination

    # Need a sender: either a Messaging Service (A2P) or a From number.
    if not (account_sid and auth_token) or not (messaging_service or from_number):
        raise RuntimeError(
            "SMS not configured for this organization: account SID + auth token "
            "+ (messaging service or from number) must be set, either globally "
            "in .env or on the agency's channel route. Set SMS_SIMULATED=true "
            "for dev."
        )

    data: dict[str, str] = {"To": to, "Body": body}
    # Prefer the Messaging Service (A2P 10DLC): Twilio picks the sender from the
    # registered pool. Fall back to the bare From number.
    if messaging_service:
        data["MessagingServiceSid"] = messaging_service
    else:
        data["From"] = from_number
    if s.TWILIO_STATUS_CALLBACK_URL:
        data["StatusCallback"] = s.TWILIO_STATUS_CALLBACK_URL

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{_TWILIO_API_ROOT}/Accounts/{account_sid}/Messages.json",
            data=data,
            auth=(auth_user, auth_token),
        )
        if resp.status_code >= 400:
            log.error("Twilio send failed: status=%d body=%s", resp.status_code, resp.text[:400])
        resp.raise_for_status()
        payload = resp.json()
    return {"sid": payload.get("sid"), "status": payload.get("status"), "simulated": False}

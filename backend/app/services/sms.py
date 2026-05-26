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
import time
from typing import Any

import httpx

from app.config import get_settings
from app.services._common import ParsedMessage

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
        fake_sid = f"SM_SIMULATED_{int(time.time() * 1000)}"
        log.info("SMS SIMULATED outbound to=%s body_len=%d (would-be sid=%s)", to, len(body), fake_sid)
        return {"sid": fake_sid, "simulated": True}

    # Need a sender: either a Messaging Service (A2P) or a From number.
    if not (s.TWILIO_ACCOUNT_SID and s.TWILIO_AUTH_TOKEN) or not (
        s.TWILIO_MESSAGING_SERVICE_SID or s.TWILIO_PHONE_NUMBER
    ):
        raise RuntimeError(
            "SMS not configured: TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + "
            "(TWILIO_MESSAGING_SERVICE_SID or TWILIO_PHONE_NUMBER) must be set, "
            "or set SMS_SIMULATED=true for dev."
        )

    data: dict[str, str] = {"To": to, "Body": body}
    # Prefer the Messaging Service (A2P 10DLC): Twilio picks the sender from the
    # registered pool. Fall back to the bare From number.
    if s.TWILIO_MESSAGING_SERVICE_SID:
        data["MessagingServiceSid"] = s.TWILIO_MESSAGING_SERVICE_SID
    else:
        data["From"] = s.TWILIO_PHONE_NUMBER
    if s.TWILIO_STATUS_CALLBACK_URL:
        data["StatusCallback"] = s.TWILIO_STATUS_CALLBACK_URL

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{_TWILIO_API_ROOT}/Accounts/{s.TWILIO_ACCOUNT_SID}/Messages.json",
            data=data,
            auth=(s.TWILIO_ACCOUNT_SID, s.TWILIO_AUTH_TOKEN),
        )
        if resp.status_code >= 400:
            log.error("Twilio send failed: status=%d body=%s", resp.status_code, resp.text[:400])
        resp.raise_for_status()
        payload = resp.json()
    return {"sid": payload.get("sid"), "status": payload.get("status"), "simulated": False}

"""Email channel — Resend transactional API + inbound webhook.

Inbound flow:
  Resend POSTs the webhook → we verify the Svix-style HMAC signature with
  RESEND_WEBHOOK_SECRET → parse_inbound_email() returns ParsedMessage objects
  (channel="email") → the orchestrator routes through `conversation.handle_inbound_message`
  same as WhatsApp.

Outbound flow:
  send_email(to, subject, body_text, in_reply_to=None) POSTs to api.resend.com.
  When EMAIL_SIMULATED=true (dev default), it LOGS the payload and returns a
  synthetic id. Lets us develop without a Resend account or verified domain.

Threading: emails carry `In-Reply-To` + `References` headers; we surface the
original Message-ID via ParsedMessage.thread_id so the orchestrator places the
new message in the same Conversation row (matched by Conversation.external_thread_id).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from app.config import get_settings
from app.services._common import ParsedMessage

log = logging.getLogger(__name__)

__all__ = [
    "verify_resend_signature",
    "parse_inbound_email",
    "send_email",
]


# ── Signature verification (Resend uses Svix-compatible signing) ───────


def verify_resend_signature(
    body: bytes,
    *,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    secret: str,
) -> bool:
    """Verify a Svix-style signed webhook payload.

    Resend signs `{svix_id}.{svix_timestamp}.{body_utf8}` with HMAC-SHA256
    using the webhook secret (base64-decoded after the `whsec_` prefix is
    stripped). The signature header carries one or more `v1,<base64>` entries
    space-separated; any match counts.

    If `secret` is empty (dev mode without webhook configured), this returns
    False so the route can decide to allow unsigned requests when SIMULATED.
    """
    if not (svix_id and svix_timestamp and svix_signature and secret):
        return False

    # Optional `whsec_` prefix on the secret + base64 body.
    key_material = secret.removeprefix("whsec_")
    try:
        import base64

        key = base64.b64decode(key_material)
    except Exception:
        # If the secret isn't valid base64, fall back to raw bytes.
        key = key_material.encode("utf-8")

    signed_payload = f"{svix_id}.{svix_timestamp}.{body.decode('utf-8', errors='replace')}".encode()
    expected = hmac.new(key, signed_payload, hashlib.sha256).digest()

    import base64

    expected_b64 = base64.b64encode(expected).decode("ascii")

    # Header may contain multiple "v1,<sig>" entries separated by spaces.
    for entry in svix_signature.split(" "):
        if "," not in entry:
            continue
        version, sig = entry.split(",", 1)
        if version != "v1":
            continue
        if hmac.compare_digest(sig.strip(), expected_b64):
            return True
    return False


# ── Inbound payload parsing ────────────────────────────────────────────


def parse_inbound_email(payload: dict[str, Any]) -> list[ParsedMessage]:
    """Extract ParsedMessage(s) from a Resend inbound webhook payload.

    Resend sends one payload per inbound email. Shape (simplified):
      {
        "type": "email.received",
        "data": {
          "id": "<resend message id>",
          "from": "lead@example.com",
          "from_name": "Juan García",          // optional
          "to": ["info@realtor.com"],
          "subject": "Consulta piso Madrid",
          "text": "...",
          "html": "...",
          "headers": {
            "message-id": "<rfc822 id>",
            "in-reply-to": "<previous msg id>",
            "references": "<id1> <id2>"
          }
        }
      }
    """
    data = (payload.get("data") or {}) if isinstance(payload, dict) else {}
    if (payload.get("type") and payload["type"] != "email.received"):
        log.debug("Ignoring non-inbound Resend event: %s", payload.get("type"))
        return []
    if not data:
        return []

    headers = data.get("headers") or {}
    # Normalize header casing — Resend sends lowercase but defend.
    headers_lower = {k.lower(): v for k, v in headers.items()}

    msg_id = (
        headers_lower.get("message-id")
        or data.get("id")
        or f"resend-{int(time.time() * 1000)}"
    )
    in_reply_to = headers_lower.get("in-reply-to")
    references = headers_lower.get("references", "")
    # Thread key: prefer in-reply-to, fall back to the oldest reference, fall back to our own msg id.
    thread_id = in_reply_to or (references.split()[0] if references else msg_id)

    from_addr = data.get("from") or ""
    if not from_addr:
        log.warning("Email payload has no `from` — skipping: %r", data)
        return []
    from_name = data.get("from_name")

    subject = data.get("subject") or ""
    body = (data.get("text") or "").strip()
    if not body and data.get("html"):
        # Phase 3 keeps it simple: drop tags with a one-liner. Phase 4+ could
        # use BeautifulSoup for proper extraction.
        import re

        body = re.sub(r"<[^>]+>", " ", data["html"])
        body = re.sub(r"\s+", " ", body).strip()

    return [
        ParsedMessage(
            channel="email",
            external_id=msg_id,
            from_identifier=from_addr,
            from_name=from_name,
            content=body,
            msg_type="text",
            subject=subject,
            thread_id=thread_id,
        )
    ]


# ── Outbound send ──────────────────────────────────────────────────────


async def send_email(
    *,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    in_reply_to: str | None = None,
) -> dict[str, Any]:
    """Send via Resend, or LOG when EMAIL_SIMULATED=true.

    Returns Resend's response dict (or a synthetic equivalent in simulated mode):
      {"id": "<resend message id>", "simulated": true | false}
    """
    s = get_settings()

    if s.EMAIL_SIMULATED:
        fake_id = f"resend.SIMULATED_{int(time.time() * 1000)}"
        log.info(
            "Email SIMULATED outbound to=%s subject=%r body_len=%d in_reply_to=%s (would-be id=%s)",
            to, subject, len(body_text), in_reply_to, fake_id,
        )
        return {"id": fake_id, "simulated": True}

    if not s.RESEND_API_KEY:
        raise RuntimeError(
            "Email not configured: RESEND_API_KEY must be set, or set "
            "EMAIL_SIMULATED=true for dev."
        )

    headers: dict[str, str] = {}
    if in_reply_to:
        # Strip surrounding <> if present, add them back per RFC.
        clean = in_reply_to.strip().lstrip("<").rstrip(">")
        headers["In-Reply-To"] = f"<{clean}>"
        headers["References"] = f"<{clean}>"

    body: dict[str, Any] = {
        "from": s.RESEND_FROM,
        "to": [to],
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        body["html"] = body_html
    if headers:
        body["headers"] = headers

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json=body,
            headers={
                "Authorization": f"Bearer {s.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code >= 400:
            log.error("Resend send failed: status=%d body=%s", resp.status_code, resp.text[:400])
        resp.raise_for_status()
        return resp.json()

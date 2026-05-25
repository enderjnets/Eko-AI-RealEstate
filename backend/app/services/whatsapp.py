"""WhatsApp Business Cloud API — inbound signature verify, parse, outbound send.

Inbound flow:
  Meta POSTs the webhook → we verify HMAC-SHA256 with WHATSAPP_APP_SECRET →
  parse_inbound_message() flattens the entry/changes/value/messages tree into
  ParsedMessage dataclasses (channel="whatsapp") → the orchestrator
  (`app/services/conversation.py`) takes it from there.

Outbound flow:
  send_text_message(to_phone, text) POSTs to Graph API and returns the wamid.
  When WHATSAPP_SIMULATED=true (dev default), it LOGS the payload instead and
  returns a fake `wamid.SIMULATED_<unix_ts>`. This lets us develop + run E2E
  tests without registering a Meta Business app.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from app.config import get_settings
from app.services._common import ParsedMessage  # re-export below for backwards-compat

log = logging.getLogger(__name__)

__all__ = [
    "ParsedMessage",
    "verify_signature",
    "parse_inbound_message",
    "send_text_message",
]


# ── Signature verification ─────────────────────────────────────────────


def verify_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Meta signs the webhook body with HMAC-SHA256(app_secret).

    Header format: `X-Hub-Signature-256: sha256=<hex>`. Use `hmac.compare_digest`
    for constant-time comparison (avoids timing attacks).
    """
    if not signature_header or not app_secret:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    received = signature_header[len(prefix):]
    return hmac.compare_digest(expected, received)


# ── Inbound payload parsing ────────────────────────────────────────────


_NON_TEXT_PLACEHOLDER = {
    "image":    "[imagen]",
    "audio":    "[audio]",
    "video":    "[video]",
    "document": "[documento]",
    "location": "[ubicación]",
    "contacts": "[contacto]",
    "sticker":  "[sticker]",
    "button":   "[botón]",
    "interactive": "[interactivo]",
    "reaction": "[reacción]",
}


def parse_inbound_message(payload: dict[str, Any]) -> list[ParsedMessage]:
    """Flatten Meta's nested webhook payload into a list of ParsedMessage.

    A single webhook can carry multiple messages from multiple contacts. Non-text
    types are kept as placeholders (`[imagen]`, `[audio]`, …) so the human realtor
    can decide how to handle them — Phase 1 does not transcribe or describe media.
    """
    out: list[ParsedMessage] = []

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts_by_id = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in (value.get("contacts") or [])
            }
            for msg in value.get("messages") or []:
                msg_type = msg.get("type", "text")
                msg_id = msg.get("id")
                from_phone = msg.get("from")
                if not msg_id or not from_phone:
                    log.warning("Skipping malformed inbound message: %r", msg)
                    continue

                if msg_type == "text":
                    text = ((msg.get("text") or {}).get("body") or "").strip()
                else:
                    text = _NON_TEXT_PLACEHOLDER.get(msg_type, f"[{msg_type}]")

                out.append(
                    ParsedMessage(
                        channel="whatsapp",
                        external_id=msg_id,
                        from_identifier=from_phone,
                        from_name=contacts_by_id.get(from_phone),
                        content=text,
                        msg_type=msg_type,
                    )
                )

    return out


# ── Outbound send ──────────────────────────────────────────────────────


async def send_text_message(to_phone: str, text: str) -> dict[str, Any]:
    """Send a text message via Meta Graph API, or LOG it when SIMULATED=true.

    Returns Meta's response dict (or a fake equivalent in simulated mode). The
    orchestrator extracts `messages[0].id` as the wa_message_id to persist.
    """
    s = get_settings()

    if s.WHATSAPP_SIMULATED:
        fake_id = f"wamid.SIMULATED_{int(time.time() * 1000)}"
        log.info(
            "WhatsApp SIMULATED outbound to=%s len=%d text=%r (would-be wamid=%s)",
            to_phone, len(text), text[:120], fake_id,
        )
        return {"messages": [{"id": fake_id}], "simulated": True}

    if not s.WHATSAPP_ACCESS_TOKEN or not s.WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError(
            "WhatsApp not configured: WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID "
            "must be set, or set WHATSAPP_SIMULATED=true for dev."
        )

    url = (
        f"https://graph.facebook.com/{s.WHATSAPP_GRAPH_API_VERSION}"
        f"/{s.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {s.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code >= 400:
            log.error(
                "WhatsApp send failed: status=%d body=%s", resp.status_code, resp.text[:400]
            )
        resp.raise_for_status()
        return resp.json()

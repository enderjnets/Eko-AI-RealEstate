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
from uuid import uuid4

import httpx

from app.config import get_settings
from app.models.channel_route import CHANNEL_EMAIL
from app.services._common import ParsedMessage
from app.services.channel_identity import resolve_outbound_identity

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


async def fetch_inbound_email(email_id: str) -> dict[str, Any] | None:
    """Fetch the FULL received email from Resend's Received Emails API.

    The `email.received` webhook is metadata-only (no body/headers), so to get the
    text + RFC822 Message-ID + References — needed for real content AND correct
    Gmail threading — we GET /emails/inbound/{id} after the webhook fires.

    Reads on the acting agency's own Resend account. It used to use the global
    key unconditionally, and a previous commit claimed to have fixed that by
    moving the call after the org was bound — which changed the ordering and
    nothing else, because this function never consulted the identity. Two ways
    that bites: an agency on its own Resend account gets a 401 that the caller
    swallows, so the agent answers an email whose body it never read; and an
    agency that knows its own webhook secret could name any message id and have
    the server fetch it from the *operator's* account.
    """
    identity = await resolve_outbound_identity(CHANNEL_EMAIL)
    if not identity.credential:
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"https://api.resend.com/emails/inbound/{email_id}",
            headers={"Authorization": f"Bearer {identity.credential}"},
        )
        resp.raise_for_status()
        detail = resp.json()

    # The id came from the request body, and on the shared Resend account the
    # key can read every agency's mail. So an agency that legitimately knows the
    # shared webhook secret could sign a message naming its own mailbox — which
    # resolves the org to itself — while pointing `data.id` at another agency's
    # message, and the body would be fetched and stored inside theirs. Confirm
    # what came back was actually addressed to this organization.
    if not await _addressed_to_acting_org(detail):
        log.error(
            "refusing inbound email %s: the fetched message is not addressed to "
            "the organization the webhook resolved to",
            email_id,
        )
        return None
    return detail


async def _addressed_to_acting_org(detail: dict[str, Any] | None) -> bool:
    """Whether a fetched message names a destination the acting org owns.

    Only meaningful when the org has its own routes; an agency on the shared
    account and the shared mailbox has nothing to distinguish it, and for a
    single-customer install every message is theirs by definition.
    """
    if not isinstance(detail, dict):
        return False

    from app.api.v1.webhooks.email import _mailboxes
    from app.services.tenant_context import get_org_id
    from app.services.tenant_resolver import resolve_org_by_destination

    org_id = get_org_id()
    if org_id is None:
        return True

    # Only meaningful when some *other* agency has an email route: they are the
    # only party who could be impersonated through a borrowed message id. On a
    # single-customer install, or before a second agency is onboarded, every
    # message is theirs by definition and this must not start refusing mail.
    if not await _another_org_owns_email_routes(org_id):
        return True

    addresses = _mailboxes({"data": detail})
    if not addresses:
        # Refuse. This used to answer True, and it is reachable: the header of
        # a BCC-only delivery is the literal `undisclosed-recipients:;`, which
        # parses to nothing — so naming another agency's message id and letting
        # the recipient list come back empty walked straight past the check.
        return False
    try:
        owner = await resolve_org_by_destination(CHANNEL_EMAIL, addresses)
    except Exception:  # noqa: BLE001 — ambiguity here is a refusal, not a crash
        return False
    if owner is None:
        # No route claims any of these addresses. Safe only if this agency has
        # no route of its own either — otherwise it is asking for a message
        # addressed somewhere it does not own.
        return not await _org_owns_any_email_route(org_id)
    return owner == org_id


async def _another_org_owns_email_routes(org_id: int) -> bool:
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute

    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                select(ChannelRoute.id)
                .where(
                    ChannelRoute.channel == CHANNEL_EMAIL,
                    ChannelRoute.org_id != org_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None


async def _org_owns_any_email_route(org_id: int) -> bool:
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute

    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                select(ChannelRoute.id)
                .where(
                    ChannelRoute.channel == CHANNEL_EMAIL,
                    ChannelRoute.org_id == org_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None


def _strip_quoted_reply(text: str) -> str:
    """Drop the quoted history mail clients append below a reply, so the agent
    sees only the new message. Cuts at the Gmail-style attribution ('On <date>
    … wrote:') or the first quoted '>' block. Conservative — returns the original
    if nothing matches."""
    import re

    if not text:
        return text
    m = re.search(r"\n\s*On .{0,300}?wrote:", text, flags=re.DOTALL)
    if m:
        text = text[: m.start()]
    else:
        m2 = re.search(r"\n\s*>", text)
        if m2:
            text = text[: m2.start()]
    return text.strip()


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
    body = _strip_quoted_reply(body)

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
    references: str | None = None,
) -> dict[str, Any]:
    """Send via Resend, or LOG when EMAIL_SIMULATED=true.

    Returns Resend's response dict (or a synthetic equivalent in simulated mode):
      {"id": "<resend message id>", "simulated": true | false}
    """
    s = get_settings()

    if s.EMAIL_SIMULATED:
        fake_id = f"resend.SIMULATED_{uuid4().hex}"
        log.info(
            "Email SIMULATED outbound to=%s subject=%r body_len=%d in_reply_to=%s (would-be id=%s)",
            to, subject, len(body_text), in_reply_to, fake_id,
        )
        return {"id": fake_id, "simulated": True}

    # The acting agency's own mailbox and Resend account, falling back to the
    # global one. Without this, agency B's lead received a reply from agency A's
    # address and their answer arrived in A's inbox.
    identity = await resolve_outbound_identity(CHANNEL_EMAIL)
    if not identity.credential:
        raise RuntimeError(
            "Email not configured for this organization: an API key must be "
            "set, either globally in .env or on the agency's channel route. "
            "Set EMAIL_SIMULATED=true for dev."
        )

    headers: dict[str, str] = {}
    if in_reply_to:
        # Strip surrounding <> if present, add them back per RFC.
        clean = in_reply_to.strip().lstrip("<").rstrip(">")
        headers["In-Reply-To"] = f"<{clean}>"
        # References should be the FULL chain (thread root … parent) for reliable
        # threading in Gmail/Outlook; fall back to just the parent when we only
        # have the one id.
        if references:
            ids = [t.strip().lstrip("<").rstrip(">") for t in references.replace(",", " ").split() if t.strip()]
            headers["References"] = " ".join(f"<{i}>" for i in ids) or f"<{clean}>"
        else:
            headers["References"] = f"<{clean}>"

    body: dict[str, Any] = {
        "from": identity.sender_override or identity.destination,
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
                "Authorization": f"Bearer {identity.credential}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code >= 400:
            log.error("Resend send failed: status=%d body=%s", resp.status_code, resp.text[:400])
        resp.raise_for_status()
        return resp.json()

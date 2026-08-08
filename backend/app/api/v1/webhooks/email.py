"""Email inbound webhook (Resend)."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models.channel_route import CHANNEL_EMAIL
from app.services.conversation import handle_inbound_message
from app.services.email import fetch_inbound_email, parse_inbound_email, verify_resend_signature
from app.services.tenant_context import set_org_id
from app.services.tenant_resolver import WebhookOrgUnresolved, webhook_org_or_refuse

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/email")
async def email_inbound(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Resend POSTs here when an inbound email arrives at our domain.

    Headers we care about:
      svix-id        — unique event id
      svix-timestamp — unix seconds
      svix-signature — `v1,<base64>` (possibly multiple, space-separated)

    Returns 200 unless body is malformed JSON — same idempotency contract as
    the WhatsApp webhook (UNIQUE on messages.external_id catches retries).
    """
    s = get_settings()
    raw = await request.body()
    svix_id = request.headers.get("svix-id")
    svix_timestamp = request.headers.get("svix-timestamp")
    svix_signature = request.headers.get("svix-signature")

    if not s.EMAIL_SIMULATED:
        ok = verify_resend_signature(
            raw,
            svix_id=svix_id,
            svix_timestamp=svix_timestamp,
            svix_signature=svix_signature,
            secret=s.RESEND_WEBHOOK_SECRET,
        )
        if not ok:
            log.warning("Resend webhook signature verification failed")
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Email webhook: invalid JSON: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    # Real Resend `email.received` webhooks are METADATA-ONLY (no body/headers).
    # Fetch the full email (text + Message-ID + References) from the Received
    # Emails API so the agent sees real content AND replies thread correctly.
    # SIMULATED test payloads already carry the body, so they skip the fetch.
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        not s.EMAIL_SIMULATED
        and isinstance(data, dict)
        and payload.get("type") == "email.received"
        and not data.get("text")
    ):
        email_id = data.get("id") or data.get("email_id")
        if email_id:
            try:
                detail = await fetch_inbound_email(email_id)
                if detail:
                    payload = {"type": "email.received", "data": detail}
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not fetch full inbound email %s: %s", email_id, exc)

    parsed_messages = parse_inbound_email(payload)
    if not parsed_messages:
        return {"status": "ok", "processed": 0}

    # Which agency's mailbox was written to. Resolved before any write; the
    # middleware cannot read the body.
    try:
        set_org_id(await webhook_org_or_refuse(CHANNEL_EMAIL, _mailboxes(payload)))
    except WebhookOrgUnresolved as exc:
        log.error("refusing inbound email — %s", exc)
        return JSONResponse({"status": "unrouted"}, status_code=503)

    results = []
    failed = False
    for parsed in parsed_messages:
        try:
            result = await handle_inbound_message(parsed, db)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            failed = True
            log.exception("Error processing email %s: %s", parsed.external_id, exc)
            results.append({"status": "error", "external_id": parsed.external_id, "error": str(exc)})

    if failed:
        # 500 so Resend redelivers. Duplicates return normally from
        # handle_inbound_message, so reaching here means nothing was stored.
        return JSONResponse(
            {"status": "error", "processed": len(parsed_messages), "results": results},
            status_code=500,
        )
    return {"status": "ok", "processed": len(parsed_messages), "results": results}


def _mailboxes(payload: dict) -> list[str]:
    """Every address this message was addressed to, in no meaningful order.

    All of them, deliberately. This used to return the *first* entry of `to`,
    with a comment right above it admitting the agency's own address is not
    always first — so a lead writing to agency B while CC'ing agency A had their
    whole thread, lead row and transcript filed under A. Handing the full set to
    the resolver lets it match exactly one route and refuse when two agencies
    are both addressed, which is the same rule WhatsApp already follows.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    found: list[str] = []
    for candidate in (data.get("to"), data.get("cc"), data.get("recipient")):
        if isinstance(candidate, str) and candidate.strip():
            found.append(_address_only(candidate))
        elif isinstance(candidate, list):
            for item in candidate:
                addr = item.get("email") if isinstance(item, dict) else item
                if isinstance(addr, str) and addr.strip():
                    found.append(_address_only(addr))
    return found


def _address_only(value: str) -> str:
    """Strip a display name: `Agency A <a@x.com>` -> `a@x.com`.

    Senders and providers both add these, and a lookup that kept the name never
    matched a stored route — turning a routable message into a refusal.
    """
    if "<" in value and ">" in value:
        return value[value.rindex("<") + 1 : value.rindex(">")].strip()
    return value.strip()

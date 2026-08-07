"""WhatsApp Cloud API webhook receiver.

GET  /api/v1/webhooks/whatsapp — Meta verification handshake (`hub.challenge`).
POST /api/v1/webhooks/whatsapp — inbound message envelope (signed with HMAC-SHA256).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models.channel_route import CHANNEL_WHATSAPP
from app.services.conversation import handle_inbound_message
from app.services.tenant_context import set_org_id
from app.services.tenant_resolver import WebhookOrgUnresolved, webhook_org_or_refuse
from app.services.whatsapp import parse_inbound_message, verify_signature

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
) -> str:
    """Meta calls this once when you set up the webhook subscription.

    The receiver must echo back `hub.challenge` if `hub.verify_token` matches
    what Meta has on file (which we store as WHATSAPP_VERIFY_TOKEN).
    """
    s = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == s.WHATSAPP_VERIFY_TOKEN:
        log.info("WhatsApp webhook verified")
        return hub_challenge
    log.warning("WhatsApp webhook verify rejected: mode=%s", hub_mode)
    raise HTTPException(status_code=403, detail="Invalid verify token")


@router.post("/whatsapp")
async def whatsapp_inbound(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Receive an inbound message envelope from Meta.

    Returns 200 OK + a small status payload. ALWAYS return 200 unless the
    request is structurally invalid — Meta retries non-200 responses, and the
    orchestrator's idempotency check (`wa_message_id` UNIQUE) handles retries
    gracefully.
    """
    s = get_settings()
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256") or request.headers.get("x-hub-signature-256")

    # Production: HMAC required. Simulated mode: signature is optional so
    # curl / scripts work without computing it.
    if not s.WHATSAPP_SIMULATED:
        if not verify_signature(raw, sig, s.WHATSAPP_APP_SECRET):
            log.warning("WhatsApp webhook signature verification failed")
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("WhatsApp webhook: invalid JSON: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    parsed_messages = parse_inbound_message(payload)
    if not parsed_messages:
        # Meta also sends "statuses" updates (delivered/read receipts) under
        # changes[].value.statuses[]. Phase 1 ignores those — return 200 so
        # Meta doesn't keep retrying.
        return {"status": "ok", "processed": 0}

    # Which agency's WhatsApp number was messaged. Resolved once from the
    # payload metadata, before any write, because the middleware cannot read
    # the body.
    try:
        set_org_id(
            await webhook_org_or_refuse(CHANNEL_WHATSAPP, _business_number(payload))
        )
    except WebhookOrgUnresolved as exc:
        log.error("refusing inbound WhatsApp — %s", exc)
        return JSONResponse({"status": "unrouted"}, status_code=503)

    results = []
    for parsed in parsed_messages:
        try:
            result = await handle_inbound_message(parsed, db)
            results.append(result)
        except IntegrityError:
            await db.rollback()
            log.info("Idempotent skip on wa_message_id=%s", parsed.external_id)
            results.append({"status": "duplicate", "wa_message_id": parsed.external_id})
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.exception("Error processing inbound %s: %s", parsed.external_id, exc)
            results.append({"status": "error", "wa_message_id": parsed.external_id, "error": str(exc)})

    return {"status": "ok", "processed": len(parsed_messages), "results": results}


def _business_number(payload: dict) -> str | None:
    """The agency's own WhatsApp number this message was sent TO.

    Meta nests it in changes[].value.metadata. `phone_number_id` is preferred
    over `display_phone_number` because it is stable across reformatting and
    number porting, which is exactly when a routing lookup must not start
    missing.
    """
    found: set[str] = set()
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            meta = (change.get("value") or {}).get("metadata") or {}
            value = meta.get("phone_number_id") or meta.get("display_phone_number")
            if value:
                found.add(str(value))
    if len(found) == 1:
        return found.pop()
    # Zero, or more than one. Meta batches entries per app delivery, and one app
    # serving two WhatsApp Business accounts is the documented multi-tenant
    # setup — so a single envelope really can carry two agencies. Returning the
    # first one filed BOTH under it. None makes the caller refuse instead.
    if found:
        log.error(
            "WhatsApp envelope carries %d business numbers (%s); refusing rather "
            "than filing them all under the first",
            len(found),
            sorted(found),
        )
    return None

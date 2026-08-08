"""SMS webhooks (Twilio): inbound messages + delivery status callbacks.

Inbound (`POST /sms`): Twilio POSTs a form when an SMS arrives at our number. We
validate `X-Twilio-Signature`, parse, hand off to the orchestrator, and return
empty TwiML (the reply is sent asynchronously via the REST API once the LLM
responds).

Status (`POST /sms/status`): when `TWILIO_STATUS_CALLBACK_URL` is configured,
Twilio POSTs delivery updates (sent → delivered / undelivered / failed + an
ErrorCode). We reflect the final state on the outbound Message so the dashboard
shows real delivery status (and we log carrier errors like 30034 = A2P 10DLC
unregistered).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models import Message, MessageStatus
from app.models.channel_route import CHANNEL_SMS
from app.services.conversation import handle_inbound_message
from app.services.sms import parse_inbound_sms, twilio_status_to_delivery, verify_twilio_signature
from app.services.tenant_context import set_org_id
from app.services.tenant_resolver import WebhookOrgUnresolved, webhook_org_or_refuse

log = logging.getLogger(__name__)
router = APIRouter()

_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _public_url(request: Request, configured: str) -> str:
    """The URL Twilio signed against. Prefer the configured public URL; otherwise
    rebuild from forwarded headers (proxy/tunnel), else the raw request URL."""
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if proto and host:
        return f"{proto}://{host}{request.url.path}"
    return str(request.url)


@router.post("/sms")
async def sms_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    s = get_settings()
    form = {k: str(v) for k, v in (await request.form()).items()}

    if not s.SMS_SIMULATED:
        url = _public_url(request, s.TWILIO_WEBHOOK_URL)
        ok = verify_twilio_signature(
            url, form, request.headers.get("X-Twilio-Signature"), auth_token=s.TWILIO_AUTH_TOKEN
        )
        if not ok:
            log.warning(
                "Twilio inbound signature failed (url=%s, params=%s) — check TWILIO_WEBHOOK_URL "
                "matches the console webhook exactly and the auth token is the account's primary.",
                url, sorted(form),
            )
            raise HTTPException(status_code=403, detail="Invalid signature")

    parsed = parse_inbound_sms(form)
    if parsed is None:
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    # Which agency was texted. The middleware cannot read the body, so the org
    # is decided here, before any write, from the number the message arrived at.
    try:
        set_org_id(await webhook_org_or_refuse(CHANNEL_SMS, form.get("To")))
    except WebhookOrgUnresolved as exc:
        log.error("refusing inbound SMS — %s", exc)
        return Response(
            status_code=503, content=_EMPTY_TWIML, media_type="application/xml"
        )

    try:
        await handle_inbound_message(parsed, db)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.exception("Error processing SMS %s: %s", parsed.external_id, exc)
        # 500, not 200. Duplicates are recognised inside handle_inbound_message
        # and return normally, so anything reaching here means the message was
        # NOT stored. Answering 200 hid that: the lead was gone, Twilio's console
        # showed success, and the only trace was a log line reading "idempotent
        # skip" — which is what made three lost leads look like normal operation.
        return Response(
            status_code=500, content=_EMPTY_TWIML, media_type="application/xml"
        )

    # 200 + empty TwiML on success; the reply goes out via REST, not TwiML.
    return Response(content=_EMPTY_TWIML, media_type="application/xml")


@router.post("/sms/status")
async def sms_status_callback(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Reflect Twilio's delivery status on the outbound Message (matched by SID)."""
    s = get_settings()
    form = {k: str(v) for k, v in (await request.form()).items()}

    if not s.SMS_SIMULATED:
        url = _public_url(request, s.TWILIO_STATUS_CALLBACK_URL)
        ok = verify_twilio_signature(
            url, form, request.headers.get("X-Twilio-Signature"), auth_token=s.TWILIO_AUTH_TOKEN
        )
        if not ok:
            log.warning("Twilio status callback signature failed (url=%s)", url)
            raise HTTPException(status_code=403, detail="Invalid signature")

    # Delivery callbacks carry no destination — the agency is the one that OWNS
    # the outbound message, which is what `From` is here. Without this the
    # handler ran org-less: the lookup found nothing under default-deny RLS,
    # logged "unknown sid" and returned 200, so carrier failures (A2P 30034 and
    # friends) never reached any tenant but the default one.
    try:
        set_org_id(await webhook_org_or_refuse(CHANNEL_SMS, form.get("From")))
    except WebhookOrgUnresolved as exc:
        log.error("refusing SMS status callback — %s", exc)
        return Response(
            status_code=503, content=_EMPTY_TWIML, media_type="application/xml"
        )

    sid = form.get("MessageSid") or form.get("SmsSid")
    twilio_status = form.get("MessageStatus") or form.get("SmsStatus") or ""
    error_code = form.get("ErrorCode")
    mapped = twilio_status_to_delivery(twilio_status)

    if sid and mapped:
        row = (await db.execute(select(Message).where(Message.external_id == sid))).scalar_one_or_none()
        if row is not None:
            row.delivery_status = MessageStatus(mapped)
            await db.commit()
            log.info(
                "SMS status: sid=%s twilio=%s → %s%s",
                sid, twilio_status, mapped,
                f" error={error_code}" if error_code and error_code != "0" else "",
            )
        else:
            log.info("SMS status callback for unknown sid=%s (status=%s)", sid, twilio_status)

    return Response(content=_EMPTY_TWIML, media_type="application/xml")

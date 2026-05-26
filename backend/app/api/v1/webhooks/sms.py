"""SMS inbound webhook (Twilio).

Twilio POSTs an `application/x-www-form-urlencoded` body when an SMS arrives at
our number. We validate the `X-Twilio-Signature`, parse, hand off to the
orchestrator, and return empty TwiML (the actual reply is sent asynchronously via
the Twilio REST API once the LLM responds).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.services.conversation import handle_inbound_message
from app.services.sms import parse_inbound_sms, verify_twilio_signature

log = logging.getLogger(__name__)
router = APIRouter()

_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _public_url(request: Request, configured: str) -> str:
    """The URL Twilio signed against. Prefer the configured public webhook URL;
    otherwise rebuild from forwarded headers (proxy/tunnel), else the raw URL."""
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
            log.warning("Twilio signature verification failed (url=%s)", url)
            raise HTTPException(status_code=403, detail="Invalid signature")

    parsed = parse_inbound_sms(form)
    if parsed is None:
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    try:
        await handle_inbound_message(parsed, db)
    except IntegrityError:
        await db.rollback()
        log.info("Idempotent skip on SMS external_id=%s", parsed.external_id)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.exception("Error processing SMS %s: %s", parsed.external_id, exc)

    # Always 200 + empty TwiML so Twilio doesn't retry; reply goes out via REST.
    return Response(content=_EMPTY_TWIML, media_type="application/xml")

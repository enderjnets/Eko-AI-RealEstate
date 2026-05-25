"""Email inbound webhook (Resend)."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.services.conversation import handle_inbound_message
from app.services.email import parse_inbound_email, verify_resend_signature

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

    parsed_messages = parse_inbound_email(payload)
    if not parsed_messages:
        return {"status": "ok", "processed": 0}

    results = []
    for parsed in parsed_messages:
        try:
            result = await handle_inbound_message(parsed, db)
            results.append(result)
        except IntegrityError:
            await db.rollback()
            log.info("Idempotent skip on email external_id=%s", parsed.external_id)
            results.append({"status": "duplicate", "external_id": parsed.external_id})
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.exception("Error processing email %s: %s", parsed.external_id, exc)
            results.append({"status": "error", "external_id": parsed.external_id, "error": str(exc)})

    return {"status": "ok", "processed": len(parsed_messages), "results": results}

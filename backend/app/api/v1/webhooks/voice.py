"""Voice webhook (VAPI server messages): tool-calls + end-of-call report.

VAPI POSTs `{"message": {"type": ...}}` for every server event configured on the
assistant. We authenticate with the shared `x-vapi-secret` header (skipped when
VOICE_SIMULATED), then:

  - `tool-calls`         → run each tool and return `{results:[{toolCallId,result}]}`
                           SYNCHRONOUSLY so the assistant speaks the outcome.
  - `end-of-call-report` → ingest the finished call into the lead timeline.
  - anything else        → 200 OK (logged, ignored).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models.channel_route import CHANNEL_VOICE
from app.services.conversation import ingest_voice_call
from app.services.tenant_context import set_org_id
from app.services.tenant_resolver import WebhookOrgUnresolved, webhook_org_or_refuse
from app.services.voice import handle_tool_call, parse_end_of_call_report, verify_vapi_secret

log = logging.getLogger(__name__)
router = APIRouter()


# The only two VAPI message types that write anything. Everything else is
# narration and is acknowledged without touching the database.
_PERSISTING_MESSAGE_TYPES = frozenset({"tool-calls", "end-of-call-report"})


def _message(payload: Any) -> dict[str, Any]:
    """The inner `message` envelope, or the payload itself if it is flat.

    Guards the type: `json.loads` happily returns a list or a bare string for a
    malformed body, and `.get` on those raised AttributeError — an unhandled 500
    where a 400 was the honest answer.
    """
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("message")
    return inner if isinstance(inner, dict) else payload


def _dialled_numbers(msg: dict[str, Any]) -> list[str]:
    """Every key identifying the agency VAPI line that was called.

    All of them, because VAPI does not send the same one every time: the
    end-of-call report inlines `call.phoneNumber.number` while a `tool-calls`
    message for that same live call may carry only `call.phoneNumberId`. A route
    mapped by E.164 therefore matched the report and missed the tool call, so
    the assistant 503'd mid-conversation and could not book a visit — while the
    transcript still filed correctly afterwards. An operator would be hunting
    that for days.

    Returning the set lets one `channel_routes` row be found by whichever key
    the payload happens to carry. Still NOT verified against a live VAPI
    account — there is none yet — so anything unrecognised yields nothing and
    the caller falls back or refuses rather than guessing an organization.
    """
    call = msg.get("call") if isinstance(msg.get("call"), dict) else {}
    found: list[str] = []

    def _add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
        elif isinstance(value, (int, float)):
            found.append(str(value))

    for number in (call.get("phoneNumber"), msg.get("phoneNumber")):
        if isinstance(number, dict):
            _add(number.get("number"))
            _add(number.get("id"))
        else:
            _add(number)
    _add(call.get("phoneNumberId"))
    _add(msg.get("phoneNumberId"))
    return found


def _customer_number(msg: dict[str, Any]) -> str | None:
    call = msg.get("call") if isinstance(msg.get("call"), dict) else {}
    cust = call.get("customer") or msg.get("customer") or {}
    if isinstance(cust, dict):
        return (cust.get("number") or "").strip() or None
    return None


def _tool_calls(msg: dict[str, Any]) -> list[dict[str, Any]]:
    raw = msg.get("toolCalls") or msg.get("toolCallList") or []
    return [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []


def _tool_name_args(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract (name, arguments) from a VAPI tool-call, tolerating both the
    nested `function: {name, arguments}` shape and the flat one. Arguments may
    arrive as a dict or a JSON string."""
    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = fn.get("name") or call.get("name") or ""
    args = fn.get("arguments")
    if args is None:
        args = call.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name, args


@router.post("/voice")
async def voice_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    s = get_settings()
    raw = await request.body()

    if not s.VOICE_SIMULATED:
        if not verify_vapi_secret(request.headers.get("x-vapi-secret"), s.VAPI_WEBHOOK_SECRET):
            log.warning("VAPI webhook secret verification failed")
            raise HTTPException(status_code=403, detail="Invalid secret")

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        log.error("Voice webhook: invalid JSON: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    msg = _message(payload)
    mtype = msg.get("type")

    # VAPI narrates a call with several informational messages — status changes,
    # speech updates, the hangup. They are dropped at the end of this function
    # without touching the database, so putting the routing gate in front of
    # them only produced a stream of 503s and provider retries for events that
    # were never going to be stored. Resolve for the two types that write.
    if mtype not in _PERSISTING_MESSAGE_TYPES:
        log.info("Voice webhook: ignoring server message type=%s", mtype)
        return {"status": "ignored", "type": mtype}

    # Which agency's VAPI number was called. Same defensive shape as
    # _customer_number: if the fields are absent this yields nothing and the
    # caller falls back to the single-tenant path or refuses, so voice is never
    # the one channel that silently misfiles.
    try:
        set_org_id(await webhook_org_or_refuse(CHANNEL_VOICE, _dialled_numbers(msg)))
    except WebhookOrgUnresolved as exc:
        log.error("refusing inbound call — %s", exc)
        return JSONResponse({"status": "unrouted"}, status_code=503)

    # ── Tool calls — answer synchronously so the assistant can speak the result ──
    if mtype == "tool-calls":
        number = _customer_number(msg)
        results = []
        for call in _tool_calls(msg):
            name, args = _tool_name_args(call)
            tool_call_id = call.get("id") or (call.get("function") or {}).get("id")
            try:
                result = await handle_tool_call(name, args, customer_number=number, db=db)
            except Exception as exc:  # noqa: BLE001 — never stall the live call
                # No rollback here. `handle_tool_call` owns its own transaction:
                # it commits each successful tool and rolls back its own
                # failures. Rolling back again from out here reached across to
                # whatever an *earlier* tool call in this same batch had left
                # uncommitted, while that call's success string stayed in
                # `results` — so the assistant would tell the caller their visit
                # was booked after the row had been discarded.
                log.exception("Voice tool dispatch failed (%s): %s", name, exc)
                result = "Something went wrong on my side. A team member will follow up."
            results.append({"toolCallId": tool_call_id, "result": result})
        return {"results": results}

    # ── End-of-call report — ingest the finished transcript into the lead ──
    if mtype == "end-of-call-report":
        report = parse_end_of_call_report(payload)
        if report is None:
            return {"status": "ignored", "reason": "no_call_id"}
        try:
            result = await ingest_voice_call(report, db)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.exception("Error ingesting voice call %s: %s", report.call_id, exc)
            # 500, not a 200 carrying the error in its body. The whole call —
            # caller, transcript, summary — is lost otherwise, and the provider
            # is told it succeeded.
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)
        return {"status": "ok", "result": result}

    log.info("Voice webhook: ignoring server message type=%s", mtype)
    return {"status": "ignored", "type": mtype}

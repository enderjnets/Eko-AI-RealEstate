"""Voice channel — VAPI assistant (inbound calls) + server-message webhook.

VAPI runs the live call (Deepgram STT + 11labs TTS + a realtime LLM) and POSTs
"server messages" to our webhook:

  - `tool-calls`         → we answer SYNCHRONOUSLY so the assistant can act + speak
                           the result mid-call (e.g. book a visit). Handled here by
                           `handle_tool_call`.
  - `end-of-call-report` → the full call is over; `parse_end_of_call_report` turns
                           the transcript into a list of turns + extracted fields,
                           which the orchestrator ingests into the lead timeline
                           (channel="voice").

Unlike SMS/email there is no outbound "send" on this channel — the conversation
already happened live in the call. So voice stays OUT of the orchestrator's
SENDABLE_CHANNELS; we only INGEST the finished call.

When VOICE_SIMULATED=true (dev default), the webhook accepts unsigned requests so
tests + the public demo work without a VAPI account.
"""
from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

__all__ = [
    "verify_vapi_secret",
    "VoiceCallReport",
    "parse_end_of_call_report",
    "handle_tool_call",
]


# ── Signature / secret verification ─────────────────────────────────────────


def verify_vapi_secret(header_secret: str | None, configured: str) -> bool:
    """Validate the `x-vapi-secret` header against our configured secret.

    VAPI sends the assistant's `server.secret` verbatim in this header on every
    server message. A constant-time compare avoids timing leaks. Empty configured
    secret → False (the route only allows unsigned when VOICE_SIMULATED)."""
    if not (header_secret and configured):
        return False
    return hmac.compare_digest(header_secret, configured)


# ── Inbound: end-of-call report parsing ─────────────────────────────────────


@dataclass(frozen=True)
class VoiceCallReport:
    """Normalized end-of-call data, channel-agnostic for the orchestrator."""

    call_id: str
    from_identifier: str  # caller phone (E.164) or `voice:<call_id>` for web calls
    from_name: str | None
    summary: str | None
    turns: list[tuple[str, str]]  # (role, text); role ∈ {"user","agent"}
    structured: dict[str, Any] = field(default_factory=dict)


# VAPI transcript roles → our turn roles. "bot" is the assistant; "user" the caller.
# system / tool_calls / tool_call_result turns are not part of the human transcript.
_ROLE_MAP = {"bot": "agent", "assistant": "agent", "user": "user"}


def _message(payload: dict[str, Any]) -> dict[str, Any]:
    """VAPI nests everything under `message`; tolerate either shape."""
    inner = payload.get("message")
    return inner if isinstance(inner, dict) else payload


def _customer_number(msg: dict[str, Any]) -> str | None:
    call = msg.get("call") if isinstance(msg.get("call"), dict) else {}
    cust = call.get("customer") or msg.get("customer") or {}
    if isinstance(cust, dict):
        num = (cust.get("number") or "").strip()
        return num or None
    return None


def parse_end_of_call_report(payload: dict[str, Any]) -> VoiceCallReport | None:
    """Build a VoiceCallReport from a VAPI `end-of-call-report` server message.

    Pulls the transcript turns from `artifact.messages` (falls back to `messages`),
    the caller number from `call.customer.number`, and the LLM analysis
    (`analysis.summary` + `analysis.structuredData`). Returns None if there's no
    usable call id."""
    msg = _message(payload)

    call = msg.get("call") if isinstance(msg.get("call"), dict) else {}
    call_id = str(call.get("id") or msg.get("callId") or msg.get("id") or "").strip()
    if not call_id:
        log.warning("Voice end-of-call-report without a call id — skipping")
        return None

    number = _customer_number(msg)
    from_identifier = number or f"voice:{call_id}"

    artifact = msg.get("artifact") if isinstance(msg.get("artifact"), dict) else {}
    raw_turns = artifact.get("messages")
    if not isinstance(raw_turns, list):
        raw_turns = msg.get("messages") if isinstance(msg.get("messages"), list) else []

    turns: list[tuple[str, str]] = []
    for t in raw_turns:
        if not isinstance(t, dict):
            continue
        role = _ROLE_MAP.get((t.get("role") or "").lower())
        if role is None:
            continue
        text = (t.get("message") or t.get("content") or "").strip()
        if text:
            turns.append((role, text))

    analysis = msg.get("analysis") if isinstance(msg.get("analysis"), dict) else {}
    summary = (analysis.get("summary") or msg.get("summary") or "").strip() or None
    structured = analysis.get("structuredData")
    if not isinstance(structured, dict):
        structured = {}

    from_name = None
    name = structured.get("name")
    if not (isinstance(name, str) and name.strip()):
        ci = structured.get("customer_info")
        name = ci.get("name") if isinstance(ci, dict) else None
    if isinstance(name, str) and name.strip():
        from_name = name.strip()

    return VoiceCallReport(
        call_id=call_id,
        from_identifier=from_identifier,
        from_name=from_name,
        summary=summary,
        turns=turns,
        structured=structured,
    )


# ── Tool calls (answered live during the call) ───────────────────────────────


def _office_zone(tz_name: str) -> ZoneInfo:
    """ZoneInfo for the office tz, falling back to UTC on a bad/unknown name."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Unknown office timezone %r — falling back to UTC", tz_name)
        return ZoneInfo("UTC")


def _parse_dt(value: Any, tz: ZoneInfo) -> datetime | None:
    """Parse the datetime the assistant passes for booking, returning an aware UTC
    datetime — or None if unparseable.

    A caller on the phone always speaks a LOCAL wall-clock time ("2 PM"), so we
    interpret the parsed hour/minute in the OFFICE timezone regardless of any
    tz suffix the LLM may have added, then convert to UTC for storage. (2 PM in
    America/Denver → 20:00 UTC, not 14:00 UTC.)"""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # Drop any tz the LLM attached and treat the wall-clock as office-local.
    dt = dt.replace(tzinfo=tz)
    return dt.astimezone(UTC)


async def _office_tz_name(db: AsyncSession) -> str:
    """The office IANA timezone from AgentSettings (singleton), default UTC."""
    from app.models import AgentSettings

    row = await db.execute(select(AgentSettings))
    cfg = row.scalar_one_or_none()
    return (cfg.timezone if cfg and cfg.timezone else "UTC")


async def _resolve_or_create_lead(identifier: str, name: str | None, db: AsyncSession):
    """Mirror of the orchestrator's lead upsert (by identifier == Lead.phone)."""
    from app.models import Lead

    row = await db.execute(select(Lead).where(Lead.phone == identifier))
    lead = row.scalar_one_or_none()
    if lead is None:
        lead = Lead(phone=identifier, name=name)
        db.add(lead)
        await db.flush()
        log.info("Created lead id=%d channel=voice identifier=%s", lead.id, identifier)
    elif name and not lead.name:
        lead.name = name
    return lead


async def handle_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    customer_number: str | None,
    db: AsyncSession,
) -> str:
    """Execute a tool the assistant invoked mid-call; return a short text result
    that VAPI feeds back to the LLM (so it can confirm verbally).

    Supported tools:
      - check_availability(days?) → human-readable next free slots.
      - book_visit(datetime, property_address?, name?) → books a Visit for the
        caller (resolved/created by their phone number) and confirms.
    Any failure returns a spoken-friendly message, never raises (a thrown tool
    handler would make the assistant stall mid-call)."""
    from app.services.calendar_cal import CalComError, create_booking, list_available_slots

    tz_name = await _office_tz_name(db)
    zone = _office_zone(tz_name)

    try:
        if name == "check_availability":
            days = int(arguments.get("days") or 7)
            days = max(1, min(days, 30))
            now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            slots = await list_available_slots(
                start=now, end=now + timedelta(days=days), timezone_name=tz_name
            )
            if not slots:
                return "I don't see any open visit times in that window right now."
            top = slots[:5]
            pretty = "; ".join(
                s.start.astimezone(zone).strftime("%A %b %d at %I:%M %p") for s in top
            )
            return f"Here are the next available visit times: {pretty}."

        if name == "book_visit":
            from app.models import Visit, VisitStatus

            when = _parse_dt(arguments.get("datetime") or arguments.get("start_time"), zone)
            if when is None:
                return "I couldn't read that date and time. Could you give me a specific day and time?"

            # Key the lead on the CALLER ID (always present on a phone call and
            # identical in the end-of-call report), so the visit lands on the SAME
            # lead as the transcript. The number the caller dictates is kept as a
            # callback note. Web calls (no caller id) fall back to the dictated one.
            phone = (customer_number or arguments.get("phone") or "").strip()
            if not phone:
                return "I need a phone number to confirm the visit. What's the best number to reach you?"

            caller_name = arguments.get("name") or None
            lead = await _resolve_or_create_lead(phone, caller_name, db)
            property_address = (arguments.get("property_address") or arguments.get("property") or None)

            provided = (arguments.get("phone") or "").strip()
            note = "Booked during a voice call"
            if provided and provided != phone:
                note += f" · callback: {provided}"

            attendee_email = lead.phone if "@" in lead.phone else None
            attendee_phone = lead.phone if "@" not in lead.phone else None
            booking = await create_booking(
                start_time=when,
                attendee_name=lead.name or "Caller",
                attendee_email=attendee_email,
                attendee_phone=attendee_phone,
                notes=note,
                timezone_name=tz_name,
            )
            visit = Visit(
                lead_id=lead.id,
                calendar_provider="calcom",
                external_booking_id=booking.external_booking_id,
                status=VisitStatus.SCHEDULED,
                scheduled_at=booking.scheduled_at,
                duration_minutes=booking.duration_minutes,
                timezone=tz_name,
                property_address=property_address,
                meeting_url=booking.meeting_url,
                notes=note,
            )
            db.add(visit)
            await db.commit()
            await db.refresh(visit)

            try:
                from app.services.followups import enqueue_for_visit
                await enqueue_for_visit(visit, db)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not enqueue follow-ups for voice visit %d: %s", visit.id, exc)

            when_str = booking.scheduled_at.astimezone(zone).strftime("%A %b %d at %I:%M %p")
            return f"Your visit is booked for {when_str}. You'll get a reminder beforehand."

        log.warning("Voice tool-call for unknown tool: %s", name)
        return f"I'm not able to do '{name}' right now."
    except CalComError as exc:
        log.error("Voice tool %s calendar error: %s", name, exc)
        return "I'm having trouble with the calendar at the moment. A team member will follow up."
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.exception("Voice tool %s failed: %s", name, exc)
        return "Something went wrong on my side. A team member will follow up with you."

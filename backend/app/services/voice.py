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
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services._common import clip_identifier
from app.services.lead_fields import storable_text
from app.services.timezones import resolve_zone

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
    # Same treatment as the chat path, and for the same two reasons: written
    # whole it can exceed `leads.phone` (254, UNIQUE) and take the transcript
    # down with it; truncated, two callers sharing a prefix become one lead.
    from_identifier = clip_identifier(number or f"voice:{call_id}")

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


def _office_zone(tz_name: str) -> ZoneInfo | None:
    """ZoneInfo for the office tz, or None when the configured name is unusable.

    It used to fall back to UTC, which is the same defect `visits.py` carried:
    every hour this call quotes and every appointment it books lands in the
    wrong zone. In Denver that is six hours — a caller told "Tuesday at 2 PM"
    who finds the door locked at 8 AM. A warning in a log nobody is reading
    during a phone call is not a control.

    None rather than an exception, because this module's tool handler promises
    never to raise: a thrown handler stalls the assistant mid-call. The callers
    below turn None into a spoken apology, which is the honest answer — we
    cannot tell this person a time we cannot compute.

    That promise was false when first written: this caught two of `ZoneInfo`'s
    three exception types, so an office timezone of `"America"` (a tzdata
    DIRECTORY) raised `IsADirectoryError` from a call sited outside the handler's
    own `try`, straight past a docstring that says it never raises. `resolve_zone`
    is now the single place that knows the surface — see
    `app/services/timezones.py`.
    """
    zone = resolve_zone(tz_name or "UTC")
    if zone is None:
        log.error(
            "Office timezone %r is not a known IANA zone; refusing to quote or "
            "book times rather than answering in the wrong one. Fix it in Settings.",
            tz_name,
        )
    return zone


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
    resolved = dt.astimezone(UTC)
    # And refuse the hour that does not exist, the same way the HTTP routes do.
    # `replace(tzinfo=...)` never raises for a spring-forward gap, so a caller
    # naming 02:30 on that morning was silently given a 03:30 appointment — and
    # 02:30 and 03:30 became the same instant, which the double-booking guard
    # then reads as a clash between two different people. Returning None makes
    # the agent offer another time instead of inventing one, which is what it
    # already does for anything it cannot parse. Guarding the HTTP routes and
    # leaving this one is the defect this codebase produces more than any other,
    # and I had just done it again.
    if resolved.astimezone(tz).replace(tzinfo=None) != dt.replace(tzinfo=None):
        log.info("Refusing a local time that does not exist on that date: %r", str(value)[:32])
        return None
    return resolved


async def _office_tz_name(db: AsyncSession) -> str:
    from app.models import AgentSettings

    row = await db.execute(select(AgentSettings).where(AgentSettings.org_id == _acting_org()))
    cfg = row.scalar_one_or_none()
    return (cfg.timezone if cfg and cfg.timezone else "UTC")


async def _resolve_or_create_lead(identifier: str, name: str | None, db: AsyncSession):
    """Mirror of the orchestrator's lead upsert (by identifier == Lead.phone)."""
    from app.models import Lead

    # Normalised before the lookup, because the write below normalises too and
    # the two have to agree: above 254 characters the search could never match
    # the row it had just created, so the insert hit the unique index — and
    # this helper has no savepoint, so that took the call's transaction with it.
    identifier = clip_identifier(identifier)
    row = await db.execute(select(Lead).where(Lead.phone == identifier))
    lead = row.scalar_one_or_none()
    if lead is None:
        lead = Lead(
            phone=identifier,
            name=name,
            email=identifier if "@" in (identifier or "") else None,
        )
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
    from app.services.calendar_cal import (
        CalComError,
        create_booking,
        ensure_recordable,
        list_available_slots,
    )

    tz_name = await _office_tz_name(db)
    zone = _office_zone(tz_name)
    if zone is None:
        # Every branch below either quotes a time or books one, and both are
        # wrong by the office's UTC offset without a usable zone. Say so
        # instead — a caller who is asked to hold is better served than one
        # given an appointment six hours from the one they agreed to.
        return (
            "I'm sorry — I can't check the calendar right now. "
            "Someone from the team will call you back shortly to arrange a time."
        )

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

            # The lead's own address when we have one; `phone` holds it for
            # email-channel leads. Neither, and `create_booking` uses the
            # agency's booking contact rather than failing.
            attendee_email = lead.email or (lead.phone if "@" in (lead.phone or "") else None)
            attendee_phone = lead.phone if "@" not in lead.phone else None

            # Check before booking. Going straight to Cal.com meant a taken slot
            # came back as a 4xx, which the outer handler turns into "I'm having
            # trouble with the calendar" — so a caller who asked for a time
            # somebody else had hung up unbooked, told the system was broken
            # rather than offered another time.
            from app.api.v1.visits import _busy_starts

            free = await list_available_slots(
                start=when - timedelta(minutes=1),
                end=when + timedelta(days=1),
                timezone_name=tz_name,
                busy_starts=await _busy_starts(
                    db, since=when - timedelta(days=1), until=when + timedelta(days=2)
                ),
            )
            if not any(slot.start == when for slot in free):
                alternatives = ", ".join(
                    slot.start.astimezone(zone).strftime("%A at %-I:%M %p")
                    for slot in free[:3]
                )
                if not alternatives:
                    return (
                        "That time isn't available, and I don't have anything "
                        "else open that day. What other day works for you?"
                    )
                return f"That time is taken. I do have {alternatives}. Any of those?"

            # Idempotency. A replayed tool-call webhook — VAPI retries, and the
            # model can call the same tool twice in one turn — otherwise made a
            # second Cal.com booking, a second visit and a second set of
            # reminders for the same caller and the same hour.
            existing = (
                await db.execute(
                    select(Visit).where(
                        Visit.lead_id == lead.id,
                        Visit.scheduled_at == when,
                        Visit.status.in_(
                            [VisitStatus.SCHEDULED, VisitStatus.CONFIRMED]
                        ),
                    )
                )
            ).scalars().first()
            if existing is not None:
                return (
                    f"You're already booked for {when.astimezone(zone).strftime('%A at %-I:%M %p')}. "
                    "See you then."
                )

            if lead.opted_out_at is not None:
                # Cal.com emails a confirmation and then reminders. Booking
                # somebody who told us to stop is contacting them again through
                # a third party, which is no less a contact for having left
                # from someone else's server. This path is autonomous — the
                # agent books on its own — so the guard has to live here.
                log.info(
                    "Refusing to book lead %d from the voice agent: opted out at %s",
                    lead.id,
                    lead.opted_out_at.isoformat(),
                )
                return (
                    "I'm not able to book that. Let me have someone from the "
                    "office reach out to you directly."
                )

            # The name the caller gave, computed BEFORE the booking because the
            # calendar needs it too: fixing only `visit.title` left our Calendar
            # tab right and Cal.com's own confirmation and reminders — the ones
            # the CALLER receives — still going out under the stale name.
            stated_name = storable_text(caller_name, "name")

            booking = await create_booking(
                start_time=when,
                attendee_name=stated_name or lead.name or "Caller",
                attendee_email=attendee_email,
                attendee_phone=attendee_phone,
                notes=note,
                timezone_name=tz_name,
            )
            # Same rule as the HTTP route, from the same place. The reference
            # the calendar returns is the only handle that can cancel this
            # appointment later, so if it will not fit the column, the booking
            # is undone rather than left real and unrecorded — the caller is on
            # the phone and would otherwise be told about an appointment that
            # nothing here can see.
            booking = await ensure_recordable(booking)

            # Kept on the appointment, never on the lead.
            #
            # A lead is keyed by phone number and keeps the first name anyone
            # ever gave for it (`_resolve_or_create_lead`, and the same rule in
            # every other channel). That is right: a realtor can correct a name
            # by hand, and voice transcription is unreliable enough to undo it —
            # the call that exposed this heard "Enter Ocando" for "Ender
            # Ocando". But it left the owner looking at his own booking filed
            # under a stranger's name from a months-old test.
            #
            # So the STATED name lands on the visit, where a bad transcription
            # costs one appointment instead of corrupting an identity. The
            # calendar already prefers it: `_visit_item` renders
            # `v.title or lead_name or "Visit"`.
            visit = Visit(
                lead_id=lead.id,
                title=stated_name if stated_name and stated_name != lead.name else None,
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

            # The invitation matters MOST on this path. Here the assistant is
            # about to say out loud, to a person on the phone, that the visit is
            # booked — and until this line existed, that sentence was the only
            # trace of the appointment outside our own table. A caller who left
            # an email now gets something they can put in their calendar.
            from app.services.visit_invite import send_visit_invitation

            await send_visit_invitation(db, visit, lead)

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


def _acting_org() -> int:
    """The org whose settings row applies to this call.

    RLS already scopes the query in production; naming the org explicitly keeps
    it correct on a bypass or owner session too, where scalar_one_or_none()
    would otherwise see every tenant's row and raise.
    """
    from app.services.tenant_context import get_org_id

    org_id = get_org_id()
    if org_id is None:
        # Was `or DEFAULT_ORG_ID`. It fails closed today because these paths run
        # on the RLS session — an unset org reads nothing and cannot write — but
        # the fallback is one `get_bypass_db` away from silently reading and
        # overwriting client zero's row, and there are six of these. Say so
        # instead of guessing.
        raise RuntimeError(
            "no acting organization is bound; refusing to fall back to the "
            "default one"
        )
    return org_id

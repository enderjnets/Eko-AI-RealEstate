"""Orchestrator — converts a parsed inbound WhatsApp message into a full turn.

Order of operations (each step persists before the next so we never lose state
on partial failures):

  1. Upsert Lead by phone (carry forward the name if Meta gives us one).
  2. Find or create the active Conversation for the lead.
  3. Idempotency check: if wa_message_id already exists, skip silently (Meta
     retries dropped webhooks).
  4. Persist the inbound Message + bump Lead.last_message_at.
  5. If lead.human_takeover, stop here — human is driving this thread.
  6. Build message history (last N turns) for the LLM context.
  7. Run intent classifier → updates Lead.intent + Lead.zone/budget/etc. when
     confidence is high enough (does NOT overwrite values already on the lead).
  8. Generate AI reply via llm.generate_reply (Kimi primary, MiniMax fallback).
  9. Persist the outbound Message (status=PENDING).
 10. Send via WhatsApp Cloud API; update Message.wa_message_id + wa_status to
     SENT (or FAILED on exception — the reply text still lives in DB).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, time
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import first_or_create
from app.models import (
    AgentSettings,
    Conversation,
    ConversationStatus,
    Lead,
    LeadIntent,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.services._common import ParsedMessage
from app.services.classifier import classify_intent
from app.services.delivery import schedule_retry
from app.services.i18n import detect_language, language_instruction, pick_supported_language
from app.services.listings import listing_broker
from app.services.llm import LLMResult, LLMUnavailable, generate_reply
from app.services.scoring import rescore_lead
from app.services.tenant_context import get_org_id
from app.services.whatsapp import send_text_message as whatsapp_send

log = logging.getLogger(__name__)


async def _dispatch_send(
    channel: str,
    *,
    to: str,
    text: str,
    subject: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> tuple[str | None, str | None]:
    """Send the reply through the correct channel adapter.

    Returns `(external_id, optional_subject)` so the caller can persist the
    provider's id on the outbound Message and (for email) record the subject line.
    Email and SMS imports are LAZY to avoid pulling their deps when those channels
    aren't enabled in a given deploy.
    """
    if channel == "whatsapp":
        result = await whatsapp_send(to, text)
        return result.get("messages", [{}])[0].get("id"), None

    if channel == "email":
        from app.services.email import send_email as email_send  # lazy import
        result = await email_send(
            to=to,
            subject=subject or "Tu consulta",
            body_text=text,
            in_reply_to=in_reply_to,
            references=references,
        )
        return result.get("id"), subject

    if channel == "sms":
        from app.services.sms import send_sms  # lazy import
        result = await send_sms(to=to, body=text)
        return result.get("sid"), None

    raise ValueError(f"Unsupported channel for outbound send: {channel}")

# How many recent messages we feed back into the LLM as context. Plenty for
# WhatsApp where conversations rarely exceed 30 turns; safely under the token
# budget of both Kimi (262K) and MiniMax (128K).
MAX_HISTORY_TURNS = 20

# Don't overwrite existing lead.intent unless the classifier is confident.
INTENT_CONFIDENCE_THRESHOLD = 0.55


# Channels the dispatcher can actually deliver on (mirrors _dispatch_send).
# Voice (Phase 13) is intentionally excluded — sending on it is rejected.
SENDABLE_CHANNELS = {"sms", "email", "whatsapp"}


def _channel_can_reach(channel: str, identifier: str) -> bool:
    """Whether `channel` can deliver to a lead whose identifier is `identifier`.

    A lead has a single identifier (`Lead.phone`): an email address for email
    leads, a phone number otherwise. Sending email needs an address; sending
    sms/whatsapp needs a phone — picking the wrong one would dispatch to a
    nonsense recipient (e.g. emailing a phone number)."""
    is_email = "@" in identifier
    if channel == "email":
        return is_email
    if channel in ("sms", "whatsapp"):
        return not is_email
    return False


async def _latest_active_conversation(lead_id: int, db: AsyncSession) -> Conversation | None:
    """Return the most recently-active conversation for the lead, any channel."""
    row = await db.execute(
        select(Conversation)
        .where(
            Conversation.lead_id == lead_id,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .order_by(Conversation.last_at.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


async def _active_conversation_for_channel(
    lead_id: int, channel: str, db: AsyncSession
) -> Conversation | None:
    """The active conversation for a specific (lead, channel), if any."""
    row = await db.execute(
        select(Conversation)
        .where(
            Conversation.lead_id == lead_id,
            Conversation.channel == channel,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


async def send_human_message(
    lead_id: int,
    text: str,
    db: AsyncSession,
    *,
    subject: str | None = None,
    channel: str | None = None,
) -> dict[str, object]:
    """Send a human-authored reply to a lead.

    Returns a small status dict with the new outbound Message id + delivery_status.
    Used by the dashboard composer (the realtor types a reply and clicks Send).

    Channel selection:
      - `channel=None` (default): auto-pick the most recently-active conversation
        (back-compat). Errors `no_active_conversation` if the lead has none.
      - explicit `channel`: reuse that channel's active conversation, or create one
        if the lead hasn't used it yet (the realtor chose to start a new thread).
        Voice / unknown channels are rejected with `unsupported_channel`.
    """
    lead_row = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = lead_row.scalar_one_or_none()
    if lead is None:
        return {"status": "error", "error": "lead_not_found"}

    if channel is not None:
        if channel not in SENDABLE_CHANNELS:
            return {"status": "error", "error": "unsupported_channel"}
        if not _channel_can_reach(channel, lead.phone):
            # e.g. picking email for a phone-only lead — don't create an
            # undeliverable conversation; surface a clear error instead.
            return {"status": "error", "error": "channel_identifier_mismatch"}
        conv = await _active_conversation_for_channel(lead_id, channel, db)
        if conv is None:
            conv = Conversation(
                lead_id=lead_id,
                channel=channel,
                status=ConversationStatus.ACTIVE,
            )
            db.add(conv)
            await db.flush()
    else:
        conv = await _latest_active_conversation(lead_id, db)
        if conv is None:
            return {"status": "error", "error": "no_active_conversation"}

    # Build subject: for email, default to "Re: <last inbound subject>"; for
    # other channels, ignore the param.
    reply_subject: str | None = None
    if conv.channel == "email":
        if subject:
            reply_subject = subject
        else:
            last_inbound_row = await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.direction == MessageDirection.INBOUND,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_inbound = last_inbound_row.scalar_one_or_none()
            src_subj = (last_inbound.subject or "").strip() if last_inbound else ""
            if src_subj.lower().startswith("re:"):
                reply_subject = src_subj
            elif src_subj:
                reply_subject = f"Re: {src_subj}"
            else:
                reply_subject = "Tu consulta"

    outbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        sender=MessageSender.HUMAN,
        content=text,
        delivery_status=MessageStatus.PENDING,
        subject=reply_subject,
    )
    db.add(outbound)
    await db.flush()

    try:
        # For email threading, find the last inbound external_id to put in In-Reply-To.
        in_reply_to: str | None = None
        if conv.channel == "email":
            last_in_row = await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.direction == MessageDirection.INBOUND,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_in = last_in_row.scalar_one_or_none()
            in_reply_to = last_in.external_id if last_in else None

        external_id, _ = await _dispatch_send(
            conv.channel,
            to=lead.phone,
            text=text,
            subject=reply_subject,
            in_reply_to=in_reply_to,
        )
        outbound.external_id = external_id
        outbound.delivery_status = MessageStatus.SENT
    except Exception as exc:  # noqa: BLE001
        log.error("Human-send dispatch failed for lead %d: %s", lead_id, exc)
        outbound.delivery_status = MessageStatus.FAILED

    lead.last_message_at = datetime.now(UTC)
    await db.commit()
    log.info(
        "Human send: lead=%d channel=%s outbound=%d status=%s",
        lead_id, conv.channel, outbound.id, outbound.delivery_status.value,
    )
    return {
        "status": "ok",
        "lead_id": lead_id,
        "channel": conv.channel,
        "outbound_id": outbound.id,
        "outbound_status": outbound.delivery_status.value,
    }


async def generate_reply_suggestions(
    lead_id: int,
    db: AsyncSession,
    *,
    count: int = 3,
) -> dict[str, object]:
    """Generate N alternative reply texts the human can pick/edit/send.

    The LLM is asked for a JSON array of strings; on any failure we return an
    empty list + an `error` field so the UI degrades gracefully.
    """
    import json
    import re

    lead_row = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = lead_row.scalar_one_or_none()
    if lead is None:
        return {"suggestions": [], "error": "lead_not_found"}

    conv = await _latest_active_conversation(lead_id, db)
    if conv is None:
        return {"suggestions": [], "error": "no_active_conversation"}

    hist_row = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(MAX_HISTORY_TURNS)
    )
    history = list(reversed(hist_row.scalars().all()))
    if not history:
        return {"suggestions": [], "error": "empty_conversation"}

    llm_messages = [
        {
            "role": "user" if m.direction == MessageDirection.INBOUND else "assistant",
            # Without the attribution footer: it lives in `content`, so the
            # model read three credit lines back for every past turn and
            # dutifully repeated them.
            "content": strip_broker_credits(m.content),
        }
        for m in history
    ]

    # Language steering from the latest inbound.
    settings_row = await db.execute(select(AgentSettings).where(AgentSettings.org_id == _acting_org()))
    agent_cfg = settings_row.scalar_one_or_none()
    supported = (agent_cfg.languages if agent_cfg else ["en", "es"]) or ["en", "es"]
    last_user_content = next(
        (m.content for m in reversed(history) if m.direction == MessageDirection.INBOUND),
        history[-1].content,
    )
    target_lang = pick_supported_language(detect_language(last_user_content), supported)

    # IMPORTANT: do NOT reuse the inmobiliario persona here. The LLM gets
    # confused between "I am the assistant chatting with the user" and "I am
    # a draft generator" — the persona wins and it ignores the JSON instruction.
    # Use a task-only prompt that explicitly identifies as a draft generator.
    agency_name = agent_cfg.agency_name if agent_cfg else "Inmobiliaria"
    system_prompt = (
        "Sos un generador de borradores de respuesta. NO estás conversando con el cliente. "
        "Recibís el historial de WhatsApp/email entre un cliente potencial y la inmobiliaria, "
        "y producís varias respuestas posibles que el agente humano puede usar tal cual o "
        "editar antes de enviar."
        f"\n\nAGENCIA: {agency_name}"
        + language_instruction(target_lang, persona_locale="es")
        + (
            f"\n\nTAREA: generá EXACTAMENTE {count} borradores DISTINTOS entre sí "
            "(diferentes tonos / enfoques / preguntas), CORTOS (1-3 frases cada uno)."
            "\n\nFORMATO DE SALIDA OBLIGATORIO: un único array JSON de strings. SIN texto antes "
            "o después. SIN markdown. SIN claves. SIN explicación. SOLO el array."
            f"\n\nEjemplo de salida válida (formato literal, contenido distinto al tuyo):\n"
            f'[\"opción 1 corta\", \"opción 2 diferente\", \"opción 3 con pregunta\"]'
        )
    )

    try:
        result = await generate_reply(
            messages=llm_messages,
            system=system_prompt,
            max_tokens=500,
            temperature=0.7,
            json_mode=True,
        )
    except LLMUnavailable as exc:
        log.error("Suggestions failed — LLM unavailable: %s", exc)
        return {"suggestions": [], "error": f"llm_unavailable: {exc}"}

    # Parse the JSON array, tolerating prose around it.
    match = re.search(r"\[.*\]", result.text, re.DOTALL)
    if not match:
        log.warning("Suggestions: could not find JSON array in response: %r", result.text[:200])
        return {"suggestions": [], "error": "no_json_array", "raw": result.text[:200]}

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log.warning("Suggestions: invalid JSON: %s — raw: %r", exc, result.text[:200])
        return {"suggestions": [], "error": "invalid_json", "raw": result.text[:200]}

    if not isinstance(parsed, list):
        return {"suggestions": [], "error": "not_a_list"}

    # Coerce items to strings + drop empties + trim.
    suggestions = [str(s).strip() for s in parsed if isinstance(s, (str, int, float)) and str(s).strip()]
    return {
        "suggestions": suggestions[:count],
        "provider": result.provider,
        "model": result.model,
    }


_VOICE_INTENT_MAP = {
    "buy": LeadIntent.BUY,
    "rent": LeadIntent.RENT,
    "sell": LeadIntent.VALUATION,
    "valuation": LeadIntent.VALUATION,
    "other": LeadIntent.OTHER,
}


def _flatten_voice_structured(structured: dict) -> dict:
    """Normalize VAPI's structuredData to flat canonical keys.

    With an explicit `structuredDataPlan.schema` VAPI returns a flat shape
    (`intent`, `zone`, `budget_*`, `property_type`, `timeline`, `name`). Without
    one it auto-generates a NESTED shape (`property_inquiry`, `customer_info`).
    Read both so a lead always gets classified."""
    flat = dict(structured)
    pi = structured.get("property_inquiry")
    if isinstance(pi, dict):
        flat.setdefault("intent", pi.get("inquiry_type") or pi.get("intent"))
        flat.setdefault("zone", pi.get("location") or pi.get("zone"))
        flat.setdefault("budget_min", pi.get("budget_min"))
        flat.setdefault("budget_max", pi.get("budget_max"))
        flat.setdefault("property_type", pi.get("property_type"))
        flat.setdefault("timeline", pi.get("move_in_timeline") or pi.get("timeline"))
    ci = structured.get("customer_info")
    if isinstance(ci, dict):
        flat.setdefault("name", ci.get("name"))
    return flat


def _apply_voice_structured(lead: Lead, structured: dict) -> None:
    """Map a VAPI call's extracted structuredData onto the lead, conservatively
    (don't overwrite values the lead already has, except intent which reflects
    the latest call)."""
    s = _flatten_voice_structured(structured)
    raw_intent = str(s.get("intent") or "").strip().lower()
    if raw_intent in _VOICE_INTENT_MAP:
        lead.intent = _VOICE_INTENT_MAP[raw_intent]
    name = s.get("name")
    if isinstance(name, str) and name.strip() and not lead.name:
        lead.name = name.strip()
    zone = s.get("zone")
    if isinstance(zone, str) and zone.strip() and not lead.zone:
        lead.zone = zone.strip()
    for key in ("budget_min", "budget_max"):
        val = s.get(key)
        if val is not None and getattr(lead, key) is None:
            try:
                setattr(lead, key, int(float(val)))
            except (TypeError, ValueError):
                pass
    ptype = s.get("property_type")
    if isinstance(ptype, str) and ptype.strip() and not lead.property_type:
        lead.property_type = ptype.strip()
    timeline = s.get("timeline") or s.get("urgency")
    if isinstance(timeline, str) and timeline.strip() and not lead.urgency:
        lead.urgency = timeline.strip()


async def ingest_voice_call(report, db: AsyncSession) -> dict[str, int | str | bool]:
    """Ingest a finished VAPI call (channel="voice") into the lead timeline.

    The conversation already happened LIVE in the call, so — unlike the other
    channels — we do NOT call the LLM or send a reply. We upsert the lead, store
    each transcript turn as a Message (idempotent per call), apply the call's
    extracted fields, and rescore. `report` is a services.voice.VoiceCallReport.

    Caller commits the session.
    """
    # ── 1. Lead upsert (by identifier == Lead.phone, same as other channels) ──
    lead_row = await db.execute(select(Lead).where(Lead.phone == report.from_identifier))
    lead = lead_row.scalar_one_or_none()
    is_new_lead = lead is None
    if lead is None:
        lead = Lead(
            phone=report.from_identifier,
            name=report.from_name,
            email=_address_or_none(report.from_identifier),
        )
        db.add(lead)
        await db.flush()
        log.info("Created lead id=%d channel=voice identifier=%s", lead.id, lead.phone)
    elif report.from_name and not lead.name:
        lead.name = report.from_name

    # ── 2. Idempotency: a re-delivered report for the same call must not dup ──
    first_external_id = f"{report.call_id}#0"
    dup_row = await db.execute(select(Message).where(Message.external_id == first_external_id))
    already_ingested = dup_row.scalar_one_or_none() is not None

    # ── 3. Active voice conversation for this lead (anchored to the call id) ──
    conv = await _active_conversation_for_channel(lead.id, "voice", db)
    if conv is None:
        conv = Conversation(
            lead_id=lead.id,
            channel="voice",
            status=ConversationStatus.ACTIVE,
            external_thread_id=report.call_id,
        )
        db.add(conv)
        await db.flush()

    # ── 4. Persist transcript turns (skip if this call was already ingested) ──
    stored = 0
    if not already_ingested:
        turns = [
            Message(
                conversation_id=conv.id,
                direction=(
                    MessageDirection.INBOUND if role == "user" else MessageDirection.OUTBOUND
                ),
                sender=(MessageSender.LEAD if role == "user" else MessageSender.AGENT),
                content=text,
                external_id=f"{report.call_id}#{i}",
                delivery_status=MessageStatus.DELIVERED,
            )
            for i, (role, text) in enumerate(report.turns)
        ]
        stored = len(turns)
        if stored:
            lead.last_message_at = datetime.now(UTC)
            try:
                # Built first, added INSIDE the savepoint. `begin_nested()`
                # flushes anything already pending before issuing the SAVEPOINT,
                # so adding them beforehand ran the duplicate INSERT in the
                # outer transaction: the violation escaped `begin_nested()`
                # itself, the transaction went inactive, and the commit below
                # raised PendingRollbackError — losing the caller, transcript
                # and summary, and returning a 500 that VAPI redelivers.
                async with db.begin_nested():
                    db.add_all(turns)
                    await db.flush()
            except IntegrityError:
                log.info("Race-condition idempotent skip for voice call_id=%s", report.call_id)
                await db.commit()
                return {"status": "duplicate", "lead_id": lead.id, "skipped": True}

    # ── 5. Apply extracted fields + rescore ──────────────────────────────────
    if report.structured:
        _apply_voice_structured(lead, report.structured)
    await rescore_lead(lead, db, commit=False)
    await db.commit()

    log.info(
        "Voice call ingested: lead=%d call=%s turns_stored=%d intent=%s%s",
        lead.id, report.call_id, stored,
        lead.intent.value if lead.intent else "?",
        " (already_ingested)" if already_ingested else "",
    )
    return {
        "status": "duplicate" if already_ingested else "ok",
        "lead_id": lead.id,
        "call_id": report.call_id,
        "turns_stored": stored,
        "is_new_lead": is_new_lead,
    }




def _address_or_none(identifier: str | None) -> str | None:
    """The identifier, when it is an email address rather than a phone.

    Leads are keyed by `phone` on every channel, so an email lead's address has
    always been sitting in that column. Copying it into `email` is what lets a
    booking name the actual person instead of the agency's inbox.
    """
    value = (identifier or "").strip()
    return value if "@" in value else None



# Fixed, not `strftime("%A")`: that follows the container's locale, so an image
# with LC_TIME=es_* produced "lunes" and matched nothing, silently disabling
# every hours check.
_WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def _office_hours_note(agent_cfg: AgentSettings) -> str:
    """Tell the model what time it is at the office, and whether anyone is in.

    `business_hours` and `timezone` were stored, editable in Settings, and read
    by nothing: outside hours the agent replied exactly as it does at noon,
    promising a callback nobody was there to make. The hours are guidance for
    what to say, not a gate on replying — a lead who writes at 11pm should get
    an answer, just not one that implies someone is at a desk.
    """
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(agent_cfg.timezone or "UTC")
    except Exception:  # noqa: BLE001 — a bad timezone must not cost a reply
        return ""
    now = datetime.now(zone)
    note = (
        f"\n\nHORA LOCAL DE LA OFICINA: {now.strftime('%A %H:%M')} "
        f"({agent_cfg.timezone})."
    )
    hours = agent_cfg.business_hours if isinstance(agent_cfg.business_hours, dict) else {}
    if not hours:
        return note
    today = hours.get(_WEEKDAYS[now.weekday()])
    if isinstance(today, dict) and today.get("open") and today.get("close"):
        note += f" HORARIO DE HOY: {today['open']}–{today['close']}."
    elif today is None and _WEEKDAYS[now.weekday()] in hours:
        note += " HOY LA OFICINA NO ABRE."
    else:
        return note
    if not _office_is_open(now, today):
        note += (
            " Está CERRADA ahora mismo: responde igual y con la misma utilidad, "
            "pero no prometas que alguien llamará de inmediato — di cuándo abre."
        )
    return note


def _office_is_open(now: datetime, today: object) -> bool:
    """Whether the office is open, given one day of `business_hours`.

    A day is `{"open": "09:00", "close": "19:00"}` or None for closed. Anything
    it cannot read counts as open, so a malformed row never turns every reply
    into an out-of-hours one.
    """
    if today is None:
        return False
    if not isinstance(today, dict):
        return True
    try:
        opens = time.fromisoformat(str(today["open"]))
        closes = time.fromisoformat(str(today["close"]))
    except (KeyError, TypeError, ValueError):
        return True
    if opens <= closes:
        return opens <= now.time() <= closes
    # An evening span that crosses midnight — 22:00–02:00. Compared straight,
    # that condition is unsatisfiable, so an agency with evening hours had every
    # reply told the office was shut.
    return now.time() >= opens or now.time() <= closes


def _greeting_note(agent_cfg: AgentSettings) -> str:
    """The agency's own opening line, for a lead we have never heard from.

    Also stored, editable and previously unused, so an agency that wrote one
    watched the agent open with something else every time.
    """
    template = (agent_cfg.greeting_template or "").strip()
    if not template:
        return ""
    opening = template.replace("{agency_name}", agent_cfg.agency_name or "")
    return (
        "\n\nES EL PRIMER MENSAJE DE ESTE LEAD. Abre con esta línea de la "
        f"agencia, adaptada al idioma del lead: {opening}"
    )



# Words that mean the lead is trying to arrange a time, in the two languages
# the agent speaks. Deliberately a plain list: this only decides whether to
# spend one calendar call, and a missed match costs a generic answer rather
# than a wrong one.
_SCHEDULING_WORDS = (
    "visit", "visits", "viewing", "viewings", "tour", "appointment", "schedule",
    "book", "booking", "available", "availability", "cita", "citas", "visita",
    "visitar", "verlo", "verla", "agendar", "agenda", "disponible",
    "disponibilidad", "horario", "horarios",
)

# Phrases are checked as-is; single words are checked on word boundaries. As
# substrings they matched constantly — "cita" inside necesita, solicita and
# felicita, "book" inside Facebook and bookkeeping, "tour" inside detour — so a
# routine Spanish thread spent a calendar call per message.
_SCHEDULING_PHRASES = ("see the", "see it", "when can", "what time", "cuando pued")

_SCHEDULING_RE = re.compile(
    r"\b(?:" + "|".join(_SCHEDULING_WORDS) + r")\b", re.IGNORECASE
)


_SLOTS_BUDGET_SECONDS = 4.0


async def _real_slots_note(
    agent_cfg: AgentSettings, message: str | None, db: AsyncSession
) -> str:
    """The agency's actual next openings, when the lead is asking for a time.

    The chat agent has no tools wired, so it cannot query a calendar or make a
    booking — and left to itself it invents plausible times, which is worse
    than saying nothing. Handing it the real slots is the same trick already
    used for listings: the model never guesses, it picks from what is true.
    Booking still happens from the dashboard or by phone.
    """
    text = (message or "").lower()
    if not _SCHEDULING_RE.search(text) and not any(
        phrase in text for phrase in _SCHEDULING_PHRASES
    ):
        return ""
    from datetime import timedelta

    from app.api.v1.visits import _busy_starts
    from app.services.calendar_cal import list_available_slots

    now = datetime.now(UTC)
    try:
        # The agency's own diary, not just Cal.com's: a visit entered by hand in
        # the dashboard exists only in `visits`, and offering that hour sends a
        # realtor to two houses.
        busy = await _busy_starts(db, since=now, until=now + timedelta(days=7))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read booked visits for the reply: %s", exc)
        busy = set()
    try:
        # Hard budget. This runs inline in the webhook, ahead of a 30s LLM call,
        # and Cal.com's own client waits 15s — enough on its own to push an SMS
        # turn past Twilio's window and earn an 11200, or make Meta redeliver.
        # Real openings are worth having; they are not worth the turn.
        slots = await asyncio.wait_for(
            list_available_slots(
                start=now,
                end=now + timedelta(days=7),
                timezone_name=agent_cfg.timezone or "UTC",
                busy_starts=busy,
            ),
            timeout=_SLOTS_BUDGET_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — a calendar blip must not cost a reply
        log.warning("could not read availability for the reply: %s", exc)
        return ""
    if not slots:
        return ""
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(agent_cfg.timezone or "UTC")
    except Exception:  # noqa: BLE001
        zone = UTC
    offered = ", ".join(
        slot.start.astimezone(zone).strftime("%A %d %H:%M") for slot in slots[:5]
    )
    return (
        "\n\nHUECOS REALES DISPONIBLES (zona de la oficina): "
        f"{offered}. Ofrece SOLO estos si el lead pide cita; NUNCA inventes "
        "otros. Para confirmar, dile que un agente cierra la cita enseguida."
    )



# Twilio hard-rejects above this, and a rejected message is now retried five
# times before it is given up on. WhatsApp's limit is far higher; SMS sets the
# floor, so use it for both.
_SMS_MAX_CHARS = 1500


# What separates a reply that shows a listing from one that does not. Kept
# generous on purpose: a miss is an uncredited listing, a false positive is a
# redundant line.
_MONEY = re.compile(r"[$€]\s?\d|\d{3}[.,]\d{3}|\b\d{3}\s?k\b", re.IGNORECASE)


def _reply_shows(reply: str, title: str | None, address: str | None) -> bool:
    """Whether this reply puts a listing's details in front of the consumer.

    Attribution is owed when a listing's data is shown, so this is the right
    question — the earlier versions just answered it badly, by looking for one
    exact string the model was free to paraphrase away. Several signals now,
    any of which is enough: the title, the address, the street number, or a
    price anywhere in the reply. "Abrimos de 9 a 6" matches none of them; "the
    Wash Park house is $650k" matches on the price alone.
    """
    haystack = reply.lower()
    for value in (title, address):
        if not value or not value.strip():
            continue
        if value.strip().lower() in haystack:
            return True
        # And the part before the first comma — "Coldwell Banker Tower, Unit 5"
        # gets referred to as "the Coldwell Banker Tower unit", which carries
        # the listing's identity without matching the whole string.
        head = value.split(",", 1)[0].strip().lower()
        if len(head) >= 8 and head in haystack:
            return True
    if address:
        number = address.strip().split(" ", 1)[0]
        if number.isdigit() and number in reply:
            return True
    return bool(_MONEY.search(reply))


def _with_broker_credits(
    reply: str, offered: list[tuple[str, str, str | None]], channel: str
) -> str:
    """Append the listing brokers' credits to the message that reaches the lead.

    Colorado requires the broker to be named wherever a listing's details reach
    a consumer. Crediting on every turn regardless — which is what dropping the
    detection altogether produced — staples three brokers onto "we open at
    nine", on every message for the rest of the conversation. Crediting only on
    an exact title match misses the moment the model paraphrases. So: credit
    when the reply shows listing data at all, and then credit every broker
    whose listing was offered, because which of them the model actually used is
    not knowable from the text.
    """
    if not offered or not any(broker for broker, _t, _a in offered):
        return reply
    if not any(_reply_shows(reply, title, address) for _b, title, address in offered):
        return reply

    lines: list[str] = []
    for broker, _title, _address in offered:
        if not broker:
            continue
        line = f"Cortesía de {broker}"
        # This exact credit, not the bare name — a listing titled "Coldwell
        # Banker Tower" otherwise suppressed Coldwell Banker's credit.
        if line.lower() in reply.lower() or line in lines:
            continue
        lines.append(line)
    if not lines:
        return reply

    if channel not in ("sms", "whatsapp"):
        return reply.rstrip() + "\n\n" + " · ".join(lines)

    # Twilio hard-rejects past its limit, and a rejected message is retried five
    # times before being given up on. Fit the credits and let the prose give
    # way — but never return something still over the limit, which is what
    # subtracting an oversized footer from the budget did.
    footer = "\n\n" + " · ".join(lines)
    while len(lines) > 1 and len(footer) > _SMS_MAX_CHARS // 2:
        lines.pop()
        footer = "\n\n" + " · ".join(lines) + " · y otros corredores listantes"
    if len(footer) > _SMS_MAX_CHARS // 2:
        # One name too long to fit is still a listing that must be credited.
        footer = "\n\nCortesía de los corredores listantes"
    room = _SMS_MAX_CHARS - len(footer)
    body = reply if len(reply) <= room else reply[: max(0, room - 1)].rstrip() + "…"
    return body.rstrip() + footer


def strip_broker_credits(content: str) -> str:
    """The message without its attribution footer.

    The footer lives in `Message.content`, which is also what conversation
    history is built from — so without this the model reads three credit lines
    back for every past turn, and repeats them.
    """
    marker = "\n\nCortesía de"
    return content.split(marker, 1)[0].rstrip() if marker in content else content


def _fallback_reply(agent_cfg: AgentSettings | None, target_lang: str) -> LLMResult:
    """What to say when every language model is unreachable.

    Deliberately not an apology for a technical fault the lead did not cause,
    and deliberately not a promise of a time we cannot keep. It acknowledges
    the message and hands over to a person, which is what a lead needs at
    11pm when the alternative is silence.
    """
    who = (agent_cfg.agency_name if agent_cfg else None) or "the team"
    # In the language the lead wrote in. `target_lang` was in scope and unused,
    # so a Spanish WhatsApp lead at 11pm got an English apology.
    if (target_lang or "").lower().startswith("es"):
        text = (
            f"Gracias por tu mensaje — {who} lo ha recibido y alguien te "
            "responderá en breve."
        )
    else:
        text = (
            f"Thanks for your message — {who} has received it and someone will "
            "get back to you shortly."
        )
    # An LLMResult, not a bare string: everything downstream reads `.text`,
    # `.provider` and `.model` off this, and `provider="fallback"` is what the
    # dashboard and the analytics need to see to tell a canned line apart from
    # something the model wrote.
    return LLMResult(
        text=text,
        provider="fallback",
        model="none",
        input_tokens=0,
        output_tokens=0,
    )


async def handle_inbound_message(parsed: ParsedMessage, db: AsyncSession) -> dict[str, int | str | bool]:
    """Process one inbound message (any channel) end-to-end. Returns a small status dict.

    Caller (the FastAPI route) is responsible for committing the session.
    Idempotency: UNIQUE constraint on Message.external_id catches webhook retries.
    Lead lookup is by `phone` for whatsapp/sms/voice, by a synthetic key
    (phone column doubles as identifier) for email — the column accepts any
    string up to 32 chars; we store the email address there too.
    """
    # ── 0. Self-loop guard ─────────────────────────────────────────────
    # Never process an inbound that came from our OWN sending address. The
    # agent emails from noreply@<domain>, which is also receivable on that
    # domain — so a reply (or a bounce) addressed back to it would re-enter
    # here and the agent would answer itself forever. Drop it silently.
    if parsed.channel == "email":
        # The acting agency's own address, not the global one. With per-agency
        # mailboxes a global guard tests against somebody else's address, so
        # agency B's own bounces sail past it and the assistant answers itself
        # in a loop — while a message genuinely from agency A would be dropped
        # inside agency B.
        from app.models.channel_route import CHANNEL_EMAIL
        from app.services.channel_identity import resolve_outbound_identity

        identity = await resolve_outbound_identity(CHANNEL_EMAIL)
        own = parseaddr(identity.sender_override or identity.destination or "")[1]
        own = own.strip().lower()
        if own and parsed.from_identifier.strip().lower() == own:
            log.warning("Inbound from our own address %s — ignored (self-loop guard)", own)
            return {"status": "ignored_self_loop", "from": parsed.from_identifier}

    # ── 1. Lead upsert ──────────────────────────────────────────────────
    # By identifier, and also by a matching email address. Leads are keyed on
    # `phone` for every channel, so the same person writing from WhatsApp and
    # then from email became two records: two score histories, two rows in the
    # funnel, and a realtor looking at half a conversation each time. Matching
    # the address as well merges the second arrival into the first.
    #
    # Deliberately one-directional: an email that matches an existing lead's
    # address is the same person. A phone number is never matched against an
    # address, and two different phone numbers stay two leads — guessing
    # further would merge strangers.
    # Prefer the lead keyed on this exact identifier. Only when there is none,
    # and exactly one other lead carries this address, treat it as the same
    # person. Taking the oldest of several matches — which the first version of
    # this did — silently picked one and left the other's conversations, score
    # and funnel row orphaned, while the code believed it had merged them.
    lead_stmt = select(Lead).where(Lead.phone == parsed.from_identifier)
    if _address_or_none(parsed.from_identifier) is not None:
        already = (await db.execute(lead_stmt)).scalars().first()
        if already is None:
            by_address = (
                (
                    await db.execute(
                        select(Lead).where(Lead.email == parsed.from_identifier)
                    )
                )
                .scalars()
                .all()
            )
            if len(by_address) == 1:
                lead_stmt = select(Lead).where(Lead.id == by_address[0].id)
            elif len(by_address) > 1:
                # A shared mailbox — info@, or a family address. Merging any of
                # them would put one person's conversation in front of another.
                log.warning(
                    "%d leads share the address %s; keeping them separate",
                    len(by_address),
                    parsed.from_identifier,
                )
    existing_lead = (await db.execute(lead_stmt)).scalars().first()
    is_new_lead = existing_lead is None
    lead = await first_or_create(
        db,
        lead_stmt,
        lambda: Lead(
            phone=parsed.from_identifier,
            name=parsed.from_name,
            email=_address_or_none(parsed.from_identifier),
        ),
    )
    if is_new_lead and lead.id is not None:
        log.info("Created lead id=%d channel=%s identifier=%s", lead.id, parsed.channel, lead.phone)
    if parsed.from_name and not lead.name:
        lead.name = parsed.from_name

    # ── 2. Active conversation ─────────────────────────────────────────
    # Multichannel: one active conversation per (lead, channel). A lead that
    # writes both email AND whatsapp gets TWO active conversations. The partial
    # unique index behind this is what lets the get-or-create resolve a race
    # instead of leaving two ACTIVE rows that make every later message from
    # that lead raise MultipleResultsFound.
    conv_stmt = (
        select(Conversation)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.channel == parsed.channel,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    conv = await first_or_create(
        db,
        conv_stmt,
        lambda: Conversation(
            lead_id=lead.id,
            channel=parsed.channel,
            status=ConversationStatus.ACTIVE,
            external_thread_id=parsed.thread_id,
        ),
    )
    if parsed.thread_id and not conv.external_thread_id:
        conv.external_thread_id = parsed.thread_id

    # ── 3. Idempotency check ───────────────────────────────────────────
    dup_row = await db.execute(
        select(Message).where(Message.external_id == parsed.external_id)
    )
    if dup_row.scalar_one_or_none() is not None:
        log.info(
            "Duplicate webhook for external_id=%s channel=%s — idempotent skip",
            parsed.external_id, parsed.channel,
        )
        return {"status": "duplicate", "lead_id": lead.id, "skipped": True}

    # ── 4. Persist inbound ─────────────────────────────────────────────
    inbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.INBOUND,
        sender=MessageSender.LEAD,
        content=parsed.content or "",
        external_id=parsed.external_id,
        delivery_status=MessageStatus.DELIVERED,
        subject=parsed.subject,
    )
    lead.last_message_at = datetime.now(UTC)
    try:
        # `db.add` goes INSIDE. `begin_nested()` flushes whatever is already
        # pending before it issues the SAVEPOINT, so adding first meant the
        # duplicate INSERT ran in the outer transaction: the IntegrityError came
        # out of `begin_nested()` itself, the root transaction went inactive,
        # and the `await db.commit()` below raised PendingRollbackError. The
        # savepoint protected nothing and turned a duplicate into a 500 that the
        # provider retries forever.
        async with db.begin_nested():
            db.add(inbound)
            await db.flush()
    except IntegrityError:
        log.info("Race-condition idempotent skip for external_id=%s", parsed.external_id)
        await db.commit()
        return {"status": "duplicate", "lead_id": lead.id, "skipped": True}

    # ── 5. Human takeover check ────────────────────────────────────────
    if lead.human_takeover:
        await rescore_lead(lead, db, commit=False)
        await db.commit()
        log.info("Lead %d on human_takeover — skipping AI reply", lead.id)
        return {"status": "human_takeover", "lead_id": lead.id, "inbound_id": inbound.id}

    # ── 6. Build history for LLM ───────────────────────────────────────
    hist_row = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(MAX_HISTORY_TURNS)
    )
    history = list(reversed(hist_row.scalars().all()))
    llm_messages = [
        {
            "role": "user" if m.direction == MessageDirection.INBOUND else "assistant",
            # Without the attribution footer: it lives in `content`, so the
            # model read three credit lines back for every past turn and
            # dutifully repeated them.
            "content": strip_broker_credits(m.content),
        }
        for m in history
    ]

    # ── 7. Language detection + intent classification ─────────────────
    # Detect on the latest inbound only (avoid letting historical AI replies
    # bias the result). Pick the closest supported language from agent settings.
    agent_cfg_stmt = select(AgentSettings).where(AgentSettings.org_id == _acting_org())
    agent_cfg = (await db.execute(agent_cfg_stmt)).scalars().first()
    supported_languages = (agent_cfg.languages if agent_cfg else ["en", "es"]) or ["en", "es"]
    detected_lang = detect_language(parsed.content)
    target_lang = pick_supported_language(detected_lang, supported_languages)

    intent_result = await classify_intent(llm_messages, language_hint=target_lang)
    if intent_result.confidence >= INTENT_CONFIDENCE_THRESHOLD:
        lead.intent = intent_result.intent
        e = intent_result.entities
        if e.zone and not lead.zone:
            lead.zone = e.zone
        if e.budget_min is not None and lead.budget_min is None:
            lead.budget_min = e.budget_min
        if e.budget_max is not None and lead.budget_max is None:
            lead.budget_max = e.budget_max
        if e.property_type and not lead.property_type:
            lead.property_type = e.property_type
        if e.urgency and not lead.urgency:
            lead.urgency = e.urgency

    # ── 8. Reply generation ────────────────────────────────────────────
    if agent_cfg is None:
        # Bootstrap the singleton on first real interaction.
        # No pinned id. Org 1 owns agent_settings.id = 1, so forcing it here made
        # every inbound message for any other tenant die on a primary-key
        # collision — the read filter above was fixed and this write was missed,
        # which moved the crash from the SELECT to the flush instead of ending it.
        #
        # `org_id` is unique here, so on a fresh tenant N simultaneous first
        # contacts all reach this point, one wins, and the rest used to die at
        # the flush with their lead, conversation and message already in the
        # transaction. That is the "3 of 4 leads vanished" case: the handler
        # read the violation as a duplicate message and answered 200.
        agent_cfg = await first_or_create(db, agent_cfg_stmt, AgentSettings)

    # Persona is authored in Spanish; the language steering line tells the LLM
    # which language to actually answer in (detected from the inbound message).
    system_prompt = agent_cfg.agent_persona.replace("{agency_name}", agent_cfg.agency_name)
    system_prompt += language_instruction(target_lang, persona_locale="es")
    system_prompt += _office_hours_note(agent_cfg)
    if is_new_lead:
        system_prompt += _greeting_note(agent_cfg)
    system_prompt += await _real_slots_note(agent_cfg, inbound.content, db)

    # Phase 10: if the lead is property-shopping and we know the zone, give the
    # LLM the REAL matching listings so it can offer them (and never invent any).
    # Collected here and appended to the reply itself further down. Putting the
    # credit only in the system prompt made a licence obligation depend on the
    # model choosing to repeat it, which it will not always do.
    offered_listings: list[tuple[str, str, str | None]] = []
    if lead.intent in (LeadIntent.BUY, LeadIntent.RENT) and lead.zone:
        try:
            from app.services.listings import match_properties_for_lead  # lazy import
            matches = await match_properties_for_lead(lead, db, limit=3)
        except Exception as exc:  # noqa: BLE001
            log.warning("Listings match failed for lead %d: %s", lead.id, exc)
            matches = []
        if matches:
            lines = []
            for p in matches:
                price = f"${int(p.price):,}" if p.price is not None else "price on request"
                beds = f"{p.bedrooms}bd" if p.bedrooms else ""
                baths = f"{float(p.bathrooms):g}ba" if p.bathrooms is not None else ""
                specs = " ".join(x for x in (beds, baths) if x)
                broker = listing_broker((p.raw or {}).get("list_office_name"), p.source)
                credit = f"Cortesía de {broker}" if broker else ""
                if broker:
                    offered_listings.append((broker, p.title, p.address))
                lines.append(
                    f"- {p.title} — {price}{(' · ' + specs) if specs else ''}"
                    f"{(' · ' + p.address) if p.address else ''}{(' · ' + p.url) if p.url else ''}"
                    f"{(' · ' + credit) if credit else ''}"
                )
            system_prompt += (
                "\n\nLISTINGS DISPONIBLES QUE PUEDES OFRECER (usa SOLO estas, NO inventes "
                "ni cites otras; si encajan con lo que pide, ofrécelas con naturalidad):\n"
                + "\n".join(lines)
            )

    try:
        reply = await generate_reply(messages=llm_messages, system=system_prompt, max_tokens=400)
    except LLMUnavailable as exc:
        log.error("All LLMs failed for lead %d: %s", lead.id, exc)
        # Say something. The webhook answers 200 either way, so the provider
        # never redelivers — silence here means a lead who wrote at 11pm gets
        # nothing at all and no one finds out until they have gone elsewhere.
        # A short human note costs nothing and keeps the conversation open.
        reply = _fallback_reply(agent_cfg, target_lang)

    # ── 9. Persist outbound (status=PENDING) ──────────────────────────
    reply_subject = None
    if parsed.channel == "email":
        # Email reply: keep the subject, prepend "Re: " unless already present.
        src_subj = (parsed.subject or "").strip()
        if src_subj.lower().startswith("re:"):
            reply_subject = src_subj
        elif src_subj:
            reply_subject = f"Re: {src_subj}"
        else:
            reply_subject = "Tu consulta"

    # The broker credit goes on the message that actually reaches the lead.
    # Only for the listings the reply mentions, and only once each — otherwise a
    # long conversation accumulates a footer nobody reads and the credit stops
    # meaning anything.
    reply_text = _with_broker_credits(reply.text, offered_listings, parsed.channel)

    outbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        sender=MessageSender.AGENT,
        content=reply_text,
        delivery_status=MessageStatus.PENDING,
        llm_provider=reply.provider,
        llm_model=reply.model,
        subject=reply_subject,
    )
    db.add(outbound)
    await db.flush()

    # ── 10. Dispatch send through the right channel adapter ──────────
    try:
        # Threading: reply In-Reply-To the inbound's Message-ID, and set References
        # to the full chain (thread root … this message) so Gmail/Outlook reliably
        # nest the reply inside the existing conversation instead of a new thread.
        email_references = None
        if parsed.channel == "email":
            chain = [t for t in (parsed.thread_id, parsed.external_id) if t]
            # dedupe while preserving order
            seen: set[str] = set()
            chain = [t for t in chain if not (t in seen or seen.add(t))]
            email_references = " ".join(chain) or None
        external_id, _ = await _dispatch_send(
            parsed.channel,
            to=parsed.from_identifier,
            text=reply_text,
            subject=reply_subject,
            in_reply_to=parsed.external_id if parsed.channel == "email" else None,
            references=email_references,
        )
        try:
            # The assignments go INSIDE the savepoint: `begin_nested()` flushes
            # pending work before opening it, so setting them first put the
            # colliding UPDATE in the outer transaction and left the session
            # unusable rather than protected.
            #
            # Stamping the provider's id can collide on uq_messages_external_id
            # — a provider replaying an id, or two replies landing on the same
            # one. The reply really was sent, and this transaction also holds
            # the lead, the conversation and the inbound message: none of that
            # may be thrown away because a bookkeeping column would not fit.
            async with db.begin_nested():
                outbound.external_id = external_id
                outbound.delivery_status = MessageStatus.SENT
                await db.flush()
        except IntegrityError:
            log.warning(
                "Duplicate provider id %s on outbound msg %d; keeping the turn "
                "and leaving the id unset",
                external_id, outbound.id,
            )
            outbound.external_id = None
            outbound.delivery_status = MessageStatus.SENT
    except Exception as exc:  # noqa: BLE001
        log.error("Channel %s send failed for outbound msg %d: %s", parsed.channel, outbound.id, exc)
        # Not just FAILED. A provider blip used to end the reply's life here:
        # one POST, no retry, and no sweep looking for what was left behind.
        schedule_retry(outbound, str(exc))

    await rescore_lead(lead, db, commit=False)
    await db.commit()
    log.info(
        "Turn done: lead=%d channel=%s inbound=%d outbound=%d intent=%s provider=%s status=%s",
        lead.id, parsed.channel, inbound.id, outbound.id,
        lead.intent.value if lead.intent else "?",
        reply.provider,
        outbound.delivery_status.value,
    )
    return {
        "status": "ok",
        "lead_id": lead.id,
        "channel": parsed.channel,
        "is_new_lead": is_new_lead,
        "inbound_id": inbound.id,
        "outbound_id": outbound.id,
        "outbound_status": outbound.delivery_status.value,
        "llm_provider": reply.provider,
    }


def _acting_org() -> int:
    """The org whose settings row applies to this call."""
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

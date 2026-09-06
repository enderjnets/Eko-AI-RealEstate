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
from dataclasses import dataclass
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
from app.services.fair_housing import find_violations
from app.services.i18n import (
    detect_for,
    detect_language,
    language_instruction,
    pick_supported_language,
)
from app.services.lead_events import record
from app.services.lead_fields import (
    merge_budget,
    storable_budget,
    storable_text,
)
from app.services.listings import listing_broker
from app.services.llm import LLMResult, LLMUnavailable, generate_reply
from app.services.optout import (
    CONFIRMATION,
    RESUMED,
    opt_in_keyword,
    opt_out_keyword,
)
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


async def reachable_active_conversations(
    lead_id: int, identifier: str, db: AsyncSession
) -> list[Conversation]:
    """Every active conversation that can deliver to this lead, newest first.

    The follow-up worker needs the whole list, not just the newest. It used to
    take the newest reachable one and, if the consent gate refused that channel,
    mark the follow-up SKIPPED — a terminal status. So a lead who genuinely
    initiated contact on WhatsApp lost their nurture sequence permanently the
    moment a realtor answered them once by SMS: the SMS thread became the
    newest, the gate correctly refused it (consent is per channel), and the
    WhatsApp thread that would have passed was never consulted.
    """
    reachable = [c for c in SENDABLE_CHANNELS if _channel_can_reach(c, identifier)]
    if not reachable:
        return []
    rows = await db.execute(
        select(Conversation)
        .where(
            Conversation.lead_id == lead_id,
            Conversation.status == ConversationStatus.ACTIVE,
            Conversation.channel.in_(reachable),
        )
        .order_by(Conversation.last_at.desc())
    )
    return list(rows.scalars())


async def _latest_active_conversation(
    lead_id: int, db: AsyncSession, *, identifier: str | None = None
) -> Conversation | None:
    """The most recently-active conversation for the lead.

    With `identifier`, only conversations that can actually deliver to that
    lead are considered. Both callers that auto-pick a channel — the dashboard
    composer and the follow-up worker — hand the result straight to
    `_dispatch_send`, and the newest active conversation is not necessarily one
    anything can be sent through. A lead who arrived through the public web
    form has a `web` conversation, which exists to show what they wrote and can
    receive nothing: without this filter their first submission made the reply
    button fail and marked every scheduled follow-up FAILED.

    The argument is optional and off by default so callers that only want to
    read the thread keep their existing behaviour.
    """
    stmt = select(Conversation).where(
        Conversation.lead_id == lead_id,
        Conversation.status == ConversationStatus.ACTIVE,
    )
    if identifier is not None:
        reachable = [c for c in SENDABLE_CHANNELS if _channel_can_reach(c, identifier)]
        if not reachable:
            return None
        stmt = stmt.where(Conversation.channel.in_(reachable))
    row = await db.execute(stmt.order_by(Conversation.last_at.desc()).limit(1))
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

    if lead.opted_out_at is not None:
        # Every automated path already refuses here — the sweep, the retry, the
        # dispatch gate, the booking route. This one did not, and it is the one
        # a person uses on a lead who has gone quiet. Measured before it was
        # written: a lead who texted STOP got HTTP 200 and the message was
        # delivered.
        #
        # Opt-out is not a preference the sender can weigh against a good
        # reason. It is revoked consent, it outranks everything else on record,
        # and the fact that we stored it and sent anyway is what turns a $500
        # message into a $1,500 one. A realtor who needs to reach this person
        # can phone them; that consent is separate and this system is not the
        # one making that call.
        return {
            "status": "error",
            "error": "lead_opted_out",
            "opted_out_at": lead.opted_out_at.isoformat(),
            "opted_out_keyword": lead.opted_out_keyword,
        }

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
        # Scoped to what can reach this lead. Without that, a lead whose newest
        # thread is the `web` one from the public form made this return a
        # conversation nothing can be sent through, and the realtor's reply
        # died in `_dispatch_send` with an error about an unknown channel.
        conv = await _latest_active_conversation(lead_id, db, identifier=lead.phone)
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
        # Setting FAILED and nothing else left `next_attempt_at` NULL, which
        # matches neither branch of the retry sweep's query: the realtor's own
        # reply sat in the database forever while the dashboard reported it
        # sent. The automated reply below has always been queued here; this one
        # never was.
        schedule_retry(outbound, str(exc))

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
        # Internal notes are in the thread but were never said to the lead.
        # Feeding one to the model makes it a conversational turn the model can
        # quote back, so both history builders filter it out — this one and the
        # reply lane's at the "Build history for LLM" step.
        .where(Message.conversation_id == conv.id, Message.internal.is_(False))
        # Tie-broken by id, and with a LIMIT on top it is not cosmetic: a voice
        # call writes its whole transcript at hang-up, so its turns share one
        # timestamp. Measured on 27 tied rows, `created_at DESC LIMIT 20`
        # returned the twenty OLDEST — the last seven turns of the call, where
        # the booking is agreed, were dropped before the model ever saw them.
        .order_by(Message.created_at.desc(), Message.id.desc())
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
            "content": history_content(m),
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
    target_lang = detect_for(last_user_content, supported)

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
    # Everything below goes through the same helpers as the chat path. This is
    # a voice agent's reading of a phone call — as much a guess as the chat
    # classifier's — and it is applied inside the transaction that stores the
    # caller's transcript. A value the table refuses does not lose a field, it
    # loses the record of the call, and VAPI redelivers the same payload so
    # every retry fails identically.
    if (name := storable_text(s.get("name"), "name")) and not lead.name:
        lead.name = name
    if (zone := storable_text(s.get("zone"), "zone")) and not lead.zone:
        lead.zone = zone

    # `int(float(val))` used to be the whole defence: it let negatives,
    # overflows and NaN through, and raised OverflowError on infinity — which
    # nothing caught.
    # Only offer what the lead is missing. This function is called on every
    # delivery of a report, including redeliveries of one already ingested, so
    # letting an extracted range win would silently undo a correction the
    # realtor typed by hand — they fix 100k-900k to 300k-400k, VAPI resends the
    # same call, and their edit is gone with no sign it ever happened.
    #
    # A complete range still lands in one go on a lead with no budget at all,
    # because both sides are offered then.
    lead.budget_min, lead.budget_max = merge_budget(
        (lead.budget_min, lead.budget_max),
        (
            storable_budget(s.get("budget_min")) if lead.budget_min is None else None,
            storable_budget(s.get("budget_max")) if lead.budget_max is None else None,
        ),
    )

    if (ptype := storable_text(s.get("property_type"), "property_type")) and not lead.property_type:
        lead.property_type = ptype
    timeline = storable_text(s.get("timeline") or s.get("urgency"), "urgency")
    if timeline and not lead.urgency:
        lead.urgency = timeline


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
            # Trimmed: the column is 160 characters and this comes from the
            # provider, inside the transaction that stores the transcript.
            name=storable_text(report.from_name, "name"),
            email=_address_or_none(report.from_identifier),
        )
        db.add(lead)
        await db.flush()
        log.info("Created lead id=%d channel=voice identifier=%s", lead.id, lead.phone)
    elif report.from_name and not lead.name:
        lead.name = storable_text(report.from_name, "name")

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

    # The call's own summary, kept once. VAPI's analysis was parsed and thrown
    # away until now, so "what did they want" existed only as a transcript
    # somebody had to read. `not conv.summary` because a redelivered report
    # must not overwrite a summary a person may have since edited.
    summary_was_new = bool(report.summary and not conv.summary)
    if summary_was_new:
        conv.summary = report.summary[:5000]

    await db.commit()

    # ── 6. The history row, AFTER the call is safely stored ──────────────────
    #
    # Deliberately after the commit above and inside its own try. This is
    # analytics; the four lines before it are a customer's phone call. A NOT
    # NULL this code did not anticipate, or a policy that refuses the row,
    # would otherwise leave the session in PendingRollback and take the
    # transcript with it — which is exactly how a transcript was lost here
    # once already, and the comment forty lines up is the scar.
    if not already_ingested:
        try:
            record(
                db,
                lead,
                "call_inbound",
                actor="vapi",
                at=report.started_at,
                meta={
                    "call_id": report.call_id,
                    "duration_seconds": report.duration_seconds,
                    "ended_reason": report.ended_reason,
                    "recording_url": report.recording_url,
                    "cost": report.cost,
                    "conversation_id": conv.id,
                },
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - the call is already safe
            log.warning("Could not record the call in the lead's history: %s", exc)
            try:
                await db.rollback()
            except Exception:
                log.warning("Rollback after the history failure also failed")

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
        "conversation_id": conv.id,
        "turns_stored": stored,
        # Whether the summary was written on THIS delivery. The caller needs it
        # to decide whether to tell a human, and only this function can answer
        # it: idempotency is keyed on `<call_id>#0`, a row a transcript-less
        # report never writes — so a report carrying an analysis summary and no
        # turns comes back "ok" on every redelivery, and a guard that trusted
        # `status` alone would mail the agency the same call twice.
        #
        # Narrower than "this delivery learned something", and the difference is
        # a known gap: the conversation is the lead's ACTIVE voice thread, not
        # one per call, and nothing closes it — so `conv.summary` belongs to the
        # first call that had one and a later call's summary is neither stored
        # nor announced. Backlogged; the fix is an idempotency row per call.
        "summary_was_new": summary_was_new,
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
    from app.services.timezones import resolve_zone

    # The fifth call site. The sweep that centralised this said "four", and an
    # audit counted five — the miscount is the finding, not the behaviour, which
    # was already right: an unusable zone costs the note, never the reply.
    zone = resolve_zone(agent_cfg.timezone or "UTC")
    if zone is None:
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
    agent_cfg: AgentSettings, message: str | None, db: AsyncSession, lead: Lead | None = None
) -> str:
    """The agency's actual next openings, when the lead is asking for a time.

    The chat agent has no tools wired, so it cannot query a calendar or make a
    booking — and left to itself it invents plausible times, which is worse
    than saying nothing. Handing it the real slots is the same trick already
    used for listings: the model never guesses, it picks from what is true.
    Booking still happens from the dashboard or by phone.
    """
    from app.config import get_settings

    # Interim funnel: appointments are arranged personally, so the model must
    # not quote times. The instruction rides EVERY turn while the flag is on —
    # deliberately in front of the keyword gate below, because the gate is a
    # heuristic and an audit measured five ordinary ways of asking for a time
    # that slip past it ("can I come by tomorrow at 3pm?", "nos vemos el
    # martes a las 5?"...). Missing the gate used to cost a reply with no
    # hours in it; while paused it would cost invented ones — the docstring
    # above records that a model left without instructions INVENTS plausible
    # hours. One temporary paragraph in the prompt is the cheaper failure.
    if get_settings().BOOKING_OFFERS_PAUSED:
        return (
            "\n\nCITAS EN PAUSA: no ofrezcas, confirmes ni inventes horas "
            "concretas. Si el lead pide cita, dile que un agente le llamará "
            "en las próximas horas para cuadrar la hora."
        )
    text = (message or "").lower()
    if not _SCHEDULING_RE.search(text) and not any(
        phrase in text for phrase in _SCHEDULING_PHRASES
    ):
        return ""
    from datetime import timedelta

    from app.api.v1.visits import _busy_starts
    from app.services.calendar_cal import UnusableTimezone, list_available_slots
    from app.services.timezones import resolve_zone

    now = datetime.now(UTC)
    try:
        # The agency's own diary, not just Cal.com's: a visit entered by hand in
        # the dashboard exists only in `visits`, and offering that hour sends a
        # realtor to two houses.
        busy = await _busy_starts(db, since=now, until=now + timedelta(days=7))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read booked visits for the reply: %s", exc)
        busy = set()

    from app.services.agent_calendar import activity_for_lead, pick_agent_safely

    # Never lets agent scheduling cost a reply — and now for real. The first
    # version ran `pick_agent` on this session inside a bare except: a failed
    # lookup aborted the shared transaction, the fallback "returned", and the
    # message writes further down died with InFailedSQLTransactionError — the
    # lead got no reply at all, precisely in the deploy-before-migrate window
    # the fallback exists for. `pick_agent_safely` fails on its own session.
    target = await pick_agent_safely(activity_for_lead(lead))
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
                # The hours this agent declared for THIS kind of appointment.
                # This lane was the one the first draft of the plan forgot: with
                # only the voice lane converted, the chat would have gone on
                # offering the agency-wide default while the phone offered the
                # agent's real hours — two answers to the same question.
                event_type_id=target.event_type_id,
            ),
            timeout=_SLOTS_BUDGET_SECONDS,
        )
    except UnusableTimezone as exc:
        # Not a blip: the agency's own timezone is unusable, so every hour we
        # could offer would be wrong by its offset. The lead gets a reply with
        # no hours in it rather than hours it cannot keep — a person who is
        # asked to wait is better served than one who is given the wrong
        # Tuesday. Logged at error, because this is a config fault somebody has
        # to fix, not weather.
        log.error("refusing to offer hours for org %s: %s", agent_cfg.org_id, exc)
        return ""
    except Exception as exc:  # noqa: BLE001 — a calendar blip must not cost a reply
        log.warning("could not read availability for the reply: %s", exc)
        return ""
    if not slots:
        return ""
    # No UTC fallback. `list_available_slots` has already refused an unusable
    # zone above, so this cannot normally be None — but the previous version
    # substituted UTC here as well, which meant the SAME wrong hours could be
    # printed even on a path where generation had succeeded in a different
    # zone. Two silent substitutions of the same value is how it survived.
    zone = resolve_zone(agent_cfg.timezone or "UTC")
    if zone is None:
        log.error(
            "office timezone %r is unusable; offering no hours for org %s",
            agent_cfg.timezone,
            agent_cfg.org_id,
        )
        return ""
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
# WhatsApp accepts 4096. Applying the SMS floor to it amputated ordinary
# replies on the product's main channel for no reason.
_CHANNEL_MAX_CHARS = {"sms": _SMS_MAX_CHARS, "whatsapp": 4000}



@dataclass(frozen=True)
class OfferedListing:
    """One listing put in front of the model this turn, and who to credit."""

    broker: str
    title: str | None
    address: str | None
    price: object



def _price_patterns(price: object) -> list[re.Pattern[str]]:
    """How this listing's price might be written, matched as a whole number.

    Substring matching was wrong in both directions at once. "1k" — the form
    for a $1,200 rental — is inside "451k", so an unrelated sale credited the
    rental's broker; and "1,200" is inside "1,200 sq ft", so a floor area did
    too. Word boundaries fix the first. For the second, a number small enough
    to be a room count, a year or a square footage has to arrive with a
    currency marker before it; a six-figure number does not, because nothing
    else in a property conversation looks like that.
    """
    try:
        whole = int(float(price))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        # OverflowError included deliberately: a Decimal("Infinity") is a legal
        # numeric column value, and this runs after the reply is generated but
        # before it is saved — an exception here loses the answer entirely.
        return []
    if whole <= 0:
        return []

    forms = {str(whole), f"{whole:,}", f"{whole:,}".replace(",", ".")}
    if whole >= 1000:
        forms.add(f"{whole // 1000}k")
    needs_currency = whole < 10_000
    prefix = r"[$€]\s?" if needs_currency else r"[$€]?\s?"
    return [
        # The boundaries exclude a longer number on either side — "1k" inside
        # "451k", "650" inside "1650" — but not ordinary punctuation, which the
        # first attempt did: "$650k," failed on its own comma.
        re.compile(
            rf"(?<!\d)(?<!\d[.,]){prefix}{re.escape(form)}(?!\d)(?![.,]\d)",
            re.IGNORECASE,
        )
        for form in forms
    ]


def _reply_shows(reply: str, listing: OfferedListing) -> bool:
    """Whether this reply puts THIS listing's details in front of the consumer.

    Three signals: the full title, the full address, or this listing's own
    price. A listing that offers none of them — a short generated title, no
    address, no price ("price on request" is a real state) — counts as shown,
    because a listing that can never satisfy the test can never be credited,
    and silence is the failure that costs a licence.
    """
    haystack = reply.lower()
    usable = False
    for value in (listing.title, listing.address):
        if value and len(value.strip()) >= 8:
            usable = True
            if value.strip().lower() in haystack:
                return True
    patterns = _price_patterns(listing.price)
    usable = usable or bool(patterns)
    if any(pattern.search(reply) for pattern in patterns):
        return True
    return not usable


def _with_broker_credits(
    reply: str, offered: list[OfferedListing], channel: str
) -> str:
    """Append the listing brokers' credits to the message that reaches the lead.

    Colorado requires the broker to be named wherever a listing's details reach
    a consumer. Which of the offered listings the model actually used is not
    knowable from the text, so once the reply shows any of them, all of their
    brokers are credited: over-crediting is a redundant line, under-crediting
    is a licence problem.
    """
    shown = [item for item in offered if item.broker and _reply_shows(reply, item)]
    lines: list[str] = []
    for item in offered if shown else []:
        if not item.broker:
            continue
        line = f"Cortesía de {item.broker}"
        # This exact credit, not the bare name — a listing titled "Coldwell
        # Banker Tower" otherwise suppressed Coldwell Banker's credit.
        if line.lower() in reply.lower() or line in lines:
            continue
        lines.append(line)

    footer = ""
    if lines:
        footer = "\n\n" + " · ".join(lines)
        budget = _CHANNEL_MAX_CHARS.get(channel, 0) // 2
        if budget:
            while len(lines) > 1 and len(footer) > budget:
                lines.pop()
                footer = "\n\n" + " · ".join(lines) + _AND_OTHERS
            if len(footer) > budget:
                footer = _COLLECTIVE_CREDIT
    return _fit_to_channel(reply, footer, channel)


# Bilingual, because the product is. A lead writing in English should not be
# handed Spanish legalese, and the credit has to survive either way.
_AND_OTHERS = " · y otros corredores listantes / and other listing brokers"
_COLLECTIVE_CREDIT = (
    "\n\nCortesía de los corredores listantes / Courtesy of the listing brokers"
)


def _fit_to_channel(reply: str, footer: str, channel: str) -> str:
    """The message, with its footer, inside what the channel will accept.

    The cap used to live inside the credit branch, so a reply that earned no
    footer was never measured — and a 2200-character SMS is rejected by Twilio
    and then retried five times to the same rejection.
    """
    limit = _CHANNEL_MAX_CHARS.get(channel)
    if limit is None:
        return reply.rstrip() + footer if footer else reply
    room = limit - len(footer)
    body = reply if len(reply) <= room else reply[: max(0, room - 1)].rstrip() + "…"
    return body.rstrip() + footer if footer else body



def history_content(message: "Message") -> str:
    """What the model should read back for one past turn.

    Our own messages lose their attribution footer: it lives in `content`, so
    without this the model reads three credit lines back for every past turn
    and repeats them. A lead's message is never touched — someone who pastes a
    listing block and asks their question underneath would have had the
    question deleted, and the agent would answer the turn before.
    """
    if message.direction == MessageDirection.OUTBOUND:
        return strip_broker_credits(message.content)
    return message.content


def strip_broker_credits(content: str) -> str:
    """The message without its attribution footer.

    From the end, and only when what follows is nothing but credit lines. The
    first version split on the first occurrence — and the listing block handed
    to the model already contains "Cortesía de", so the model echoes it, and a
    bulleted reply puts one mid-body. Everything after it, including the actual
    question, vanished from the history the model reads next turn.
    """
    marker = "\n\nCortesía de"
    head, found, tail = content.rpartition(marker)
    if not found:
        return content
    trailing = (found + tail).strip()
    # A footer is one line of credits. Anything with a paragraph break in it is
    # the body of the message, not the footer.
    if "\n\n" in trailing[2:]:
        return content
    return head.rstrip() or content


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


async def _optout_language(
    lead: Lead, conv: Conversation, parsed: ParsedMessage, db: AsyncSession
) -> str:
    """Which language to confirm an opt-out in.

    Detecting on the message itself is useless here: "STOP" is the same word in
    both languages, and it is the word most people send. So look back at what
    this person has actually written to us, newest first, and fall back to the
    keyword itself — "baja" and "cancelar" are Spanish whoever types them.
    """
    rows = await db.execute(
        select(Message.content)
        .where(
            Message.conversation_id == conv.id,
            Message.direction == MessageDirection.INBOUND,
        )
        .order_by(Message.created_at.desc())
        .limit(6)
    )
    for content in rows.scalars():
        if opt_out_keyword(content, parsed.channel) or opt_in_keyword(
            content, parsed.channel
        ):
            continue  # a keyword tells us nothing about their language
        detected = detect_language(content)
        if detected:
            return pick_supported_language(detected, ("en", "es"))
    return pick_supported_language(detect_language(parsed.content or ""), ("en", "es"))


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
        lead.name = storable_text(parsed.from_name, "name")

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

    # ── 4b. Revocation ─────────────────────────────────────────────────
    # Before the takeover check, before the history, before the model. A lead
    # who wrote STOP gets exactly one confirmation and nothing else, ever —
    # generating a helpful reply to somebody who just asked to be left alone is
    # the automated message the revocation forbids, and it would go out with
    # the model's own wording rather than a confirmation.
    #
    # The dispatch is direct rather than through the retry queue: a
    # confirmation that arrives late, or twice, is worse than one that does not
    # arrive at all.
    stop_word = opt_out_keyword(parsed.content, parsed.channel)
    start_word = opt_in_keyword(parsed.content, parsed.channel)
    if stop_word or (start_word and lead.opted_out_at is not None):
        # Same language machinery the reply path uses, but keyed on the
        # conversation's history rather than on the one-word message — "STOP"
        # detects as English no matter who sends it, and confirming a Spanish
        # speaker's opt-out in English is the last thing they hear from us.
        target_lang = await _optout_language(lead, conv, parsed, db)
        if stop_word:
            # First STOP wins the date. A second one used to reset it, and the
            # date the agency was first on notice is the difference between one
            # TCPA violation and thirty. The confirmation is still sent for
            # every STOP — that is what the carriers do and what the person is
            # entitled to — but the record of when they first said it stands.
            if lead.opted_out_at is None:
                lead.opted_out_at = datetime.now(UTC)
                lead.opted_out_channel = parsed.channel
                lead.opted_out_keyword = stop_word[:40]
            text = CONFIRMATION.get(target_lang) or CONFIRMATION["en"]
        else:
            lead.opted_out_at = None
            lead.opted_out_channel = None
            lead.opted_out_keyword = None
            text = RESUMED.get(target_lang) or RESUMED["en"]

        ack = Message(
            conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND,
            sender=MessageSender.AGENT,
            content=text,
            delivery_status=MessageStatus.PENDING,
        )
        db.add(ack)
        await db.flush()
        try:
            external_id, _ = await _dispatch_send(
                parsed.channel, to=parsed.from_identifier, text=text
            )
            ack.external_id = external_id
            ack.delivery_status = MessageStatus.SENT
        except Exception as exc:  # noqa: BLE001
            log.error("Opt-out confirmation failed for lead %d: %s", lead.id, exc)
            if lead.opted_out_at is None:
                # They asked to come back. This is the one confirmation somebody
                # is actually waiting for, they have consented by definition, and
                # dropping it leaves them believing they resubscribed to silence.
                schedule_retry(ack, str(exc))
            else:
                # Not retried on purpose. The opt-out itself is already recorded
                # and honoured; a failed confirmation must never leave the door
                # open for the sweep to send anything else.
                ack.delivery_status = MessageStatus.FAILED
        await db.commit()
        log.info(
            "Lead %d %s on %s via %r",
            lead.id,
            "opted out" if stop_word else "opted back in",
            parsed.channel,
            stop_word or start_word,
        )
        return {
            "status": "opted_out" if stop_word else "opted_in",
            "lead_id": lead.id,
            "inbound_id": inbound.id,
            "keyword": stop_word or start_word,
        }

    # ── 4c. Still opted out ────────────────────────────────────────────
    # The block above catches the message that CONTAINS the stop word. This
    # catches every message after it. Without it the revocation lasted exactly
    # one turn: the lead texted STOP, got the confirmation, then wrote anything
    # at all the next day — "what about Wash Park?" — and the model answered
    # with a full automated reply. The comment above this code claimed "one
    # confirmation and nothing else, ever"; it was true only of that one turn.
    #
    # Their message is still stored and still lands in the Inbox as pending, so
    # nothing is lost — a person answers instead of the machine, which is
    # exactly what "no automated messages" means. Only START lifts it.
    if lead.opted_out_at is not None:
        await rescore_lead(lead, db, commit=False)
        await db.commit()
        log.info(
            "Lead %d opted out on %s — storing the message for a human, no AI reply",
            lead.id,
            lead.opted_out_at.isoformat(),
        )
        return {
            "status": "opted_out_no_reply",
            "lead_id": lead.id,
            "inbound_id": inbound.id,
        }

    # ── 5. Human takeover check ────────────────────────────────────────
    if lead.human_takeover:
        await rescore_lead(lead, db, commit=False)
        await db.commit()
        log.info("Lead %d on human_takeover — skipping AI reply", lead.id)
        return {"status": "human_takeover", "lead_id": lead.id, "inbound_id": inbound.id}

    # ── 6. Build history for LLM ───────────────────────────────────────
    hist_row = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.internal.is_(False))
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
            "content": history_content(m),
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
        # The budgets come out of a language model reading free text, and they
        # are written once and never revisited (`is None` below), so a pair the
        # wrong way round sticks to the lead for ever: it matches no listing at
        # all and `/matches` reports that as "nothing available". "under 900k,
        # at least 100" is enough to produce it. The database refuses the pair
        # outright, which would abort this whole inbound message — so keep the
        # extraction and drop the half that makes it impossible, rather than
        # losing a customer's message to a bad guess.
        # Whatever the model understood, made safe for the table. Both are
        # dropped rather than refused: a rejected write aborts the transaction
        # holding the customer's message, and the provider replays it, so every
        # retry fails the same way and the message is gone for good.
        e = e.model_copy(
            update={
                "budget_min": storable_budget(e.budget_min),
                "budget_max": storable_budget(e.budget_max),
            }
        )

        lead.budget_min, lead.budget_max = merge_budget(
            (lead.budget_min, lead.budget_max), (e.budget_min, e.budget_max)
        )
        # Trimmed to the column width, for the same reason as the budgets:
        # `urgency` is 40 characters and "as soon as possible, ideally within
        # the next thirty days" is 52. Postgres does not truncate, it refuses —
        # and the refusal takes the customer's message with it.
        if e.property_type and not lead.property_type:
            lead.property_type = storable_text(e.property_type, "property_type")
        if e.urgency and not lead.urgency:
            lead.urgency = storable_text(e.urgency, "urgency")

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
    system_prompt += await _real_slots_note(agent_cfg, inbound.content, db, lead)

    # Phase 10: if the lead is property-shopping and we know the zone, give the
    # LLM the REAL matching listings so it can offer them (and never invent any).
    # Collected here and appended to the reply itself further down. Putting the
    # credit only in the system prompt made a licence obligation depend on the
    # model choosing to repeat it, which it will not always do.
    offered_listings: list[OfferedListing] = []
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
                    offered_listings.append(
                        OfferedListing(broker, p.title, p.address, p.price)
                    )
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

    # Fair Housing, on the text that actually leaves — after the broker credit,
    # because IDX attribution is reproduced verbatim by legal obligation and a
    # brokerage called "Perfect for Families Realty" would otherwise walk
    # straight past a filter pointed at `reply.text`.
    #
    # It RECORDS, it does not block: the lead gets an answer at the speed they
    # asked for it, and `services/fair_housing_watch.py` tells the operator out
    # of band. Read `find_violations` before trusting this: it matches listed
    # phrases, not paraphrase. Measured against the live module, "It's a safe
    # neighborhood with good schools" scores 2 and "You'll love how safe this
    # area feels for raising kids" scores 0. This is a floor, not a ceiling.
    flags = find_violations(reply_text, target_lang)
    if flags:
        log.warning(
            "Fair Housing: outbound reply for lead %d carries %d flagged "
            "phrase(s): %s",
            lead.id,
            len(flags),
            sorted({f["category"] for f in flags}),
        )

    outbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        sender=MessageSender.AGENT,
        content=reply_text,
        delivery_status=MessageStatus.PENDING,
        llm_provider=reply.provider,
        llm_model=reply.model,
        subject=reply_subject,
        # `[]`, not NULL, when it came back clean. The two are different claims
        # and the column is a compliance artifact: NULL means "never screened"
        # (every row written before v0.56, plus the inbound side and the lanes
        # that do not run this filter), `[]` means "screened, nothing found".
        # Collapsing them into NULL to save a few bytes would make the honest
        # answer to "was this reply checked?" unavailable forever.
        fair_housing_flags=flags,
    )
    db.add(outbound)
    await db.flush()
    # Held as a plain int for the handlers below. Once a savepoint rolls back,
    # `outbound.id` is an expired attribute, and reading one inside an `except`
    # is a synchronous lazy load that raises MissingGreenlet out of every
    # handler in this function.
    outbound_id = outbound.id

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
            # A savepoint rollback EXPIRES every object it touched, so reading
            # `outbound.id` here was a synchronous lazy load inside async code.
            # It raised MissingGreenlet — not an IntegrityError — so it escaped
            # to the outer handler below, whose first act was to read
            # `outbound.id` again. The recovery written to save the turn was
            # what killed it, and by then the reply had already gone out over
            # the wire: the lead was answered and we kept no record of it.
            #
            # Two guards, and measured rather than assumed: EITHER one alone
            # makes the test pass, so neither is load-bearing on its own. Both
            # are kept because they cover different ground and each costs a
            # line — `refresh` restores the object for everything after this
            # block (the assignments, `rescore_lead`, the commit and the final
            # log line, all of which read it), while `outbound_id` also serves
            # the outer `except Exception`, which catches states this savepoint
            # never saw. Saying they are both required would be the kind of
            # comment that defends a choice with an argument that is not true.
            #
            # `followups.py:423-427` learned this first, in the same words.
            await db.refresh(outbound)
            log.warning(
                "Duplicate provider id %s on outbound msg %d; keeping the turn "
                "and leaving the id unset",
                external_id, outbound_id,
            )
            outbound.external_id = None
            outbound.delivery_status = MessageStatus.SENT
    except Exception as exc:  # noqa: BLE001
        log.error(
            "Channel %s send failed for outbound msg %d: %s",
            parsed.channel, outbound_id, exc,
        )
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

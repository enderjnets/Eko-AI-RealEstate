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

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.i18n import detect_language, language_instruction, pick_supported_language
from app.services.llm import LLMUnavailable, generate_reply
from app.services.scoring import rescore_lead
from app.services.whatsapp import send_text_message as whatsapp_send

log = logging.getLogger(__name__)


async def _dispatch_send(
    channel: str,
    *,
    to: str,
    text: str,
    subject: str | None = None,
    in_reply_to: str | None = None,
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
            "content": m.content,
        }
        for m in history
    ]

    # Language steering from the latest inbound.
    settings_row = await db.execute(select(AgentSettings).where(AgentSettings.id == 1))
    agent_cfg = settings_row.scalar_one_or_none()
    supported = (agent_cfg.languages if agent_cfg else ["es", "en"]) or ["es", "en"]
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


async def handle_inbound_message(parsed: ParsedMessage, db: AsyncSession) -> dict[str, int | str | bool]:
    """Process one inbound message (any channel) end-to-end. Returns a small status dict.

    Caller (the FastAPI route) is responsible for committing the session.
    Idempotency: UNIQUE constraint on Message.external_id catches webhook retries.
    Lead lookup is by `phone` for whatsapp/sms/voice, by a synthetic key
    (phone column doubles as identifier) for email — the column accepts any
    string up to 32 chars; we store the email address there too.
    """
    # ── 1. Lead upsert ──────────────────────────────────────────────────
    lead_row = await db.execute(select(Lead).where(Lead.phone == parsed.from_identifier))
    lead = lead_row.scalar_one_or_none()
    is_new_lead = lead is None
    if lead is None:
        lead = Lead(phone=parsed.from_identifier, name=parsed.from_name)
        db.add(lead)
        await db.flush()
        log.info("Created lead id=%d channel=%s identifier=%s", lead.id, parsed.channel, lead.phone)
    elif parsed.from_name and not lead.name:
        lead.name = parsed.from_name

    # ── 2. Active conversation ─────────────────────────────────────────
    # Multichannel: one active conversation per (lead, channel). A lead that
    # writes both email AND whatsapp gets TWO active conversations.
    conv_row = await db.execute(
        select(Conversation)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.channel == parsed.channel,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    conv = conv_row.scalar_one_or_none()
    if conv is None:
        conv = Conversation(
            lead_id=lead.id,
            channel=parsed.channel,
            status=ConversationStatus.ACTIVE,
            external_thread_id=parsed.thread_id,
        )
        db.add(conv)
        await db.flush()
    elif parsed.thread_id and not conv.external_thread_id:
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
    db.add(inbound)
    lead.last_message_at = datetime.now(UTC)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        log.info("Race-condition idempotent skip for external_id=%s", parsed.external_id)
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
            "content": m.content,
        }
        for m in history
    ]

    # ── 7. Language detection + intent classification ─────────────────
    # Detect on the latest inbound only (avoid letting historical AI replies
    # bias the result). Pick the closest supported language from agent settings.
    settings_row_pre = await db.execute(select(AgentSettings).where(AgentSettings.id == 1))
    agent_cfg = settings_row_pre.scalar_one_or_none()
    supported_languages = (agent_cfg.languages if agent_cfg else ["es", "en"]) or ["es", "en"]
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
        agent_cfg = AgentSettings(id=1)
        db.add(agent_cfg)
        await db.flush()

    # Persona is authored in Spanish; the language steering line tells the LLM
    # which language to actually answer in (detected from the inbound message).
    system_prompt = agent_cfg.agent_persona.replace("{agency_name}", agent_cfg.agency_name)
    system_prompt += language_instruction(target_lang, persona_locale="es")

    # Phase 10: if the lead is property-shopping and we know the zone, give the
    # LLM the REAL matching listings so it can offer them (and never invent any).
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
                lines.append(
                    f"- {p.title} — {price}{(' · ' + specs) if specs else ''}"
                    f"{(' · ' + p.address) if p.address else ''}{(' · ' + p.url) if p.url else ''}"
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
        await rescore_lead(lead, db, commit=False)
        await db.commit()
        return {
            "status": "llm_unavailable",
            "lead_id": lead.id,
            "inbound_id": inbound.id,
            "is_new_lead": is_new_lead,
        }

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

    outbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        sender=MessageSender.AGENT,
        content=reply.text,
        delivery_status=MessageStatus.PENDING,
        llm_provider=reply.provider,
        llm_model=reply.model,
        subject=reply_subject,
    )
    db.add(outbound)
    await db.flush()

    # ── 10. Dispatch send through the right channel adapter ──────────
    try:
        external_id, _ = await _dispatch_send(
            parsed.channel,
            to=parsed.from_identifier,
            text=reply.text,
            subject=reply_subject,
            in_reply_to=parsed.external_id if parsed.channel == "email" else None,
        )
        outbound.external_id = external_id
        outbound.delivery_status = MessageStatus.SENT
    except Exception as exc:  # noqa: BLE001
        log.error("Channel %s send failed for outbound msg %d: %s", parsed.channel, outbound.id, exc)
        outbound.delivery_status = MessageStatus.FAILED

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

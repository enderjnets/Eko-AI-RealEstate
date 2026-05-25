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
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentSettings,
    Conversation,
    ConversationStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.services._common import ParsedMessage
from app.services.classifier import classify_intent
from app.services.i18n import detect_language, language_instruction, pick_supported_language
from app.services.llm import LLMUnavailable, generate_reply
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

    raise ValueError(f"Unsupported channel for outbound send: {channel}")

# How many recent messages we feed back into the LLM as context. Plenty for
# WhatsApp where conversations rarely exceed 30 turns; safely under the token
# budget of both Kimi (262K) and MiniMax (128K).
MAX_HISTORY_TURNS = 20

# Don't overwrite existing lead.intent unless the classifier is confident.
INTENT_CONFIDENCE_THRESHOLD = 0.55


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
    lead.last_message_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        log.info("Race-condition idempotent skip for external_id=%s", parsed.external_id)
        return {"status": "duplicate", "lead_id": lead.id, "skipped": True}

    # ── 5. Human takeover check ────────────────────────────────────────
    if lead.human_takeover:
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

    try:
        reply = await generate_reply(messages=llm_messages, system=system_prompt, max_tokens=400)
    except LLMUnavailable as exc:
        log.error("All LLMs failed for lead %d: %s", lead.id, exc)
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

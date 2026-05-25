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
from app.services.classifier import classify_intent
from app.services.llm import LLMUnavailable, generate_reply
from app.services.whatsapp import ParsedMessage, send_text_message

log = logging.getLogger(__name__)

# How many recent messages we feed back into the LLM as context. Plenty for
# WhatsApp where conversations rarely exceed 30 turns; safely under the token
# budget of both Kimi (262K) and MiniMax (128K).
MAX_HISTORY_TURNS = 20

# Don't overwrite existing lead.intent unless the classifier is confident.
INTENT_CONFIDENCE_THRESHOLD = 0.55


async def handle_inbound_message(parsed: ParsedMessage, db: AsyncSession) -> dict[str, int | str | bool]:
    """Process one inbound WhatsApp message end-to-end. Returns a small status dict.

    Caller (the FastAPI route) is responsible for committing the session.
    This function uses `flush()` to keep DB rows live across steps but defers
    final commit so the route can return 200 to Meta even if commit fails — Meta
    will retry, idempotency check on wa_message_id catches the duplicate.
    """
    # ── 1. Lead upsert ──────────────────────────────────────────────────
    lead_row = await db.execute(select(Lead).where(Lead.phone == parsed.from_phone))
    lead = lead_row.scalar_one_or_none()
    is_new_lead = lead is None
    if lead is None:
        lead = Lead(phone=parsed.from_phone, name=parsed.from_name)
        db.add(lead)
        await db.flush()
        log.info("Created lead id=%d phone=%s", lead.id, lead.phone)
    elif parsed.from_name and not lead.name:
        lead.name = parsed.from_name

    # ── 2. Active conversation ─────────────────────────────────────────
    conv_row = await db.execute(
        select(Conversation)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    conv = conv_row.scalar_one_or_none()
    if conv is None:
        conv = Conversation(lead_id=lead.id, channel="whatsapp", status=ConversationStatus.ACTIVE)
        db.add(conv)
        await db.flush()

    # ── 3. Idempotency check ───────────────────────────────────────────
    dup_row = await db.execute(
        select(Message).where(Message.wa_message_id == parsed.wa_message_id)
    )
    if dup_row.scalar_one_or_none() is not None:
        log.info(
            "Duplicate webhook for wa_message_id=%s — idempotent skip",
            parsed.wa_message_id,
        )
        return {"status": "duplicate", "lead_id": lead.id, "skipped": True}

    # ── 4. Persist inbound ─────────────────────────────────────────────
    inbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.INBOUND,
        sender=MessageSender.LEAD,
        content=parsed.text or "",
        wa_message_id=parsed.wa_message_id,
        wa_status=MessageStatus.DELIVERED,
    )
    db.add(inbound)
    lead.last_message_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError:
        # Race: a concurrent webhook just inserted this message_id. Roll back
        # and exit idempotently.
        await db.rollback()
        log.info("Race-condition idempotent skip for wa_message_id=%s", parsed.wa_message_id)
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

    # ── 7. Intent classification ──────────────────────────────────────
    intent_result = await classify_intent(llm_messages)
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
    settings_row = await db.execute(select(AgentSettings).where(AgentSettings.id == 1))
    agent_cfg = settings_row.scalar_one_or_none()
    if agent_cfg is None:
        # Bootstrap the singleton on first real interaction.
        agent_cfg = AgentSettings(id=1)
        db.add(agent_cfg)
        await db.flush()

    system_prompt = agent_cfg.agent_persona.replace("{agency_name}", agent_cfg.agency_name)

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
    outbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        sender=MessageSender.AGENT,
        content=reply.text,
        wa_status=MessageStatus.PENDING,
        llm_provider=reply.provider,
        llm_model=reply.model,
    )
    db.add(outbound)
    await db.flush()

    # ── 10. Send via WhatsApp ─────────────────────────────────────────
    try:
        send_result = await send_text_message(parsed.from_phone, reply.text)
        outbound.wa_message_id = send_result.get("messages", [{}])[0].get("id")
        outbound.wa_status = MessageStatus.SENT
    except Exception as exc:  # noqa: BLE001
        log.error("WhatsApp send failed for outbound msg %d: %s", outbound.id, exc)
        outbound.wa_status = MessageStatus.FAILED

    await db.commit()
    log.info(
        "Turn done: lead=%d inbound=%d outbound=%d intent=%s provider=%s status=%s",
        lead.id, inbound.id, outbound.id,
        lead.intent.value if lead.intent else "?",
        reply.provider,
        outbound.wa_status.value,
    )
    return {
        "status": "ok",
        "lead_id": lead.id,
        "is_new_lead": is_new_lead,
        "inbound_id": inbound.id,
        "outbound_id": outbound.id,
        "outbound_status": outbound.wa_status.value,
        "llm_provider": reply.provider,
    }

"""Conversations API — fetch full chat history for a lead. Phase 2 will add
write endpoints (manual takeover toggle, human reply override)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)

router = APIRouter()


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: MessageDirection
    sender: MessageSender
    content: str
    wa_message_id: str | None
    wa_status: MessageStatus
    llm_provider: str | None
    llm_model: str | None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    channel: str
    status: ConversationStatus
    summary: str | None
    started_at: datetime
    last_at: datetime
    messages: list[MessageOut]


@router.get("/{lead_id}", response_model=ConversationOut)
async def get_conversation_for_lead(
    lead_id: int, db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    conv = (
        await db.execute(
            select(Conversation)
            .where(Conversation.lead_id == lead_id)
            .order_by(Conversation.last_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="No conversation found for this lead")

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()

    return ConversationOut(
        id=conv.id,
        lead_id=conv.lead_id,
        channel=conv.channel,
        status=conv.status,
        summary=conv.summary,
        started_at=conv.started_at,
        last_at=conv.last_at,
        messages=[MessageOut.model_validate(m) for m in msgs],
    )

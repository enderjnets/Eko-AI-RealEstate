"""Conversations API — chat history for a lead.

Two read shapes:
  - GET /{lead_id}           → the single most-recently-active conversation (legacy).
  - GET /{lead_id}/timeline  → a merged, time-ordered timeline across ALL of the
                               lead's conversations (every channel), each message
                               carrying its own channel. Powers the unified
                               per-lead view + multichannel composer.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

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
    external_id: str | None
    delivery_status: MessageStatus
    subject: str | None
    # In the lead's thread but never said to them — today, the copy of an
    # appointment invitation that went to the agency. Exposed so the panel can
    # mark it as such: an unmarked internal note reads as something the client
    # received, and a realtor would answer accordingly.
    internal: bool = False
    # Channel this message was sent/received on (from its Conversation). Carried
    # per-message so a merged multichannel timeline can icon each bubble.
    channel: str = ""
    llm_provider: str | None
    fair_housing_flags: list[dict[str, str]] | None
    llm_model: str | None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    channel: str
    external_thread_id: str | None
    status: ConversationStatus
    summary: str | None
    started_at: datetime
    last_at: datetime
    messages: list[MessageOut]


class ConversationSummaryOut(BaseModel):
    id: int
    channel: str
    status: ConversationStatus
    external_thread_id: str | None
    started_at: datetime
    last_at: datetime
    message_count: int


class TimelineOut(BaseModel):
    lead_id: int
    messages: list[MessageOut]  # flat, time-ordered ASC across all conversations
    conversations: list[ConversationSummaryOut]  # per-channel summaries
    channels: list[str]  # distinct channels present, ordered by recency
    primary_channel: str | None  # most-recently-active channel → composer default
    primary_conversation_id: int | None


def _message_out(m: Message, channel: str) -> MessageOut:
    return MessageOut(
        id=m.id,
        direction=m.direction,
        sender=m.sender,
        content=m.content,
        external_id=m.external_id,
        delivery_status=m.delivery_status,
        subject=m.subject,
        internal=m.internal,
        channel=channel,
        llm_provider=m.llm_provider,
        fair_housing_flags=m.fair_housing_flags,
        llm_model=m.llm_model,
        created_at=m.created_at,
    )


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
            # Tie-broken by id, like the thread endpoint below, and for a
            # reason that is not hypothetical: a voice call writes its WHOLE
            # transcript at hang-up, so its turns share one `created_at` to the
            # microsecond. One real call left 27 rows on 2 timestamps and
            # Postgres returned them in whatever order it liked — the realtor
            # opened the file and read the conversation scrambled, with the
            # answer above the question.
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).scalars().all()

    return ConversationOut(
        id=conv.id,
        lead_id=conv.lead_id,
        channel=conv.channel,
        external_thread_id=conv.external_thread_id,
        status=conv.status,
        summary=conv.summary,
        started_at=conv.started_at,
        last_at=conv.last_at,
        messages=[_message_out(m, conv.channel) for m in msgs],
    )


@router.get("/{lead_id}/timeline", response_model=TimelineOut)
async def get_timeline_for_lead(
    lead_id: int, db: AsyncSession = Depends(get_db)
) -> TimelineOut:
    """Merged, time-ordered timeline across all of the lead's conversations.

    Returns 200 with empty arrays when the lead has no conversations yet, so the
    UI can render an empty thread and still offer the composer to start one.
    """
    # All messages across every conversation of the lead, each tagged with its
    # conversation's channel. One JOINed query — no per-message lookups.
    rows = (
        await db.execute(
            select(Message, Conversation.channel)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id == lead_id)
            # Message.conversation is lazy="joined"; suppress the eager join — we
            # already have the channel from the explicit JOIN above.
            .options(lazyload(Message.conversation))
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()
    messages = [_message_out(m, channel) for (m, channel) in rows]

    # Per-conversation summaries (with message counts), ordered by recency.
    conv_rows = (
        await db.execute(
            select(Conversation, func.count(Message.id))
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id == lead_id)
            # Conversation.lead is lazy="joined" + messages lazy="selectin";
            # suppress both so GROUP BY conversations.id is valid (no extra lead
            # columns in the SELECT) and we don't fire a needless selectin query.
            .options(lazyload(Conversation.lead), lazyload(Conversation.messages))
            .group_by(Conversation.id)
            .order_by(Conversation.last_at.desc())
        )
    ).all()
    conversations = [
        ConversationSummaryOut(
            id=c.id,
            channel=c.channel,
            status=c.status,
            external_thread_id=c.external_thread_id,
            started_at=c.started_at,
            last_at=c.last_at,
            message_count=count,
        )
        for (c, count) in conv_rows
    ]

    # Distinct channels, most-recent first (dedupe preserving order).
    channels: list[str] = []
    for c in conversations:
        if c.channel not in channels:
            channels.append(c.channel)

    # The composer default = the most-recently-active ACTIVE conversation.
    primary = next((c for c in conversations if c.status == ConversationStatus.ACTIVE), None)

    return TimelineOut(
        lead_id=lead_id,
        messages=messages,
        conversations=conversations,
        channels=channels,
        primary_channel=primary.channel if primary else None,
        primary_conversation_id=primary.id if primary else None,
    )

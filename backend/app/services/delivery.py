"""Sending a reply again when the first attempt did not land.

Every channel adapter is one `httpx` POST followed by `raise_for_status()`. A
Meta 503, a Twilio 429, a Resend timeout — any of them stamped the message
FAILED and that was the end of it. Nothing anywhere queried for messages left
PENDING or FAILED, so the AI's answer to a lead who wrote at midnight was
simply lost, and the only trace was a status column nobody watches.

This is the missing half: a sweep that picks up outbound messages that still
owe a delivery and tries them again, backing off, giving up loudly rather than
silently. It runs per organization like the other workers, so a retry is sent
with the right agency's identity.

Deliberately at-least-once, not exactly-once. The alternative — never retrying
— loses messages, and a lead receiving the same answer twice is a smaller
failure than a lead receiving nothing. What keeps duplicates rare is that the
provider's id is stamped on success and a message that has one is never picked
up again.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from app.models.message import Message, MessageDirection, MessageStatus

log = logging.getLogger(__name__)

# After this many tries the message is left FAILED for good. Five attempts over
# the schedule below spans about an hour and a half, which covers a provider
# blip and a short outage without still pestering a lead the next morning.
MAX_ATTEMPTS = 5

# Backoff per attempt number, in minutes. The first retry is quick because most
# failures are transient; the later ones are spaced so a real outage is not
# hammered.
_BACKOFF_MINUTES = (1, 5, 15, 60)

# How long a PENDING message with no schedule has to sit before it counts as
# abandoned rather than in flight. Long enough that a slow provider call is not
# raced by the sweep; short enough that a lead is not left waiting.
_ABANDONED_AFTER = timedelta(minutes=5)


def backoff_for(attempts: int) -> timedelta:
    """How long to wait before the next attempt."""
    index = min(max(attempts - 1, 0), len(_BACKOFF_MINUTES) - 1)
    return timedelta(minutes=_BACKOFF_MINUTES[index])


def schedule_retry(message: Message, error: str) -> None:
    """Record a failed send and when to try it again.

    Called from the send path itself, so a message is retryable the moment it
    fails rather than waiting for a sweep to notice it is stuck.
    """
    message.delivery_status = MessageStatus.FAILED
    message.send_attempts = (message.send_attempts or 0) + 1
    message.last_error = (error or "")[:500]
    if message.send_attempts >= MAX_ATTEMPTS:
        message.next_attempt_at = None
        log.error(
            "message %s gave up after %d attempts: %s",
            message.id,
            message.send_attempts,
            message.last_error,
        )
        return
    message.next_attempt_at = datetime.now(UTC) + backoff_for(message.send_attempts)


async def retry_pending_sends(db: AsyncSession, *, limit: int = 20) -> dict[str, int]:
    """Try again on outbound messages that still owe a delivery.

    Runs inside one organization's scope — the caller supplies that — so the
    retry goes out with the same agency identity the original would have used.
    """
    from app.services.conversation import _dispatch_send

    now = datetime.now(UTC)
    due = (
        (
            await db.execute(
                select(Message)
                # The model eager-loads its lead and conversation, and Postgres
                # refuses FOR UPDATE on the nullable side of an outer join.
                # Nothing here needs them: the recipient is looked up per row.
                .options(lazyload("*"))
                .where(
                    Message.direction == MessageDirection.OUTBOUND,
                    Message.delivery_status.in_(
                        [MessageStatus.PENDING, MessageStatus.FAILED]
                    ),
                    Message.external_id.is_(None),
                    # Either scheduled and due, or PENDING with nothing
                    # scheduled at all — which is what a worker killed between
                    # the insert and the POST leaves behind, and the case the
                    # sweep was written for. `next_attempt_at` is only ever
                    # written by `schedule_retry`, so requiring it excluded
                    # exactly those rows.
                    or_(
                        Message.next_attempt_at <= now,
                        and_(
                            Message.next_attempt_at.is_(None),
                            Message.delivery_status == MessageStatus.PENDING,
                            Message.created_at < now - _ABANDONED_AFTER,
                        ),
                    ),
                    Message.send_attempts < MAX_ATTEMPTS,
                )
                .order_by(Message.next_attempt_at)
                .limit(limit)
                # Skip anything another worker holds rather than queueing behind
                # it; the next tick will find whatever was skipped.
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    sent = failed = 0
    for message in due:
        recipient, channel, in_reply_to = await _recipient_of(message, db)
        if not recipient or not channel:
            # Nothing to send to. Stop retrying rather than looping forever on a
            # row we cannot address.
            message.next_attempt_at = None
            message.last_error = "no recipient for this message"
            continue
        try:
            external_id, _ = await _dispatch_send(
                channel,
                to=recipient,
                text=message.content,
                # The row was holding all three. Without them the retry arrived
                # as a brand-new email titled "Tu consulta", detached from the
                # thread the lead was reading.
                subject=message.subject,
                in_reply_to=in_reply_to,
                references=in_reply_to,
            )
        except Exception as exc:  # noqa: BLE001 — the point is to survive this
            schedule_retry(message, str(exc))
            await db.commit()
            failed += 1
            continue
        message.delivery_status = MessageStatus.SENT
        message.next_attempt_at = None
        message.last_error = None
        if external_id:
            # Not inside a savepoint on purpose: a collision here would mean the
            # provider handed back an id we already hold, which is worth seeing
            # rather than swallowing. The sweep is not in a request path.
            message.external_id = external_id
        sent += 1
        # Per message, deliberately. With one commit after the loop, a
        # CancelledError on the last of twenty rolled back the nineteen already
        # delivered — and the next tick sent all nineteen again.
        await db.commit()

    if sent or failed:
        log.info("delivery retry: %d sent, %d still failing", sent, failed)
    await db.commit()
    return {"sent": sent, "failed": failed}


async def _recipient_of(
    message: Message, db: AsyncSession
) -> tuple[str | None, str | None, str | None]:
    """Who this message was for, on which channel, and what it was replying to."""
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    conversation = (
        await db.execute(
            select(Conversation).where(Conversation.id == message.conversation_id)
        )
    ).scalar_one_or_none()
    if conversation is None:
        return None, None, None
    lead = (
        await db.execute(select(Lead).where(Lead.id == conversation.lead_id))
    ).scalar_one_or_none()
    if lead is None:
        return None, None, None
    channel = getattr(conversation.channel, "value", conversation.channel)
    if channel == "email":
        # 6) An address or nothing. Falling back to `lead.phone` posted a phone
        # number as a `to:` address and earned five identical 422s.
        address = lead.email or (lead.phone if "@" in (lead.phone or "") else None)
        thread = (
            (
                await db.execute(
                    select(Message.external_id)
                    .where(
                        Message.conversation_id == conversation.id,
                        Message.direction == MessageDirection.INBOUND,
                        Message.external_id.is_not(None),
                    )
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
        )
        return address, channel, thread
    return lead.phone, channel, None

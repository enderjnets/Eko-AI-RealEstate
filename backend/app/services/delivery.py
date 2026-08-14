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

from app.models.message import Message, MessageDirection, MessageSender, MessageStatus

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

    Two passes on purpose. The first reads only ids, with no lock held; the
    second locks and sends one message at a time, committing each. Locking the
    whole batch and committing per message did both things wrong at once: the
    commit released the locks on every row still waiting, so a second worker
    picked them up and the lead got the same answer twice — from the very
    commit added to stop a cancellation replaying the batch.
    """
    now = datetime.now(UTC)
    candidates = (
        (
            await db.execute(
                select(Message.id)
                .where(_still_owed(now))
                .order_by(Message.next_attempt_at.nulls_last(), Message.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    sent = failed = dropped = 0
    for message_id in candidates:
        outcome = await _retry_one(db, message_id, now)
        if outcome == "sent":
            sent += 1
        elif outcome == "failed":
            failed += 1
        elif outcome == "dropped":
            # Counted, and reported. A revoked message that vanishes from the
            # summary looks to the operator like a quiet sweep, which is the
            # one reading of "0 sent, 0 failed" that is not true.
            dropped += 1

    if sent or failed or dropped:
        log.info(
            "delivery retry: %d sent, %d still failing, %d dropped (revoked)",
            sent, failed, dropped,
        )
    return {"sent": sent, "failed": failed, "dropped": dropped}


def _still_owed(now: datetime):  # noqa: ANN201 — a SQLAlchemy clause
    """Outbound messages that have not reached a provider."""
    return and_(
        Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_status.in_([MessageStatus.PENDING, MessageStatus.FAILED]),
        Message.external_id.is_(None),
        Message.send_attempts < MAX_ATTEMPTS,
        or_(
            Message.next_attempt_at <= now,
            # PENDING with nothing scheduled is what a worker killed between
            # the insert and the POST leaves behind — the case the sweep exists
            # for, and the one `next_attempt_at IS NOT NULL` used to exclude.
            and_(
                Message.next_attempt_at.is_(None),
                Message.delivery_status == MessageStatus.PENDING,
                Message.created_at < now - _ABANDONED_AFTER,
            ),
        ),
    )


async def _retry_one(db: AsyncSession, message_id: int, now: datetime) -> str:
    """Send one message, in its own transaction, holding only its own row."""
    from app.services.conversation import _dispatch_send

    message = (
        (
            await db.execute(
                select(Message)
                # The model eager-loads its lead and conversation, and Postgres
                # refuses FOR UPDATE on the nullable side of an outer join.
                .options(lazyload("*"))
                .where(Message.id == message_id, _still_owed(now))
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .first()
    )
    if message is None:
        # Another worker took it, or it stopped qualifying between the two
        # passes. Either way it is not ours. Roll back so the session is not
        # left idle in a transaction for the rest of the batch.
        await db.rollback()
        return "skipped"

    # A revocation must reach messages that were already queued when it
    # arrived. Without this the sweep happily delivered them minutes or hours
    # after the person said STOP: the gate lived in the follow-up worker, which
    # checks BEFORE creating the row, so anything already in the queue sailed
    # past it. The consent gate belongs at the dispatch boundary too, not only
    # at the producer.
    # AGENT only. The gate's documented bound — in `may_send_automated` and in
    # docs/public-capture-form.md — is that it covers automated messages and a
    # realtor can still write personally. Dropping on `sender` alone retired a
    # human-authored message orphaned PENDING by a restart, which is precisely
    # the case this sweep exists to rescue, and it did it permanently.
    lead = (
        await _lead_of(message, db)
        if message.sender == MessageSender.AGENT
        else None
    )
    if lead is not None and lead.opted_out_at is not None:
        message.delivery_status = MessageStatus.FAILED
        message.next_attempt_at = None
        message.last_error = "lead opted out before this message could be sent"
        log.info(
            "Dropping queued message %s: lead %d opted out at %s",
            message.id,
            lead.id,
            lead.opted_out_at.isoformat(),
        )
        await db.commit()
        return "dropped"

    recipient, channel, in_reply_to = await _recipient_of(message, db)

    # The half of the gate that was missing. The block above honours a
    # revocation; this one honours the absence of permission in the first
    # place, which is not the same thing and was never checked here. An
    # automated message could sit in the queue, the lead could turn out to have
    # neither consent on record nor a message they sent us first, and this
    # sweep would deliver it anyway — the producer's gate having been the only
    # one, and having run before the row existed.
    #
    # It became reachable a different way with the call console: telling an
    # advisor "phone me, don't text me" cancels the follow-ups but cannot
    # cancel a text already queued.
    # Imported here rather than at module scope: capture.py reaches back into
    # this module, and a top-level import closes the cycle.
    from app.services.capture import may_send_automated

    if lead is not None and channel and not await may_send_automated(lead, channel, db):
        # Backed off, NOT retired. Unlike an opt-out this is a point-in-time
        # answer that can turn into a yes: consent gets recorded, or the person
        # writes to us on this channel, and then the message is sendable. The
        # gate is also per channel, so a lead whose only inbound was WhatsApp
        # fails it for a queued SMS — killing the row outright there would
        # discard a message the very next reply would have permitted. Backing
        # off costs a few retries and reaches the attempt cap on its own if
        # nothing changes.
        schedule_retry(message, f"no permission on record to send on {channel} yet")
        log.info(
            "Holding queued message %s: lead %d has no consent or prior inbound "
            "on %s (attempt %d of %d)",
            message.id,
            lead.id,
            channel,
            message.send_attempts,
            MAX_ATTEMPTS,
        )
        await db.commit()
        return "failed"

    if not recipient or not channel:
        # No address right now. Counted as a failure and backed off like any
        # other, NOT retired on the spot: `_recipient_of` also returns nothing
        # when the lead is momentarily invisible — an unbound org on the RLS
        # session, a row mid-write — and jumping straight to the attempt cap
        # let one bad tick delete a pending reply for good.
        schedule_retry(message, "no address for this conversation yet")
        log.warning(
            "message %s has no address to go to (attempt %d of %d)",
            message.id,
            message.send_attempts,
            MAX_ATTEMPTS,
        )
        await db.commit()
        return "failed"

    try:
        external_id, _ = await _dispatch_send(
            channel,
            to=recipient,
            text=message.content,
            # The row was holding all three. Without them the retry arrived as a
            # brand-new email titled "Tu consulta", detached from the thread the
            # lead was reading.
            subject=message.subject,
            in_reply_to=in_reply_to,
            references=in_reply_to,
        )
    except Exception as exc:  # noqa: BLE001 — surviving this is the whole point
        schedule_retry(message, str(exc))
        await db.commit()
        return "failed"

    message.delivery_status = MessageStatus.SENT
    message.next_attempt_at = None
    message.last_error = None
    if external_id:
        message.external_id = external_id
    await db.commit()
    return "sent"


async def _lead_of(message: Message, db: AsyncSession):
    """The lead a queued message is addressed to, or None if it cannot be found."""
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    return (
        await db.execute(
            select(Lead)
            .join(Conversation, Conversation.lead_id == Lead.id)
            .where(Conversation.id == message.conversation_id)
        )
    ).scalar_one_or_none()


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

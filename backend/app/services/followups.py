"""Autonomous nurture follow-ups (Phase 10).

When a visit is booked we enqueue a 24h-before reminder and a post-visit
sequence (24h / 72h / 7d). A background worker sends the ones whose
`scheduled_for` has passed — skipping leads on human takeover, cancelled visits,
and the 72h nudge when the lead already replied after the visit. Messages are
bilingual and sent as the AI agent through the lead's active channel.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentSettings,
    CallLog,
    Conversation,
    FollowUp,
    FollowUpKind,
    FollowUpStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
    Visit,
    VisitStatus,
)
from app.models.lead import PreferredChannel
from app.services.capture import may_send_automated
from app.services.conversation import (
    _dispatch_send,
    reachable_active_conversations,
)
from app.services.delivery import schedule_retry
from app.services.i18n import detect_language, pick_supported_language
from app.services.tenant_context import get_org_id

log = logging.getLogger(__name__)

# A follow-up with no permitted channel is HELD, not cancelled: the lead may
# consent on the website tomorrow or reply on WhatsApp next week, and the
# sequence was waiting for exactly that. Re-checked daily, and given up on
# after a fortnight so a permanently unreachable lead does not accumulate work
# forever.
_HOLD_RETRY_AFTER = timedelta(days=1)
# Counted in holds rather than in wall-clock age. `created_at` is when the
# follow-up was SCHEDULED, which for a post-visit-7d row is a week before it is
# due — so an age-based cutoff dropped it on the first hold instead of holding
# it. One hold a day, so fourteen holds is a fortnight of grace.
_HOLD_GIVE_UP_AFTER_HOLDS = 14

# Offsets relative to the visit's scheduled_at.
_POST_VISIT_OFFSETS = {
    FollowUpKind.POST_VISIT_24H: timedelta(hours=24),
    FollowUpKind.POST_VISIT_72H: timedelta(hours=72),
    FollowUpKind.POST_VISIT_7D: timedelta(days=7),
}

# How overdue a post-visit message may be and still be worth sending.
#
# The invariant this has to preserve is that no two of these can be overdue at
# the same time, because two overdue messages are the burst. That needs the
# window to be narrower than the smallest *gap between* offsets (48h here), and
# the smallest offset (24h) happens to satisfy it — which is not the same
# statement, and an earlier comment here claimed the wrong one. Add a fourth
# offset less than 24h from its neighbour and the prose would still have read
# true while the invariant broke, so `test_no_two_post_visit_messages_can_be_
# overdue_at_once` checks it against the actual values instead.
_POST_VISIT_GRACE = min(_POST_VISIT_OFFSETS.values())

# The same rule at send time needs a little more room than at creation time, or
# the two disagree about a row on the boundary: `enqueue_for_visit` deliberately
# keeps a message 23h59m overdue — a showing logged the morning after — and the
# very next tick would have cancelled the one message the enqueue logic went out
# of its way to preserve.
_SEND_STALE_AFTER = _POST_VISIT_GRACE + timedelta(hours=1)

# Bilingual templates. {name} is dropped cleanly when the lead has no name.
_TEMPLATES: dict[FollowUpKind, dict[str, str]] = {
    FollowUpKind.REMINDER_24H: {
        "en": "Hi{name}! Just a reminder of your visit tomorrow with {agency}. See you there — reply here if anything comes up.",
        "es": "¡Hola{name}! Te recuerdo tu visita de mañana con {agency}. ¡Nos vemos! Si surge algo, respondé por acá.",
    },
    FollowUpKind.POST_VISIT_24H: {
        "en": "Hi{name}, how did the visit go? Anything you liked, or something else you'd like to see?",
        "es": "Hola{name}, ¿qué te pareció la visita? ¿Te gustó algo, o querés ver otra opción?",
    },
    FollowUpKind.POST_VISIT_72H: {
        "en": "Hi{name}, just checking in on the property you saw. Happy to answer any questions or line up another viewing.",
        "es": "Hola{name}, ¿pudiste pensar en la propiedad que viste? Quedo para cualquier duda o para coordinar otra visita.",
    },
    FollowUpKind.POST_VISIT_7D: {
        "en": "Hi{name}, we have new listings similar to what you saw. Want me to send you a few?",
        "es": "Hola{name}, tenemos nuevas propiedades parecidas a la que viste. ¿Te paso algunas?",
    },
    # Scheduled from the console after a call. Deliberately open-ended: the
    # advisor already knows the specifics, and a template that guesses them
    # ("about the Wash Park house") is wrong more often than it is right.
    FollowUpKind.CALL_FOLLOW_UP: {
        "en": "Hi{name}, {agency} here — following up on our call. Has anything changed on your side, or shall I send you a few options?",
        "es": "Hola{name}, te escribe {agency} — te doy seguimiento a nuestra llamada. ¿Ha cambiado algo por tu lado, o te mando algunas opciones?",
    },
}


def _first_name(lead: Lead) -> str:
    """The lead's first name with a leading space, or "".

    `if not lead.name` is not enough: a WhatsApp profile name of " " is truthy,
    and `" ".strip().split()[0]` raises IndexError. That exception escaped the
    per-row handler, so the whole batch never reached its single commit — five
    identical SMS were handed to the provider across five ticks with zero
    message rows written and the follow-up frozen at `pending attempts=0`. One
    blank profile name wedged the worker for every tenant.
    """
    parts = (lead.name or "").split()
    return " " + parts[0] if parts else ""


async def _agency_name(db: AsyncSession) -> str:
    cfg = (await db.execute(select(AgentSettings).where(AgentSettings.org_id == _acting_org()))).scalar_one_or_none()
    return cfg.agency_name if cfg and cfg.agency_name else "the team"


async def _lead_language(lead: Lead, db: AsyncSession) -> str:
    """Best-effort language for nurture text: from the lead's last inbound, else
    the agency's primary supported language."""
    cfg = (await db.execute(select(AgentSettings).where(AgentSettings.org_id == _acting_org()))).scalar_one_or_none()
    supported = (cfg.languages if cfg else ["en"]) or ["en"]
    last_in = (
        await db.execute(
            select(Message.content)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id == lead.id, Message.direction == MessageDirection.INBOUND)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_in:
        return pick_supported_language(detect_language(last_in), supported)
    return supported[0]


# ── Enqueue ──────────────────────────────────────────────────────────────


async def enqueue_for_visit(visit: Visit, db: AsyncSession, *, now: datetime | None = None) -> int:
    """Idempotently schedule the reminder + post-visit follow-ups for a visit.

    Returns how many NEW follow-ups were created. Safe to call repeatedly
    (UNIQUE(visit_id, kind)).
    """
    now = now or datetime.now(UTC)
    if visit.status in (VisitStatus.CANCELLED, VisitStatus.NO_SHOW):
        return 0

    when = visit.scheduled_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    planned: list[tuple[FollowUpKind, datetime]] = []
    reminder_at = when - timedelta(hours=24)
    if reminder_at > now:  # only schedule a reminder if it's still in the future
        planned.append((FollowUpKind.REMINDER_24H, reminder_at))
    for kind, offset in _POST_VISIT_OFFSETS.items():
        # A visit entered with a past date — a showing logged after the fact, a
        # mistyped year, a date the voice agent misheard — used to schedule all
        # three post-visit messages already overdue, and the next sweep sent
        # "how did it go?", the nudge and "new listings just came up" to the
        # same person within seconds. The burst is the defect, not lateness:
        # a showing logged the morning after is exactly when "how did it go?"
        # should go out. So one message may be overdue, by less than the
        # smallest gap in the cadence — which makes two of them impossible.
        due = when + offset
        if due > now - _POST_VISIT_GRACE:
            planned.append((kind, due))

    existing = set(
        (
            await db.execute(select(FollowUp.kind).where(FollowUp.visit_id == visit.id))
        ).scalars().all()
    )

    created = 0
    for kind, sched in planned:
        if kind in existing:
            continue
        db.add(
            FollowUp(
                lead_id=visit.lead_id,
                visit_id=visit.id,
                kind=kind,
                status=FollowUpStatus.PENDING,
                scheduled_for=sched,
            )
        )
        created += 1
    if created:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            created = 0
    return created


# The stated preferences this worker can actually act on. CALL and EMAIL are
# absent on purpose — neither has a compliant automated sender today (no voice
# provider; no unsubscribe header on outbound email), so a follow-up for either
# is surfaced as a task for a human instead of being sent. Adding a value here
# turns on automated sending for it, which is a compliance decision, not a
# configuration one.
AUTOMATED_PREFERENCES = frozenset({PreferredChannel.SMS})


def _prefer(
    candidates: list[Conversation], preferred: PreferredChannel | None
) -> list[Conversation]:
    """Move the channel the lead asked for to the front of the queue.

    Reorders; never filters. Honouring a preference is worth doing, but a
    preference is not permission and it is not reachability: dropping the other
    channels would mean a lead who said "text me" and has consent only on
    WhatsApp is never contacted again, which serves nobody. The consent gate
    downstream still decides what may actually be sent — this only decides what
    is offered to it first.

    Only preferences in AUTOMATED_PREFERENCES reach here; the rest never enter
    the batch.
    """
    if preferred is None:
        return candidates
    wanted = preferred.value
    return sorted(candidates, key=lambda c: 0 if c.channel == wanted else 1)


async def enqueue_after_call(
    call: CallLog,
    db: AsyncSession,
    *,
    in_days: int,
    now: datetime | None = None,
) -> FollowUp | None:
    """Schedule the single nudge a logged call asked for.

    The other four kinds hang off a visit, which left the commonest case after
    a call — interested, not ready, nothing booked — with no way to be followed
    up at all.

    One row per call, not a drip. The advisor chose this date on the phone; a
    ladder they did not choose would be us deciding how often to contact
    somebody we just spoke to. When the nudge goes out and nothing comes back,
    the lead resurfaces in the console's own list, and that loop has a human in
    it on purpose.

    Does NOT commit: the caller runs inside `register_call`'s transaction, so
    that a call is never recorded without its follow-up or the other way round.
    """
    if in_days < 0:
        raise ValueError("a follow-up cannot be scheduled in the past")

    now = now or datetime.now(UTC)
    follow_up = FollowUp(
        org_id=call.org_id,
        lead_id=call.lead_id,
        call_log_id=call.id,
        kind=FollowUpKind.CALL_FOLLOW_UP,
        status=FollowUpStatus.PENDING,
        scheduled_for=now + timedelta(days=in_days),
    )
    db.add(follow_up)
    return follow_up


# ── Process due ────────────────────────────────────────────────────────────


async def _lead_replied_since(lead_id: int, since: datetime, db: AsyncSession) -> bool:
    n = (
        await db.execute(
            select(func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.lead_id == lead_id,
                Message.direction == MessageDirection.INBOUND,
                Message.created_at > since,
            )
        )
    ).scalar_one()
    return n > 0


def _as_utc(when: datetime) -> datetime:
    """Postgres hands these back naive on some paths; comparing one against an
    aware `now` raises rather than answering."""
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


async def _persist(db: AsyncSession, fu_id: int) -> None:
    """Save this item's outcome, whatever path produced it.

    A message handed to the provider is irreversible the instant it leaves, and
    a skip or a hold is bookkeeping the next item's rollback must not be able to
    undo. Failing to commit is logged rather than raised: it belongs to one
    follow-up, and taking the batch down over it is the behaviour being removed.
    """
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.exception(
            "Follow-up %d finished but its row could not be committed — it may "
            "be reprocessed next tick: %s",
            fu_id, exc,
        )


async def process_due_followups(db: AsyncSession, *, now: datetime | None = None, limit: int = 50) -> dict[str, int]:
    """Send (or skip) all pending follow-ups whose time has come.

    Returns counts {sent, skipped, failed}.
    """
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(FollowUp)
            .join(Lead, Lead.id == FollowUp.lead_id)
            .where(
                FollowUp.status == FollowUpStatus.PENDING,
                FollowUp.scheduled_for <= now,
                # A lead whose stated channel has no automated sender is a task
                # for the console, not work for this sweep — see
                # AUTOMATED_PREFERENCES. Excluded in SQL, not in the loop: left
                # in the batch such a row would stay PENDING and due for ever,
                # and being the oldest it would sit at the head of every
                # limit-N window and starve the follow-ups that can be sent.
                or_(
                    Lead.preferred_channel.is_(None),
                    Lead.preferred_channel.in_(AUTOMATED_PREFERENCES),
                ),
            )
            .order_by(FollowUp.scheduled_for)
            .limit(limit)
        )
    ).scalars().all()

    sent = skipped = failed = 0
    agency = await _agency_name(db)

    # Iterated by id, not by loaded row. A rollback in any iteration expires
    # every ORM object in this list, and the next plain attribute access on one
    # — even `fu.id` — becomes a synchronous lazy load and raises MissingGreenlet
    # outside every handler here, which is the batch dying again by another
    # route. Re-reading each row costs one indexed select and cannot go stale.
    # One post-visit message per lead per sweep, whatever the dates say.
    #
    # Both graces reason about *when a row is due*, and there is a route neither
    # can see: the consent hold pushes every due row to the same "tomorrow", so
    # after a fortnight of holds the 24h/72h/7d cadence has collapsed onto one
    # tick, and the moment consent arrives all three go out together. That is
    # the burst this module exists to prevent, arriving through the schedule
    # rather than around it. Rather than add a third rule about dates, cap the
    # outcome: the rest keep their rows and go out on later sweeps.
    sent_to_lead: set[int] = set()

    for fu_id in [row.id for row in rows]:
        fu = await db.get(FollowUp, fu_id)
        if fu is None:
            continue
        # Every path out of this item persists its own outcome before the
        # next one runs. `continue` still runs a `finally`, and that is the
        # point: with ten early exits, remembering to commit at each is the
        # kind of thing this codebase forgets in exactly one of them. It had
        # already gone wrong the other way — a later item's rollback threw
        # away an earlier item's SKIPPED and its hold counter, so a held
        # follow-up never advanced toward giving up and never moved off the
        # head of the queue.
        try:
            lead = (await db.execute(select(Lead).where(Lead.id == fu.lead_id))).scalar_one_or_none()
            if lead is None:
                fu.status = FollowUpStatus.CANCELLED
                skipped += 1
                continue

            # Skip rules.
            if lead.human_takeover:
                fu.status = FollowUpStatus.SKIPPED
                skipped += 1
                continue
            # Defined for every follow-up, not only the ones with a visit: a
            # standalone nurture row has no visit and must not blow up the sweep
            # with a NameError when the hold branch reads it.
            visit_is_past = False
            visit_at = None
            if fu.visit_id is not None:
                visit = (await db.execute(select(Visit).where(Visit.id == fu.visit_id))).scalar_one_or_none()
                # COMPLETED belongs here for the PRE-visit reminder only: telling
                # somebody "your viewing is tomorrow" about a viewing they have
                # already attended is the kind of message that makes the whole
                # system look broken to the client. The post-visit follow-ups are
                # the opposite — COMPLETED is exactly when they should go.
                dead = {VisitStatus.CANCELLED, VisitStatus.NO_SHOW}
                if fu.kind == FollowUpKind.REMINDER_24H:
                    dead.add(VisitStatus.COMPLETED)
                visit_at = visit.scheduled_at if visit is not None else None
                if visit_at is not None and visit_at.tzinfo is None:
                    visit_at = visit_at.replace(tzinfo=UTC)
                visit_is_past = visit_at is not None and visit_at < now
                if visit is None or visit.status in dead:
                    fu.status = FollowUpStatus.CANCELLED
                    skipped += 1
                    continue
                if fu.kind == FollowUpKind.POST_VISIT_72H:
                    sched_at = visit.scheduled_at
                    if sched_at.tzinfo is None:
                        sched_at = sched_at.replace(tzinfo=UTC)
                    if await _lead_replied_since(lead.id, sched_at, db):
                        fu.status = FollowUpStatus.SKIPPED  # they already re-engaged
                        skipped += 1
                        continue

            # Only channels that can actually deliver to this lead — a lead who came
            # in through the public web form has a `web` conversation as their
            # newest, and dispatching a nurture message to it marked every
            # follow-up FAILED instead of sending anything.
            #
            # And the FIRST such channel the consent gate allows, not merely the
            # newest one. Taking only the newest meant a lead who genuinely started
            # a WhatsApp conversation lost their sequence for good as soon as a
            # realtor answered them once by SMS: the SMS thread became newest, the
            # gate correctly refused it because consent is per channel, and SKIPPED
            # is terminal — the WhatsApp thread that would have passed was never
            # looked at.
            # A pre-visit reminder must never go out after its own visit, whatever
            # else is true. This guard was written inside the "no permitted
            # channel" branch below — the one place nothing could be sent anyway —
            # so it did nothing at all: with a sendable channel the sweep fell
            # straight through and dispatched "your viewing is tomorrow" days
            # after the viewing. The COMPLETED check upstream only helps when
            # somebody remembered to mark the visit done, which is not the
            # ordinary state of a calendar.
            if fu.kind == FollowUpKind.REMINDER_24H and visit_is_past:
                log.info(
                    "Follow-up %d cancelled for lead %d: its visit is already in "
                    "the past",
                    fu.id, lead.id,
                )
                fu.status = FollowUpStatus.CANCELLED
                skipped += 1
                continue

            # The same grace `enqueue_for_visit` applies when creating these,
            # applied again here — because that one only guards creation. Let
            # this worker be down for a week and all three post-visit messages
            # come due on their own, so the first tick back sends "how did it
            # go?", the nudge and "new listings" within seconds of each other:
            # the burst returns by a route the creation-time check cannot see.
            if (
                fu.kind in _POST_VISIT_OFFSETS
                and fu.scheduled_for is not None
                and (
                    # Never touched: `scheduled_for` is still the real due date,
                    # so staleness reads straight off it. This is the outage
                    # case — nobody ran the worker, nothing advanced.
                    (
                        fu.attempts == 0
                        and _as_utc(fu.scheduled_for) < now - _SEND_STALE_AFTER
                    )
                    # Touched at least once: `scheduled_for` has been moved
                    # forward by the hold and no longer says when this message
                    # was *for*, so it cannot answer the question. Exempting
                    # these outright — which is what the first version of this
                    # did — meant a held sequence survived an outage and then
                    # fired all three messages at once, 38 days late. A counter
                    # is not a clock. Bound the lateness absolutely instead,
                    # from the visit the message is about, allowing the whole
                    # hold window to elapse legitimately first.
                    or (
                        visit_at is not None
                        and now
                        > visit_at
                        + _POST_VISIT_OFFSETS[fu.kind]
                        + _SEND_STALE_AFTER
                        + _HOLD_GIVE_UP_AFTER_HOLDS * _HOLD_RETRY_AFTER
                    )
                )
            ):
                log.info(
                    "Follow-up %d cancelled for lead %d: %s was due %s and is "
                    "too stale to send now",
                    fu.id, lead.id, fu.kind.value, fu.scheduled_for,
                )
                fu.status = FollowUpStatus.CANCELLED
                skipped += 1
                continue

            if fu.kind in _POST_VISIT_OFFSETS and lead.id in sent_to_lead:
                log.info(
                    "Follow-up %d held for lead %d: they already received a "
                    "post-visit message on this sweep",
                    fu.id, lead.id,
                )
                fu.scheduled_for = now + _HOLD_RETRY_AFTER
                skipped += 1
                continue

            # Choosing *where* to send must not be able to take the batch down
            # either. Composing was wrapped for exactly that reason and these lines
            # were left outside it, so one lead whose conversations or consent rows
            # raised aborted the loop before its single commit — and every
            # follow-up already handed to the provider on that tick lost its SENT
            # row and was sent again on the next one, to people who had already
            # received it, at TCPA exposure per message.
            try:
                candidates = await reachable_active_conversations(lead.id, lead.phone, db)
                candidates = _prefer(candidates, lead.preferred_channel)
                conv = None
                for candidate in candidates:
                    # TCPA. An automated text to somebody who neither consented in
                    # writing nor wrote to us first on that channel is $500–$1,500
                    # per message, and the exposure lands on the broker's licence
                    # rather than on the software.
                    if await may_send_automated(lead, candidate.channel, db):
                        conv = candidate
                        break
            except Exception as exc:  # noqa: BLE001
                # Rollback first, and it is not housekeeping. A database error —
                # the very class this handler names — leaves the transaction
                # aborted, so without this the next iteration's `select(Lead)`
                # raises InFailedSQLTransactionError *outside* any handler and the
                # batch dies anyway. Worse, the increment below would be written
                # into the aborted transaction and thrown away, so the give-up
                # bound could never be reached: the bad row stayed PENDING and due,
                # sorted first by `scheduled_for`, and starved that tenant's entire
                # nurture queue on every tick, silently.
                await db.rollback()
                log.exception("Follow-up %d could not choose a channel: %s", fu_id, exc)
                refreshed = await db.get(FollowUp, fu_id)
                if refreshed is None:
                    skipped += 1
                    continue
                # Left PENDING so a transient database error is retried rather than
                # cancelling somebody's sequence, but bounded so a permanently
                # malformed row cannot spin forever.
                refreshed.attempts += 1
                if refreshed.attempts > _HOLD_GIVE_UP_AFTER_HOLDS:
                    refreshed.status = FollowUpStatus.FAILED
                    failed += 1
                else:
                    skipped += 1
                await db.commit()
                continue

            if conv is None:
                # HELD, not SKIPPED. SKIPPED is terminal and never re-evaluated, so
                # "held for consent" silently meant "cancelled": a lead who ticks
                # the box on the website tomorrow, or replies on WhatsApp next
                # week, would never receive the sequence that was waiting for
                # exactly that. Push it a day and look again.
                # Counted in HOLDS, not from `created_at`. A post-visit-7d
                # follow-up is created the moment the visit is booked, so by the
                # time it is due its row can already be older than the grace
                # period — measuring from creation dropped it on its very first
                # hold, which is the opposite of holding it.
                fu.attempts += 1
                if fu.attempts > _HOLD_GIVE_UP_AFTER_HOLDS:
                    log.info(
                        "Follow-up %d dropped for lead %d after %d daily holds "
                        "with no permitted channel",
                        fu.id, lead.id, fu.attempts,
                    )
                    fu.status = FollowUpStatus.SKIPPED
                else:
                    log.info(
                        "Follow-up %d held for lead %d: %d reachable channel(s), "
                        "none with consent on record or a message they sent us "
                        "first — retrying tomorrow",
                        fu.id, lead.id, len(candidates),
                    )
                    fu.scheduled_for = now + _HOLD_RETRY_AFTER
                skipped += 1
                continue

            # Composing the message must not be able to take the batch down. It
            # did: a blank WhatsApp profile name raised IndexError out here,
            # outside the dispatch try below, so the loop aborted before its single
            # commit — five identical SMS handed to the provider across five ticks,
            # zero rows written, the follow-up frozen. One malformed row must cost
            # one follow-up, not every tenant's nurture flow.
            try:
                lang = await _lead_language(lead, db)
                template = _TEMPLATES[fu.kind].get(lang) or _TEMPLATES[fu.kind]["en"]
                text = template.format(name=_first_name(lead), agency=agency)
            except Exception as exc:  # noqa: BLE001
                # Same reasoning as the channel handler above: `_lead_language`
                # queries, so this can be a database error too, and a handler that
                # does not roll back only moves the crash to the next iteration.
                await db.rollback()
                log.exception("Follow-up %d could not be composed: %s", fu_id, exc)
                refreshed = await db.get(FollowUp, fu_id)
                if refreshed is not None:
                    refreshed.status = FollowUpStatus.FAILED
                    await db.commit()
                failed += 1
                continue

            outbound = Message(
                conversation_id=conv.id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.AGENT,
                content=text,
                delivery_status=MessageStatus.PENDING,
            )
            db.add(outbound)
            fu.attempts += 1
            try:
                external_id, _ = await _dispatch_send(conv.channel, to=lead.phone, text=text)
                outbound.external_id = external_id
                outbound.delivery_status = MessageStatus.SENT
                fu.status = FollowUpStatus.SENT
                fu.sent_at = now
                lead.last_message_at = now
                if fu.kind in _POST_VISIT_OFFSETS:
                    sent_to_lead.add(lead.id)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                log.error("Follow-up %d dispatch failed: %s", fu.id, exc)
                failed += 1
                try:
                    # The follow-up itself is done — it produced its Message and
                    # will not compose another. Delivery of that one Message is
                    # the retry queue's job from here, so the lead gets it once,
                    # late, instead of never.
                    schedule_retry(outbound, str(exc))
                    fu.status = FollowUpStatus.FAILED
                    await db.commit()
                except Exception as while_recording:  # noqa: BLE001
                    # The send path writes through this session, so its failure
                    # can be the session's. Its two sibling handlers roll back
                    # and this one did not: the outbound row and the FAILED
                    # status both vanished while the follow-up stayed PENDING,
                    # and the next tick composed and sent it again — a duplicate
                    # text, with the exposure that carries, from a log line
                    # nobody reads. Record FAILED and give up the retry: sending
                    # twice is the worse outcome of the two.
                    await db.rollback()
                    log.exception(
                        "Follow-up %d could not even be marked failed: %s",
                        fu_id, while_recording,
                    )
                    refreshed = await db.get(FollowUp, fu_id)
                    if refreshed is not None:
                        refreshed.status = FollowUpStatus.FAILED
                        await db.commit()

        except Exception as exc:  # noqa: BLE001
            # The last line of defence, and it has to exist: the inner handlers
            # recover on the same session that just failed, so when the failure
            # is the session itself their own recovery raises too, escapes the
            # loop, and leaves the row PENDING for the next tick to send again.
            # One follow-up must never cost the batch, however it fails.
            failed += 1
            log.exception("Follow-up %d failed in a way nothing else caught: %s", fu_id, exc)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                log.exception("Follow-up %d: the session could not even be rolled back", fu_id)
        finally:
            await _persist(db, fu_id)

    await db.commit()
    if sent or skipped or failed:
        log.info("Follow-ups processed: sent=%d skipped=%d failed=%d", sent, skipped, failed)
    return {"sent": sent, "skipped": skipped, "failed": failed}


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

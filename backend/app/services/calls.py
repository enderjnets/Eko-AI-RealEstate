"""Register what happened on a call, and let the outcome do the work.

The whole point of the console is that marking a call is not filing it. One
tap records what was learned *and* fires the next step, because a second screen
is where follow-through goes to die.

Two rules shape everything here:

* **What the call revealed is written onto the `Lead`.** `match_properties_for_lead`
  and `compute_lead_score` already read intent, budget, zone, property type and
  urgency from there. A parallel copy on the call row would need somebody to
  reconcile the two, and nobody would.
* **One call, one transaction.** A call recorded without the follow-up it
  promised, or a follow-up queued for a call that was never saved, are both
  worse than the write failing outright.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CallLog,
    CallOutcome,
    FollowUp,
    FollowUpKind,
    FollowUpStatus,
    Lead,
)
from app.models.lead import LeadIntent, LeadStatus, PreferredChannel
from app.services.followups import enqueue_after_call
from app.services.scoring import rescore_lead

log = logging.getLogger(__name__)

# What we write as the consent record when someone asks, on the phone, to be
# sent something. It names the source, because "consent_at is set" with no
# provenance is not evidence of anything a year later in front of a regulator.
VERBAL_CONSENT_TEMPLATE = (
    "Verbal consent given on a call with {who} on {when} to be sent property "
    "options and appointment details by text message."
)


@dataclass(frozen=True)
class CallUpdates:
    """What the advisor confirmed or corrected during the call.

    Every field is optional and `None` means "not discussed" — never "clear
    it". A console that blanks a lead's budget because the advisor did not
    re-enter it is worse than one that captures nothing.
    """

    intent: LeadIntent | None = None
    urgency: str | None = None
    zone: str | None = None
    property_type: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    preferred_channel: PreferredChannel | None = None
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class CallResult:
    call: CallLog
    follow_up: FollowUp | None
    score: int
    cancelled_follow_ups: int


# Outcomes that mean "stop the machinery". Everything pending is cancelled, and
# nothing new is queued.
_STAND_DOWN = {
    CallOutcome.HAS_AGENT,
    CallOutcome.DO_NOT_CONTACT,
    CallOutcome.WRONG_NUMBER,
}


def _apply(lead: Lead, updates: CallUpdates) -> None:
    # Derived from the dataclass rather than a hand-kept list. A second list to
    # remember is how a field gets added to CallUpdates, plumbed through the
    # API, shown in the UI, and then silently never written — which this
    # repository has paid for four times under a different name.
    for field in fields(updates):
        value = getattr(updates, field.name)
        if value is None:
            continue
        if isinstance(value, str):
            # A blank string is the same statement as an absent field: nothing
            # was said about it. Without this, an untouched input that posts ""
            # erases the lead's zone or budget — the exact opposite of the rule
            # this service exists to keep, and invisible until somebody notices
            # the matcher has stopped finding anything for them. The console
            # already trims, but a rule that lives only in the client is a rule
            # the next client does not have.
            value = value.strip()
            if not value:
                continue
        setattr(lead, field.name, value)


def _record_verbal_consent(lead: Lead, *, who: str | None, when: datetime) -> bool:
    """Write the consent evidence, once.

    Returns whether anything was written. Consent is a historical fact: the
    first record of it is the one that was actually shown or spoken, so an
    existing `consent_at` is never overwritten with a fresher, vaguer one.
    """
    if lead.consent_at is not None:
        return False
    lead.consent_at = when
    lead.consent_text = VERBAL_CONSENT_TEMPLATE.format(
        who=who or "an advisor", when=when.date().isoformat()
    )
    return True


async def _cancel_pending(lead_id: int, db: AsyncSession) -> int:
    """Cancel every follow-up still waiting for this lead.

    Used when the person tells us to stop, or that they already have an agent.
    Leaving a queued nudge behind means the instruction was taken and then
    ignored three days later, which is exactly the complaint that follows.
    """
    pending = (
        await db.execute(
            select(FollowUp).where(
                FollowUp.lead_id == lead_id,
                FollowUp.status == FollowUpStatus.PENDING,
            )
        )
    ).scalars().all()
    for row in pending:
        row.status = FollowUpStatus.CANCELLED
    return len(pending)


async def register_call(
    lead: Lead,
    outcome: CallOutcome,
    db: AsyncSession,
    *,
    logged_by: str | None = None,
    note: str | None = None,
    updates: CallUpdates | None = None,
    follow_up_in_days: int | None = None,
    asked_for_texts: bool = False,
    now: datetime | None = None,
) -> CallResult:
    """Record a call and carry out the one action its outcome implies.

    `asked_for_texts` is the advisor confirming the person asked, on the call,
    to be sent options. It is the only thing that writes consent here, and it
    is deliberately separate from `preferred_channel`: saying "text me rather
    than email me" is a preference about *how*, not permission to start.
    """
    now = now or datetime.now(UTC)
    updates = updates or CallUpdates()

    call = CallLog(
        org_id=lead.org_id,
        lead_id=lead.id,
        logged_by=logged_by,
        outcome=outcome,
        note=(note or "").strip() or None,
    )
    db.add(call)
    # The follow-up needs call.id, and the outcome branches below need the row
    # to exist. Flush rather than commit: one call is one transaction.
    await db.flush()

    _apply(lead, updates)

    if asked_for_texts:
        _record_verbal_consent(lead, who=logged_by, when=now)

    follow_up: FollowUp | None = None
    cancelled = 0

    if outcome in _STAND_DOWN:
        cancelled = await _cancel_pending(lead.id, db)
        if outcome == CallOutcome.DO_NOT_CONTACT:
            # The same field the STOP keyword sets, so every sender already
            # honours it — there is no second switch to remember.
            lead.opted_out_at = now
            lead.opted_out_channel = "call"
            lead.opted_out_keyword = "verbal"
            lead.status = LeadStatus.LOST
        elif outcome == CallOutcome.HAS_AGENT:
            # NAR Article 16. Paused, not lost: the representation ends one day
            # and this is not a rejection of us.
            lead.status = LeadStatus.PAUSED
        elif outcome == CallOutcome.WRONG_NUMBER:
            lead.status = LeadStatus.PAUSED
    else:
        # A logged call *is* the touch a pending call-task was asking for.
        # Leaving it queued would show the advisor a job they just did.
        cancelled = await _resolve_call_tasks(lead.id, db, exclude_call_id=call.id)

        if outcome == CallOutcome.BOOKED_VISIT:
            lead.status = LeadStatus.VISITING
        elif outcome in (CallOutcome.WANTS_LISTINGS, CallOutcome.FOLLOW_UP):
            if lead.status == LeadStatus.NEW:
                lead.status = LeadStatus.QUALIFIED

        if follow_up_in_days is not None:
            follow_up = await enqueue_after_call(
                call, db, in_days=follow_up_in_days, now=now
            )

    # `last_message_at` is deliberately NOT touched here. It means what it
    # says — the last *message* — and it feeds both the recency component of
    # the score and the inbox's sort order. Stamping it from a call would
    # inflate the score of someone who just said no and quietly reshuffle the
    # inbox, from an action nobody would expect to do either.

    # Rescore inside the transaction so the console's next screen — the
    # property proposals — sees the lead the call actually described.
    score = await rescore_lead(lead, db, commit=False)

    await db.commit()
    return CallResult(
        call=call, follow_up=follow_up, score=score, cancelled_follow_ups=cancelled
    )


async def _resolve_call_tasks(
    lead_id: int, db: AsyncSession, *, exclude_call_id: int
) -> int:
    """Close out call-tasks this call has just satisfied."""
    rows = (
        await db.execute(
            select(FollowUp).where(
                FollowUp.lead_id == lead_id,
                FollowUp.status == FollowUpStatus.PENDING,
                FollowUp.kind == FollowUpKind.CALL_FOLLOW_UP,
                FollowUp.call_log_id != exclude_call_id,
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = FollowUpStatus.CANCELLED
    return len(rows)

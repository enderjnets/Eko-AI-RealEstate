"""The console's list of today.

Three things need somewhere to be seen, and until now two of them had nowhere:

* **Calls to make.** A follow-up for a lead who asked to be phoned or emailed
  has no automated sender behind it (see `followups.AUTOMATED_PREFERENCES`), so
  it is a job for a person. Without this list those rows would sit pending for
  ever and the preference would be a promise nobody keeps.
* **Follow-ups that are not getting through.** The worker holds a message when
  no channel has consent or a prior inbound, retries daily, and gives up after
  a few rounds; and a provider outage marks the due ones FAILED. Both only ever
  appeared in a log line, so the office could not tell "we are nurturing them"
  from "we have not been able to say anything to them for a week".
* **Hot leads nobody has touched.** The scorer already ranks them; nothing
  surfaces the ones that are ranked highly and then left alone.

A list, not a dashboard. Anything that needs interpreting belongs on the
analytics page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import get_db
from app.models import CallLog, FollowUp, FollowUpStatus, Lead, LeadStatus
from app.models.lead import PreferredChannel
from app.services.followups import AUTOMATED_PREFERENCES

router = APIRouter()

# Statuses that mean the relationship is not currently ours to work.
CLOSED_STATUSES = (LeadStatus.WON, LeadStatus.LOST, LeadStatus.PAUSED)

HOT_SCORE = 70

# How far back a failed follow-up stays on the list. FAILED is terminal, so
# without a window the section becomes an ever-growing archive rather than a
# list of what needs doing today.
FAILED_WINDOW_DAYS = 14


class ConsoleLead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    score: int | None = None
    status: LeadStatus
    zone: str | None = None
    preferred_channel: PreferredChannel | None = None
    last_message_at: datetime | None = None


class ConsoleTask(BaseModel):
    """A follow-up a person has to carry out, because nothing can send it."""

    follow_up_id: int
    scheduled_for: datetime
    channel: PreferredChannel
    lead: ConsoleLead


class HeldFollowUp(BaseModel):
    """Not getting through: either the consent gate is refusing every channel,
    or the sends themselves failed."""

    follow_up_id: int
    # When the message was for. Since the deferral moved to its own column this
    # stays put, which is what makes "held, 7 attempts, due 7 days ago" honest —
    # but on its own it left the operator with no idea when the system would
    # look again, so `next_attempt_at` carries that.
    scheduled_for: datetime
    next_attempt_at: datetime | None = None
    holds: int
    status: FollowUpStatus
    lead: ConsoleLead


class ConsoleToday(BaseModel):
    tasks: list[ConsoleTask]
    held: list[HeldFollowUp]
    untouched_hot: list[ConsoleLead]
    generated_at: datetime


def _open_leads(stmt: Select) -> Select:
    return stmt.where(Lead.status.notin_(CLOSED_STATUSES), Lead.opted_out_at.is_(None))


@router.get("/today", response_model=ConsoleToday)
async def today(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    untouched_days: int = Query(default=7, ge=1, le=90),
) -> ConsoleToday:
    now = datetime.now(UTC)

    # 1. Tasks: due follow-ups whose lead's channel has no automated sender.
    task_rows = (
        await db.execute(
            _open_leads(
                select(FollowUp, Lead)
                .join(Lead, Lead.id == FollowUp.lead_id)
                .where(
                    FollowUp.status == FollowUpStatus.PENDING,
                    FollowUp.scheduled_for <= now,
                    Lead.preferred_channel.isnot(None),
                    Lead.preferred_channel.notin_(AUTOMATED_PREFERENCES),
                )
            )
            .order_by(FollowUp.scheduled_for)
            .limit(limit)
        )
    ).all()

    tasks = [
        ConsoleTask(
            follow_up_id=fu.id,
            scheduled_for=fu.scheduled_for,
            # Narrowed by the query above, so this is never None here.
            channel=lead.preferred_channel,  # type: ignore[arg-type]
            lead=ConsoleLead.model_validate(lead),
        )
        for fu, lead in task_rows
    ]

    # 2. Held: due, sendable in principle, but not getting through — either the
    # consent gate refused every channel (`consent_holds` is the counter the
    # worker increments, and only a consent hold may spend it) or the sends
    # themselves failed.
    #
    # Each kind gets its own budget. Sharing one `limit` across both means a
    # burst of one buries the other entirely, and a burst is exactly when this
    # page matters: a provider outage fails hundreds of rows in one sweep, and
    # every one of them is newer than the consent hold that has been sitting
    # there since yesterday. Ordering cannot fix that — whichever column leads,
    # the losing category is the one that disappears. Two queries can.
    async def _held(status_clause: ColumnElement[bool], budget: int) -> list[Any]:
        return (
            await db.execute(
                _open_leads(
                    select(FollowUp, Lead)
                    .join(Lead, Lead.id == FollowUp.lead_id)
                    .where(
                        status_clause,
                        or_(
                            Lead.preferred_channel.is_(None),
                            Lead.preferred_channel.in_(AUTOMATED_PREFERENCES),
                        ),
                    )
                )
                # Most recently touched first. Sorting by status put FAILED at the
                # head of every page, so the oldest dead rows crowded out the live
                # ones; sorting on the due date has the same flaw as filtering on
                # it, since a row that failed this morning can be weeks overdue.
                .order_by(FollowUp.updated_at.desc(), FollowUp.consent_holds.desc())
                .limit(budget)
            )
        ).all()

    # PENDING holds are the ones a person can act on right now (ask for consent,
    # or pick up the phone), so they must never be crowded out by delivery
    # failures — which is precisely what a shared limit did.
    # Postponed, not merely "not due yet". `attempts > 0` alone missed a row the
    # per-lead cap deferred without advancing the counter; widening it to
    # `scheduled_for > now` then matched every freshly booked follow-up in the
    # system and buried the real consent holds under them. `postponed_until`
    # says exactly this and nothing else.
    hold_rows = await _held(
        and_(
            FollowUp.status == FollowUpStatus.PENDING,
            or_(
                FollowUp.consent_holds > 0,
                FollowUp.postponed_until.is_not(None),
            ),
        ),
        limit,
    )
    # FAILED belongs here as much as PENDING — a provider outage marks every due
    # message FAILED, and with only PENDING the list stayed reassuringly empty
    # on the one morning it should have been full.
    #
    # But FAILED is terminal: nothing in the codebase ever moves a follow-up back
    # out of it. Unbounded, every failure that ever happened would sit here for
    # ever. Recent failures are news; a failure from March is history, and
    # history belongs on the analytics page. The window is measured on when it
    # FAILED, not when it was due: after a backlog the sweep picks up rows weeks
    # overdue and fails them today, and on `scheduled_for` those were invisible
    # from the moment they broke, in the one place they could have appeared.
    failed_rows = await _held(
        and_(
            FollowUp.status == FollowUpStatus.FAILED,
            FollowUp.updated_at >= now - timedelta(days=FAILED_WINDOW_DAYS),
        ),
        limit,
    )
    # Two statements, two snapshots: a hold the worker flips PENDING→FAILED
    # between them satisfies both predicates and comes back twice, with
    # contradictory badges on the two cards. The trigger is a sweep running
    # while the page loads — during the outage this page exists for.
    seen: set[int] = set()
    ranked = sorted(
        hold_rows + failed_rows,
        key=lambda row: (row[0].updated_at, row[0].consent_holds),
        reverse=True,
    )
    deduped = [row for row in ranked if not (row[0].id in seen or seen.add(row[0].id))]

    # `limit` means what it says. Taking the top `limit` of the merged list
    # would hand the whole page back to whichever kind is noisier — the thing
    # the two budgets exist to prevent — so take from each in turn instead:
    # neither can starve the other, and a caller asking for 50 gets 50.
    held_rows: list[Any] = []
    by_kind = {
        FollowUpStatus.PENDING: [r for r in deduped if r[0].status == FollowUpStatus.PENDING],
        FollowUpStatus.FAILED: [r for r in deduped if r[0].status == FollowUpStatus.FAILED],
    }
    while len(held_rows) < limit and any(by_kind.values()):
        for queue in by_kind.values():
            if queue and len(held_rows) < limit:
                held_rows.append(queue.pop(0))
    held_rows.sort(key=lambda row: (row[0].updated_at, row[0].consent_holds), reverse=True)

    held = [
        HeldFollowUp(
            follow_up_id=fu.id,
            scheduled_for=fu.scheduled_for,
            next_attempt_at=fu.postponed_until,
            holds=fu.consent_holds,
            status=fu.status,
            lead=ConsoleLead.model_validate(lead),
        )
        for fu, lead in held_rows
    ]

    # 3. Hot and untouched: highly ranked, and nobody has called them or heard
    # from them within the window. The subquery is on call_logs specifically —
    # an automated nurture message going out is not somebody having spoken to
    # them, and counting it as such is how a hot lead goes quiet for a month.
    # A lead already listed above is already on today's list. Showing them a
    # second time makes a short list look long and a scannable one look
    # repetitive, which is how a list stops being read.
    already_listed = {t.lead.id for t in tasks} | {h.lead.id for h in held}

    cutoff = now - timedelta(days=untouched_days)
    recent_call = (
        select(func.count())
        .select_from(CallLog)
        .where(CallLog.lead_id == Lead.id, CallLog.created_at >= cutoff)
        .scalar_subquery()
    )
    hot_rows = (
        await db.execute(
            _open_leads(
                select(Lead).where(
                    Lead.score >= HOT_SCORE,
                    recent_call == 0,
                    Lead.id.notin_(already_listed) if already_listed else true(),
                    or_(
                        Lead.last_message_at.is_(None),
                        Lead.last_message_at < cutoff,
                    ),
                )
            )
            .order_by(Lead.score.desc(), Lead.last_message_at.asc().nulls_first())
            .limit(limit)
        )
    ).scalars().all()

    return ConsoleToday(
        tasks=tasks,
        held=held,
        untouched_hot=[ConsoleLead.model_validate(row) for row in hot_rows],
        generated_at=now,
    )

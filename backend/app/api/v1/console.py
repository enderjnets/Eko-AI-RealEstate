"""The console's list of today.

Three things need somewhere to be seen, and until now two of them had nowhere:

* **Calls to make.** A follow-up for a lead who asked to be phoned or emailed
  has no automated sender behind it (see `followups.AUTOMATED_PREFERENCES`), so
  it is a job for a person. Without this list those rows would sit pending for
  ever and the preference would be a promise nobody keeps.
* **Held follow-ups.** The worker holds a message when no channel has consent
  or a prior inbound, retries daily, and gives up after a few rounds. Today
  that only ever appears in a log line, so the office cannot tell the
  difference between "we are nurturing them" and "we have been unable to say
  anything to them for a week".
* **Hot leads nobody has touched.** The scorer already ranks them; nothing
  surfaces the ones that are ranked highly and then left alone.

A list, not a dashboard. Anything that needs interpreting belongs on the
analytics page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import CallLog, FollowUp, FollowUpStatus, Lead, LeadStatus
from app.models.lead import PreferredChannel
from app.services.followups import AUTOMATED_PREFERENCES

router = APIRouter()

# Statuses that mean the relationship is not currently ours to work.
CLOSED_STATUSES = (LeadStatus.WON, LeadStatus.LOST, LeadStatus.PAUSED)

HOT_SCORE = 70


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
    """Due, but nothing may be sent: no channel has consent or a prior inbound."""

    follow_up_id: int
    scheduled_for: datetime
    holds: int
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

    # 2. Held: due, sendable in principle, but the consent gate refused every
    # channel. `attempts` is the hold counter the worker increments.
    held_rows = (
        await db.execute(
            _open_leads(
                select(FollowUp, Lead)
                .join(Lead, Lead.id == FollowUp.lead_id)
                .where(
                    FollowUp.status == FollowUpStatus.PENDING,
                    FollowUp.attempts > 0,
                    or_(
                        Lead.preferred_channel.is_(None),
                        Lead.preferred_channel.in_(AUTOMATED_PREFERENCES),
                    ),
                )
            )
            .order_by(FollowUp.attempts.desc(), FollowUp.scheduled_for)
            .limit(limit)
        )
    ).all()

    held = [
        HeldFollowUp(
            follow_up_id=fu.id,
            scheduled_for=fu.scheduled_for,
            holds=fu.attempts,
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

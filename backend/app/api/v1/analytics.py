"""Analytics API — funnel + conversion + channel/score/activity metrics (Phase 11).

All read-only aggregates over existing data. Backs the `/analytics` dashboard.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import Conversation, Lead, Message, MessageDirection

router = APIRouter()

_STATUS_ORDER = ["new", "qualified", "visiting", "post_visit", "won", "lost", "paused"]


class AnalyticsOut(BaseModel):
    total_leads: int
    funnel: dict[str, int]              # status -> count (all statuses, 0-filled)
    conversion_rate: float              # won / (won + lost), 0-1
    by_channel: dict[str, int]          # channel -> conversation count
    by_score_tier: dict[str, int]       # hot/warm/cold -> count
    leads_per_day: list[dict]           # [{date, count}] last 14 days
    avg_first_response_seconds: float | None


@router.get("", response_model=AnalyticsOut)
async def analytics(db: AsyncSession = Depends(get_db)) -> AnalyticsOut:
    total = (await db.execute(select(func.count()).select_from(Lead))).scalar_one()

    # Funnel by status.
    status_rows = (
        await db.execute(select(Lead.status, func.count()).group_by(Lead.status))
    ).all()
    counts = {s.value if hasattr(s, "value") else str(s): n for s, n in status_rows}
    funnel = {s: counts.get(s, 0) for s in _STATUS_ORDER}

    won, lost = funnel["won"], funnel["lost"]
    conversion_rate = round(won / (won + lost), 3) if (won + lost) else 0.0

    # Conversations by channel.
    chan_rows = (
        await db.execute(select(Conversation.channel, func.count()).group_by(Conversation.channel))
    ).all()
    by_channel = {str(c): n for c, n in chan_rows}

    # Score tiers.
    hot = (await db.execute(select(func.count()).select_from(Lead).where(Lead.score >= 67))).scalar_one()
    warm = (await db.execute(
        select(func.count()).select_from(Lead).where(Lead.score >= 34, Lead.score < 67)
    )).scalar_one()
    cold = (await db.execute(select(func.count()).select_from(Lead).where(Lead.score < 34))).scalar_one()
    by_score_tier = {"hot": hot, "warm": warm, "cold": cold}

    # Leads created per day, last 14 days.
    since = datetime.now(UTC) - timedelta(days=14)
    day_rows = (
        await db.execute(
            select(func.date(Lead.created_at).label("d"), func.count())
            .where(Lead.created_at >= since)
            .group_by(func.date(Lead.created_at))
            .order_by(func.date(Lead.created_at))
        )
    ).all()
    leads_per_day = [{"date": str(d), "count": n} for d, n in day_rows]

    # Avg first-response time: per conversation, first outbound minus first inbound.
    in_sub = (
        select(
            Message.conversation_id.label("cid"),
            func.min(Message.created_at).label("first_in"),
        )
        .where(Message.direction == MessageDirection.INBOUND)
        .group_by(Message.conversation_id)
        .subquery()
    )
    out_sub = (
        select(
            Message.conversation_id.label("cid"),
            func.min(Message.created_at).label("first_out"),
        )
        .where(Message.direction == MessageDirection.OUTBOUND)
        .group_by(Message.conversation_id)
        .subquery()
    )
    avg_resp = (
        await db.execute(
            select(func.avg(func.extract("epoch", out_sub.c.first_out - in_sub.c.first_in)))
            .select_from(in_sub.join(out_sub, in_sub.c.cid == out_sub.c.cid))
            .where(out_sub.c.first_out > in_sub.c.first_in)
        )
    ).scalar_one()
    avg_first_response_seconds = round(float(avg_resp), 1) if avg_resp is not None else None

    return AnalyticsOut(
        total_leads=total,
        funnel=funnel,
        conversion_rate=conversion_rate,
        by_channel=by_channel,
        by_score_tier=by_score_tier,
        leads_per_day=leads_per_day,
        avg_first_response_seconds=avg_first_response_seconds,
    )

"""Analytics API v2 — the whole funnel, in the agency's own days.

v1 answered five questions with no date range: how many leads, by status, by
channel, by score, and an average first response that counted internal notes as
replies. It could not say where anybody came from, whether the phone was ever
picked up, whether an appointment happened, or what kind of business closed —
because until this release none of that was recorded anywhere.

This replaces it rather than sitting beside it. The only consumer is our own
`/analytics` page, and two endpoints answering the same question differently is
how a dashboard starts disagreeing with itself.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import current_role
from app.db.base import get_db
from app.models import AgentSettings
from app.services import analytics as svc

router = APIRouter()

# A year and a day. Long enough for "the last twelve months", short enough that
# one request cannot walk the whole table and hold a connection while it does.
MAX_RANGE_DAYS = 366

_PRESETS = {"7d": 7, "30d": 30, "90d": 90}


class RangeOut(BaseModel):
    from_: date
    to: date
    timezone: str

    model_config = {"populate_by_name": True}


class AnalyticsOut(BaseModel):
    range: dict
    traffic: dict
    funnel: list[dict]
    leads: dict
    response: dict
    calls: dict
    appointments: dict
    deals: dict
    content: list[dict]
    by_agent: list[dict]


async def _agency_zone(db: AsyncSession) -> str:
    """The office's timezone, or Denver.

    A fresh organization has no settings row yet, and grouping its first days in
    UTC would put every evening lead on the following morning — a difference
    nobody notices because each number still looks plausible.
    """
    tz = (
        await db.execute(select(AgentSettings.timezone).limit(1))
    ).scalar_one_or_none()
    name = (tz or "").strip() or svc.DEFAULT_TZ
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return svc.DEFAULT_TZ
    return name


def _window(zone: str, preset: str, since: date | None, until: date | None) -> svc.Window:
    """Local dates in, UTC instants out.

    `to` is inclusive as a date and exclusive as an instant: asking for the 4th
    means everything up to the last microsecond of the 4th, which is what a
    person means and not what `<=` on a timestamp does.
    """
    tz = ZoneInfo(zone)
    if since is not None or until is not None:
        if since is None or until is None:
            raise HTTPException(
                status_code=422, detail="from_and_to_required: give both dates or neither"
            )
        if since > until:
            raise HTTPException(status_code=422, detail="inverted_range: from is after to")
        if (until - since).days > MAX_RANGE_DAYS:
            raise HTTPException(
                status_code=422,
                detail=f"range_too_wide: at most {MAX_RANGE_DAYS} days in one request",
            )
        first, last = since, until
    else:
        today = datetime.now(tz).date()
        first = today - timedelta(days=_PRESETS.get(preset, 30) - 1)
        last = today

    start = datetime.combine(first, datetime.min.time(), tzinfo=tz).astimezone(UTC)
    end = (
        datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    ).astimezone(UTC)
    return svc.Window(start=start, end=end, tz=zone)


@router.get("", response_model=AnalyticsOut)
async def analytics(
    range: Literal["7d", "30d", "90d"] = "30d",
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    role: str = Depends(current_role),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOut:
    zone = await _agency_zone(db)
    window = _window(zone, range, from_, to)

    traffic = await svc.traffic(db, window)
    return AnalyticsOut(
        range={
            "from": window.start.astimezone(ZoneInfo(zone)).date().isoformat(),
            "to": (
                window.end.astimezone(ZoneInfo(zone)) - timedelta(microseconds=1)
            ).date().isoformat(),
            "timezone": zone,
        },
        traffic=traffic,
        funnel=await svc.funnel(db, window, traffic),
        leads=await svc.leads(db, window),
        response=await svc.response(db, window),
        calls=await svc.calls(db, window),
        appointments=await svc.appointments(db, window),
        # The amount is the one number here that is not everyone's business.
        # The gate lives in the router because that is where the role is: the
        # service takes a boolean and cannot be tricked into deciding.
        deals=await svc.deals(db, window, with_value=role == "admin"),
        content=await svc.content(db, window),
        by_agent=await svc.by_agent(db, window),
    )

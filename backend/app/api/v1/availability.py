"""«My availability» — each agent declares when they can be booked.

**The whole authorisation model of this router is one sentence: the email comes
from the session token and from nowhere else.** There is no `email` path
parameter, no `email` field on any request body, and every schema is
`extra="forbid"` so sending one is a 422 rather than something to interpret. An
agent therefore cannot address another agent's schedule — not because a check
rejects them, but because there is no way to name a victim.

That is deliberate over the alternative (`PUT /availability/{email}` guarded by
a comparison), which is one forgotten `if` away from letting anyone rewrite
anyone's working hours.

Two consequences worth stating rather than discovering:

* The shared office password grants access **without identity** — `current_email`
  returns None for it, by design, because an attribution that is sometimes wrong
  is worse than one that is absent. So these routes refuse it. There is no "my"
  to read.
* The signed-in email must still be on the access list. The schema comment on
  `agent_calendars.email` claims a row "cannot belong to somebody who cannot
  sign in", and an audit of the migration pointed out that nothing enforced it —
  no foreign key, no check. This is where it is enforced, because this is the
  only writer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import current_email, require_admin
from app.db.base import get_db
from app.models import AgentCalendar, AgentSettings, AllowedUser, AppointmentActivity
from app.services.agent_calendar import (
    ACTIVITY_LABELS,
    CalComScheduleError,
    Window,
    ensure_calendar,
    get_windows,
    set_windows,
    undeliverable_reason,
    validate_windows,
)
from app.services.channel_identity import MissingChannelCredential
from app.services.tenant_context import get_org_id

router = APIRouter()

MAX_DURATION_MINUTES = 480


class WindowIn(BaseModel):
    """One weekly window. No `email` field here, and none anywhere else."""

    model_config = ConfigDict(extra="forbid")

    days: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(min_length=4, max_length=5)
    end: str = Field(min_length=4, max_length=5)

    @field_validator("days")
    @classmethod
    def _days_in_range(cls, v: list[int]) -> list[int]:
        if any(d not in range(7) for d in v):
            raise ValueError("days must be 0 (Monday) to 6 (Sunday)")
        return v


class WindowsPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: list[WindowIn] = Field(default_factory=list, max_length=20)
    duration_minutes: int | None = Field(default=None, ge=5, le=MAX_DURATION_MINUTES)
    active: bool | None = None


class ActivityOut(BaseModel):
    activity: str
    label: str
    duration_minutes: int
    active: bool
    # False while Cal.com has not been provisioned yet: the UI shows "setting
    # up" instead of an empty week that looks like a deliberate "never".
    configured: bool
    windows: list[WindowIn]


class AvailabilityOut(BaseModel):
    email: str
    timezone: str
    # Non-null means nothing here can work yet, and says why in words a person
    # can act on. A spinner would be the alternative.
    unavailable_reason: str | None
    activities: list[ActivityOut]


class TeamMemberOut(BaseModel):
    email: str
    activities: list[ActivityOut]


async def _office_timezone(db: AsyncSession) -> str:
    org_id = get_org_id()
    cfg = (
        await db.execute(select(AgentSettings).where(AgentSettings.org_id == org_id))
    ).scalar_one_or_none()
    return (cfg.timezone if cfg and cfg.timezone else "UTC") or "UTC"


async def _signed_in_agent(request: Request, db: AsyncSession) -> str:
    """The one place an email enters this router. Never from input."""
    email = current_email(request)
    if not email:
        raise HTTPException(
            status_code=403,
            detail=(
                "This page needs a personal sign-in. The shared office password "
                "grants access without an identity, so there is no 'my "
                "availability' to show. Sign in with Google."
            ),
        )
    allowed = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == email))
    ).scalar_one_or_none()
    if allowed is None:
        raise HTTPException(
            status_code=403,
            detail="This address is not on the team, so it cannot hold a schedule.",
        )
    return email


def _as_out(row: AgentCalendar, windows: list[Window]) -> ActivityOut:
    return ActivityOut(
        activity=row.activity.value,
        label=ACTIVITY_LABELS[row.activity],
        duration_minutes=row.duration_minutes,
        active=row.active,
        configured=bool(row.calcom_event_type_id),
        windows=[
            WindowIn(days=list(w.days), start=w.start, end=w.end) for w in windows
        ],
    )


@router.get("/me", response_model=AvailabilityOut)
async def read_my_availability(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AvailabilityOut:
    email = await _signed_in_agent(request, db)
    tz = await _office_timezone(db)

    blocked = undeliverable_reason()
    if blocked:
        # Report the rows we have without touching the network. The page still
        # renders, and it says why it is inert instead of failing.
        rows = (
            await db.execute(
                select(AgentCalendar).where(AgentCalendar.email == email)
            )
        ).scalars().all()
        by_activity = {r.activity: r for r in rows}
        return AvailabilityOut(
            email=email,
            timezone=tz,
            unavailable_reason=blocked,
            activities=[
                _as_out(by_activity[a], [])
                for a in AppointmentActivity
                if a in by_activity
            ],
        )

    out: list[ActivityOut] = []
    try:
        for activity in AppointmentActivity:
            row = await ensure_calendar(db, email, activity, timezone_name=tz)
            out.append(_as_out(row, await get_windows(row)))
        await db.commit()
    except MissingChannelCredential as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CalComScheduleError as exc:
        # The rows already written are worth keeping: a half-provisioned row is
        # resumed by the next call, not restarted, which is why the two Cal.com
        # ids are stored separately.
        await db.commit()
        raise HTTPException(
            status_code=502, detail=f"Cal.com did not answer as expected: {exc}"
        ) from exc
    return AvailabilityOut(
        email=email, timezone=tz, unavailable_reason=None, activities=out
    )


@router.put("/me/{activity}", response_model=ActivityOut)
async def set_my_availability(
    activity: AppointmentActivity,
    body: WindowsPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    email = await _signed_in_agent(request, db)
    tz = await _office_timezone(db)

    blocked = undeliverable_reason()
    if blocked:
        raise HTTPException(status_code=409, detail=blocked)

    windows = [Window(days=tuple(w.days), start=w.start, end=w.end) for w in body.windows]
    try:
        validate_windows(windows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        row = await ensure_calendar(db, email, activity, timezone_name=tz)
        if body.duration_minutes is not None:
            row.duration_minutes = body.duration_minutes
        if body.active is not None:
            row.active = body.active
        stored = await set_windows(row, windows, timezone_name=tz)
        await db.commit()
    except MissingChannelCredential as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CalComScheduleError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=502, detail=f"Cal.com did not answer as expected: {exc}"
        ) from exc
    return _as_out(row, stored)


@router.get("", response_model=list[TeamMemberOut], dependencies=[Depends(require_admin)])
async def read_team_availability(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[TeamMemberOut]:
    """Who can be booked when, across the agency. Admin **and** identified.

    `require_admin` alone was not enough, and an audit demonstrated it: the
    shared office password mints an admin token with no email
    (`auth.py`), so whoever answers the phone could read the whole team's
    working hours — and this endpoint publishes the staff roster of addresses.
    With AUTH_ENABLED off it answered anonymously. The module docstring already
    claimed these routes refuse an identity-less session; that claim was true of
    `/me` and false here, so the code now matches it.

    Reads what is stored and does not provision: a listing page must not create
    Cal.com objects for four activities times every team member as a side effect
    of somebody opening it.
    """
    await _signed_in_agent(request, db)
    rows = (
        await db.execute(select(AgentCalendar).order_by(AgentCalendar.email))
    ).scalars().all()
    grouped: dict[str, list[ActivityOut]] = {}
    for row in rows:
        grouped.setdefault(row.email, []).append(_as_out(row, []))
    return [TeamMemberOut(email=e, activities=a) for e, a in grouped.items()]

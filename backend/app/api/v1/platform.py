"""Platform operator routes — creating, suspending and entering client agencies.

These are the only endpoints that legitimately act across tenants, so they run
on the bypass session and are gated by `require_platform_admin` rather than
`require_admin`: the latter authorises the admin of *some* organization, and
every client agency has one.

Impersonation is deliberately explicit and recorded. The alternative — letting
the operator read every tenant ambiently — means one compromised account exposes
every client at once, and leaves no answer to "who looked at our data?".
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import (
    _set_session_cookie,
    _token_from_request,
    require_platform_admin,
)
from app.db.base import get_bypass_db
from app.models.organization import (
    DEMO_ORG_ID,
    PLAN_PILOT,
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
    Organization,
)
from app.services import tenant_resolver
from app.services.auth import ROLE_ADMIN, decode_token, make_token

router = APIRouter(dependencies=[Depends(require_platform_admin)])


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    status: str
    plan: str
    created_at: datetime


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    plan: str = Field(default=PLAN_PILOT, max_length=24)


class OrgStatusIn(BaseModel):
    status: str = Field(pattern=f"^({STATUS_ACTIVE}|{STATUS_SUSPENDED}|trial)$")


@router.get("/organizations", response_model=list[OrgOut])
async def list_organizations(db: AsyncSession = Depends(get_bypass_db)) -> list[OrgOut]:
    rows = (
        await db.execute(select(Organization).order_by(Organization.id))
    ).scalars().all()
    return [OrgOut.model_validate(r) for r in rows]


@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_organization(
    body: OrgCreateIn, db: AsyncSession = Depends(get_bypass_db)
) -> OrgOut:
    org = Organization(name=body.name.strip(), slug=body.slug, plan=body.plan)
    db.add(org)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="slug_already_exists") from exc
    await db.refresh(org)
    # The resolver caches the org list for 15s; without this a brand-new tenant
    # would be unroutable, and a suspension would keep working, for that long.
    tenant_resolver.reset_cache()
    return OrgOut.model_validate(org)


@router.patch("/organizations/{org_id}", response_model=OrgOut)
async def set_organization_status(
    org_id: int, body: OrgStatusIn, db: AsyncSession = Depends(get_bypass_db)
) -> OrgOut:
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    org.status = body.status
    await db.commit()
    await db.refresh(org)
    tenant_resolver.reset_cache()
    return OrgOut.model_validate(org)


@router.post("/impersonate/{org_id}")
async def impersonate(
    org_id: int,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict:
    """Swap the operator's session for one that acts inside `org_id`.

    Recorded before the cookie is issued, so the audit row exists even if the
    response never reaches the client. Suspended organizations are still
    enterable — that is usually exactly when an operator needs to look — which
    is what the `impersonating` mark on the token buys.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")

    # Name the operator, not just the org they entered. The audit row used to be
    # keyed on a synthetic "impersonation:org-N" address with the IP and user
    # agent hardcoded to None, so "who read our data on Tuesday?" could only be
    # answered with "someone". With PLATFORM_ADMIN_EMAILS there is a real actor
    # to record; it falls back to the anonymous form for a password session.
    from app.services.activity import client_ip, record_login

    claims = decode_token(_token_from_request(request)) or {}
    # Keyed on the pair, not on the operator alone: `record_login` upserts, so
    # a single "impersonation:<operator>" key would have one operator's visits
    # to agency B overwrite their visits to agency A. This is still a counter
    # with a last-seen, not a per-event log — enough to answer "who, which
    # agency, how often, most recently when", which is the open gap.
    actor = claims.get("email") or "shared-password"
    await record_login(
        db,
        email=f"impersonation:{actor}:org-{org_id}",
        source="impersonate",
        org_id=org_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(
        response,
        make_token(
            email=None, role=ROLE_ADMIN, org_id=org_id, impersonating=True
        ),
    )
    return {"ok": True, "org_id": org_id, "slug": org.slug}


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    channel: str
    destination: str
    label: str | None = None


class RouteCreateIn(BaseModel):
    org_id: int
    channel: str = Field(pattern=r"^(whatsapp|sms|email|voice)$")
    destination: str = Field(min_length=3, max_length=254)
    label: str | None = Field(default=None, max_length=120)


@router.get("/routes", response_model=list[RouteOut])
async def list_routes(db: AsyncSession = Depends(get_bypass_db)) -> list[RouteOut]:
    from app.models.channel_route import ChannelRoute

    rows = (
        await db.execute(select(ChannelRoute).order_by(ChannelRoute.id))
    ).scalars().all()
    return [RouteOut.model_validate(r) for r in rows]


@router.post("/routes", response_model=RouteOut, status_code=201)
async def create_route(
    body: RouteCreateIn, db: AsyncSession = Depends(get_bypass_db)
) -> RouteOut:
    """Point an inbound destination at an agency.

    Until a destination is mapped, inbound messages for a second tenant are
    refused rather than filed under the first — so this is the prerequisite for
    onboarding client number two.
    """
    from app.models.channel_route import ChannelRoute, normalize_destination

    org = (
        await db.execute(select(Organization).where(Organization.id == body.org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    if body.org_id == DEMO_ORG_ID:
        # Organization ids are small integers and the docs example uses 3, so a
        # typo lands here easily. The demo org is what `POST /auth/register`
        # drops anonymous visitors into as viewers, so a live route pointed at
        # it publishes real leads' phone numbers and transcripts.
        raise HTTPException(status_code=400, detail="cannot_route_to_demo_org")

    route = ChannelRoute(
        org_id=body.org_id,
        channel=body.channel,
        destination=normalize_destination(body.destination),
        label=body.label,
    )
    db.add(route)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # A destination belongs to exactly one agency; two claiming it is the
        # ambiguity this table exists to prevent.
        raise HTTPException(
            status_code=409, detail="destination_already_routed"
        ) from exc
    await db.refresh(route)
    return RouteOut.model_validate(route)


@router.delete("/routes/{route_id}")
async def delete_route(route_id: int, db: AsyncSession = Depends(get_bypass_db)) -> dict:
    from app.models.channel_route import ChannelRoute

    route = (
        await db.execute(select(ChannelRoute).where(ChannelRoute.id == route_id))
    ).scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="route_not_found")
    await db.delete(route)
    await db.commit()
    return {"ok": True}


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    # `viewer` is deliberately absent. It is a role of the `accounts` table, not
    # of `allowed_users`: `resolve_email_access` reads anything that is not
    # "admin" as a member, so inviting a read-only auditor as `viewer` silently
    # handed them write access to the agency's leads. The team router restricts
    # this to the same two values.
    role: str = Field(default="admin", pattern=r"^(admin|member)$")


@router.post("/organizations/{org_id}/members", status_code=201)
async def invite_member(
    org_id: int, body: InviteIn, db: AsyncSession = Depends(get_bypass_db)
) -> dict:
    """Give a person access to a client agency.

    The last step of onboarding: without it a newly created organization has no
    one who can log into it, so `create_organization` on its own produces a
    tenant nobody can reach.

    Runs on the bypass session because the operator is acting on a tenant that
    is not their own — `add_member` in the team router does the same job from
    inside an agency, scoped by RLS.
    """
    from app.api.v1.team import _norm_email
    from app.models import AllowedUser

    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    if org.status == "suspended":
        # The row would be created and the sign-in would then 403 at the
        # suspension gate, which reads as "the invite silently did nothing".
        raise HTTPException(status_code=409, detail="organization_is_suspended")

    # An unvalidated string here is not cosmetic: `allowed_users.email` is
    # globally unique, so a typo permanently consumes the slot for a real
    # address and can only be removed by an admin of that org — who may be the
    # very person being invited.
    email = _norm_email(body.email)
    row = AllowedUser(email=email, role=body.role, added_by="platform", org_id=org_id)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Email is globally unique — identity is one person, one organization —
        # so this is the operator being told the person already belongs
        # somewhere, not a constraint surprising them.
        raise HTTPException(
            status_code=409, detail="email_already_belongs_to_an_organization"
        ) from exc
    await db.refresh(row)
    return {"id": row.id, "email": row.email, "role": row.role, "org_id": org_id}

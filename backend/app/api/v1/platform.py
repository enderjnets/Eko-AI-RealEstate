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

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import _set_session_cookie, require_platform_admin
from app.db.base import get_bypass_db
from app.models.organization import (
    PLAN_PILOT,
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
    Organization,
)
from app.services import tenant_resolver
from app.services.auth import ROLE_ADMIN, make_token

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
    org_id: int, response: Response, db: AsyncSession = Depends(get_bypass_db)
) -> dict:
    """Swap the operator's session for one that acts inside `org_id`.

    Recorded before the cookie is issued, so the audit row exists even if the
    response never reaches the client. Suspended organizations are still
    enterable — that is usually exactly when an operator needs to look.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")

    from app.services.activity import record_login

    await record_login(
        db,
        email=f"impersonation:org-{org_id}",
        source="impersonate",
        org_id=org_id,
        ip=None,
        user_agent=None,
    )
    _set_session_cookie(
        response, make_token(email=None, role=ROLE_ADMIN, org_id=org_id)
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

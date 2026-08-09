"""Properties API — listings list/detail + sync + per-lead matches (Phase 7)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_platform_admin
from app.db.base import get_db
from app.models import Lead, Property, PropertySource, PropertyStatus, SyncState
from app.services.listings import RESO_SOURCE_KEY, match_properties_for_lead, sync_listings

router = APIRouter()
lead_matches_router = APIRouter()


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: PropertySource
    external_id: str
    status: PropertyStatus
    title: str
    description: str | None
    property_type: str | None
    address: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    zone: str | None
    price: Decimal | None
    bedrooms: int | None
    bathrooms: Decimal | None
    sqft: int | None
    url: str | None
    photos: list
    listed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PropertyListOut(BaseModel):
    total: int
    items: list[PropertyOut]


class SyncResult(BaseModel):
    created: int
    updated: int
    total: int


@router.get("", response_model=PropertyListOut)
async def list_properties(
    status_filter: PropertyStatus | None = Query(default=None, alias="status"),
    source: PropertySource | None = Query(default=None),
    city: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    property_type: str | None = Query(default=None),
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PropertyListOut:
    where: list = []
    if status_filter is not None:
        where.append(Property.status == status_filter)
    if source is not None:
        where.append(Property.source == source)
    if city:
        where.append(Property.city.ilike(f"%{city}%"))
    if zone:
        where.append(Property.zone.ilike(f"%{zone}%"))
    if property_type:
        where.append(Property.property_type.ilike(f"%{property_type}%"))
    if min_price is not None:
        where.append(Property.price >= min_price)
    if max_price is not None:
        where.append(Property.price <= max_price)

    total = (await db.execute(select(func.count()).select_from(Property).where(*where))).scalar_one()
    rows = (
        await db.execute(
            select(Property)
            .where(*where)
            .order_by(Property.price.asc().nullslast(), Property.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return PropertyListOut(total=total, items=[PropertyOut.model_validate(r) for r in rows])


@router.post(
    "/sync",
    response_model=SyncResult,
    dependencies=[Depends(require_platform_admin)],
)
async def sync_properties(
    city: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> SyncResult:
    """Ingest listings from the configured feed (SIMULATED curated set or RESO).

    Operator-only. `properties` and `sync_state` are deliberately shared — there
    is one REcolorado feed — so this drives a resource every agency depends on:
    the licence quota, and the cursor that decides what the next run fetches.
    Behind `require_auth` alone, any member of any agency could exhaust the
    quota or move the cursor for everyone.
    """
    result = await sync_listings(db, city=city)
    return SyncResult(**result)


class SyncStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    cursor_modified_at: datetime | None = None
    last_run_at: datetime | None = None
    last_created: int = 0
    last_updated: int = 0
    last_error: str | None = None


# Declared before /{property_id} so "sync-status" is not parsed as an id.
@router.get("/sync-status", response_model=SyncStatusOut | None)
async def get_sync_status(
    request: Request, db: AsyncSession = Depends(get_db)
) -> SyncStatusOut | None:
    """Replication health for the MLS Grid feed — the only window into the background
    worker, which otherwise fails silently in the logs. Null before the first run."""
    row = (
        await db.execute(select(SyncState).where(SyncState.source == RESO_SOURCE_KEY))
    ).scalar_one_or_none()
    if row is None:
        return None
    out = SyncStatusOut.model_validate(row)
    # `last_error` is the provider's own message about a feed every agency
    # shares, so it can name the operator's account, quota or credentials.
    # Agencies see whether replication is healthy; only the operator sees why
    # it is not.
    from app.api.v1.auth import _token_from_request
    from app.services.auth import token_is_superuser

    if out.last_error and not token_is_superuser(_token_from_request(request)):
        out = out.model_copy(update={"last_error": "unavailable"})
    return out


@router.get("/{property_id}", response_model=PropertyOut)
async def get_property(property_id: int, db: AsyncSession = Depends(get_db)) -> PropertyOut:
    row = (await db.execute(select(Property).where(Property.id == property_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return PropertyOut.model_validate(row)


@lead_matches_router.get("/leads/{lead_id}/matches", response_model=list[PropertyOut])
async def get_lead_matches(
    lead_id: int,
    limit: int = Query(default=6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[PropertyOut]:
    """Active listings that fit the lead's intent / zone / budget / property type."""
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    matches = await match_properties_for_lead(lead, db, limit=limit)
    return [PropertyOut.model_validate(p) for p in matches]

"""Leads API — list + detail. Dashboard CRUD lives in Phase 2."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import Lead, LeadIntent, LeadStatus

router = APIRouter()


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    name: str | None
    status: LeadStatus
    intent: LeadIntent | None
    budget_min: Decimal | None
    budget_max: Decimal | None
    zone: str | None
    property_type: str | None
    urgency: str | None
    human_takeover: bool
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadListOut(BaseModel):
    total: int
    items: list[LeadOut]


@router.get("", response_model=LeadListOut)
async def list_leads(
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    intent: LeadIntent | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> LeadListOut:
    where: list = []
    if status_filter is not None:
        where.append(Lead.status == status_filter)
    if intent is not None:
        where.append(Lead.intent == intent)

    total = (await db.execute(select(func.count()).select_from(Lead).where(*where))).scalar_one()
    rows = (
        await db.execute(
            select(Lead)
            .where(*where)
            .order_by(Lead.last_message_at.desc().nullslast(), Lead.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return LeadListOut(total=total, items=[LeadOut.model_validate(r) for r in rows])


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db)) -> LeadOut:
    row = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return LeadOut.model_validate(row)

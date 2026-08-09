"""Discovery API — search business leads + import from a file (Phase 12).

Search and upload return transient results (not persisted); the dashboard shows a
preview and the user imports the selected ones via /import (which creates Lead rows).
All protected by require_auth (mounted in main.py).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_platform_admin
from app.config import get_settings
from app.db.base import get_db
from app.models import Lead
from app.services.discovery import LEAD_CATEGORIES, BusinessDTO, discover, import_business_leads
from app.services.enrichment import enrich_lead, enrich_pending_leads
from app.services.file_import import extract_leads, extract_text

log = logging.getLogger(__name__)
router = APIRouter()

# Discovery drives providers the OPERATOR pays for — Outscraper, Yelp, SerpApi —
# and the shared LLM budget, none of which is metered per agency. Behind
# `require_auth` alone, one tenant looping a search at max_results could drain
# credit that every other tenant's inbound replies depend on. Same reasoning as
# the shared MLS feed: operator-funded, so operator-gated, until there is a
# per-organization quota to charge it against.



class BusinessOut(BaseModel):
    business_name: str
    source: str
    category: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    motivation: str | None = None
    timeline: str | None = None
    property_type: str | None = None
    est_value: str | None = None


class ResultsOut(BaseModel):
    results: list[BusinessOut]


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(default="fsbo")  # a LEAD_CATEGORIES value
    query: str = Field(default="", max_length=200)  # optional free-text refine
    city: str = Field(default="", max_length=120)
    state: str = Field(default="CO", max_length=40)
    max_results: int = Field(default=50, ge=1, le=100)


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    leads: list[BusinessOut]
    source_label: str = "discovery"


class ImportResult(BaseModel):
    created: int
    skipped: int
    total: int
    lead_ids: list[int] = []


class EnrichResult(BaseModel):
    lead_id: int
    name: str | None = None
    enrichment: dict


def _dto(b: BusinessOut) -> BusinessDTO:
    return BusinessDTO(
        business_name=b.business_name, source=b.source, category=b.category,
        email=b.email, phone=b.phone, website=b.website, address=b.address,
        city=b.city, state=b.state, motivation=b.motivation, timeline=b.timeline,
        property_type=b.property_type, est_value=b.est_value,
    )


@router.post("/search", response_model=ResultsOut, dependencies=[Depends(require_platform_admin)])
async def search(body: SearchIn) -> ResultsOut:
    if body.category not in LEAD_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Unknown category: {body.category}")
    results = await discover(
        query=body.query, city=body.city, state=body.state,
        max_results=body.max_results, category=body.category,
    )
    return ResultsOut(results=[BusinessOut(**b.to_public()) for b in results])


@router.post("/upload", response_model=ResultsOut, dependencies=[Depends(require_platform_admin)])
async def upload(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> ResultsOut:
    s = get_settings()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > s.FILE_IMPORT_MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {s.FILE_IMPORT_MAX_MB} MB")

    text = extract_text(file.filename or "upload", content)
    if not text.strip():
        return ResultsOut(results=[])
    leads = await extract_leads(text)
    return ResultsOut(results=[BusinessOut(**b.to_public()) for b in leads])


@router.post("/import", response_model=ImportResult, dependencies=[Depends(require_platform_admin)])
async def do_import(body: ImportIn, db: AsyncSession = Depends(get_db)) -> ImportResult:
    if not body.leads:
        raise HTTPException(status_code=400, detail="No leads to import")
    result = await import_business_leads(
        [_dto(b) for b in body.leads], db, source_label=body.source_label
    )
    return ImportResult(**result)


@router.post("/enrich/{lead_id}", response_model=EnrichResult, dependencies=[Depends(require_platform_admin)])
async def enrich(lead_id: int, db: AsyncSession = Depends(get_db)) -> EnrichResult:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    enrichment = await enrich_lead(lead, db)
    return EnrichResult(lead_id=lead.id, name=lead.name, enrichment=enrichment)


@router.post("/enrich-pending", dependencies=[Depends(require_platform_admin)])
async def enrich_pending(
    limit: int = 25, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    """Enrich any discovery lead still unclassified (score 0) — backfill / manual sweep."""
    return await enrich_pending_leads(db, limit=max(1, min(100, limit)))

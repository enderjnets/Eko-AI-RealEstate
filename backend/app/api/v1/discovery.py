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

from app.config import get_settings
from app.db.base import get_db
from app.models import Lead
from app.services.discovery import VALID_SOURCES, BusinessDTO, discover, import_business_leads
from app.services.enrichment import enrich_lead
from app.services.file_import import extract_leads, extract_text

log = logging.getLogger(__name__)
router = APIRouter()


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


class ResultsOut(BaseModel):
    results: list[BusinessOut]


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=200)
    city: str = Field(default="", max_length=120)
    state: str = Field(default="CO", max_length=40)
    max_results: int = Field(default=50, ge=1, le=100)
    sources: list[str] = Field(default_factory=lambda: ["google_maps"])


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
        city=b.city, state=b.state,
    )


@router.post("/search", response_model=ResultsOut)
async def search(body: SearchIn) -> ResultsOut:
    bad = [s for s in body.sources if s not in VALID_SOURCES]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown sources: {bad}")
    results = await discover(
        query=body.query, city=body.city, state=body.state,
        max_results=body.max_results, sources=body.sources,
    )
    return ResultsOut(results=[BusinessOut(**b.to_public()) for b in results])


@router.post("/upload", response_model=ResultsOut)
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


@router.post("/import", response_model=ImportResult)
async def do_import(body: ImportIn, db: AsyncSession = Depends(get_db)) -> ImportResult:
    if not body.leads:
        raise HTTPException(status_code=400, detail="No leads to import")
    result = await import_business_leads(
        [_dto(b) for b in body.leads], db, source_label=body.source_label
    )
    return ImportResult(**result)


@router.post("/enrich/{lead_id}", response_model=EnrichResult)
async def enrich(lead_id: int, db: AsyncSession = Depends(get_db)) -> EnrichResult:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    enrichment = await enrich_lead(lead, db)
    return EnrichResult(lead_id=lead.id, name=lead.name, enrichment=enrichment)

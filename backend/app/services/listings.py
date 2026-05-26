"""Listings service — ingest MLS/IDX properties + match them to a lead.

When LISTINGS_SIMULATED=true (dev default), `fetch_listings` returns a curated
set of Miami listings in-memory — no MLS account needed. `sync_listings` upserts
them into the `properties` table. The dashboard + agent matching then work end to
end without any external feed.

When SIMULATED is off, `fetch_listings` queries a RESO Web API (OData) feed with
RESO_BASE_URL + RESO_ACCESS_TOKEN. RESO Web API is the USA MLS standard; the field
mapping (ListingKey, UnparsedAddress, ListPrice, BedroomsTotal…) lives here, so a
real pilot only needs env vars — no schema/orchestrator changes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Lead, LeadIntent, Property, PropertySource, PropertyStatus

log = logging.getLogger(__name__)

NOW = datetime.now(UTC)


class ListingsError(RuntimeError):
    pass


@dataclass
class ListingDTO:
    external_id: str
    title: str
    price: Decimal | None
    listing_type: str = "sale"  # "sale" | "rent" — drives intent matching
    status: PropertyStatus = PropertyStatus.ACTIVE
    property_type: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    zone: str | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    sqft: int | None = None
    url: str | None = None
    photos: list[str] = field(default_factory=list)
    listed_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _d(value: str | int | float) -> Decimal:
    return Decimal(str(value))


# ── Curated SIMULATED listings (Sunset Realty Group, Miami) ────────────────
# Zones line up with the demo leads so the dashboard's matches look alive.
_SIMULATED: list[ListingDTO] = [
    ListingDTO(
        external_id="SIM-BRK-001", title="High-floor 2BR condo with bay views — Brickell",
        price=_d(799000), listing_type="sale", property_type="condo", zone="Brickell",
        address="1300 Brickell Bay Dr #4502", city="Miami", state="FL", zip_code="33131",
        bedrooms=2, bathrooms=_d("2.0"), sqft=1180, url="https://example.com/listings/SIM-BRK-001",
        description="Floor-to-ceiling windows, 2 parking spaces, resort amenities.",
    ),
    ListingDTO(
        external_id="SIM-BRK-002", title="Modern 2BR in the heart of Brickell",
        price=_d(720000), listing_type="sale", property_type="condo", zone="Brickell",
        address="55 SW 9th St #2204", city="Miami", state="FL", zip_code="33130",
        bedrooms=2, bathrooms=_d("2.0"), sqft=1050, url="https://example.com/listings/SIM-BRK-002",
        description="Walk to Brickell City Centre. Includes 1 parking space.",
    ),
    ListingDTO(
        external_id="SIM-CG-001", title="Coral Gables family home with pool",
        price=_d(1195000), listing_type="sale", property_type="single_family", zone="Coral Gables",
        address="812 Malaga Ave", city="Coral Gables", state="FL", zip_code="33134",
        bedrooms=4, bathrooms=_d("3.0"), sqft=2650, url="https://example.com/listings/SIM-CG-001",
        description="Renovated 4/3 with heated pool, 2-car garage, top school district.",
    ),
    ListingDTO(
        external_id="SIM-CG-002", title="Grand 5BR estate — Coral Gables",
        price=_d(1450000), listing_type="sale", property_type="single_family", zone="Coral Gables",
        address="1500 Country Club Prado", city="Coral Gables", state="FL", zip_code="33134",
        bedrooms=5, bathrooms=_d("4.5"), sqft=3800, url="https://example.com/listings/SIM-CG-002",
        description="Mediterranean estate with guest house.",
    ),
    ListingDTO(
        external_id="SIM-DOR-001", title="2BR apartment for rent — Doral, gym + pool",
        price=_d(2750), listing_type="rent", property_type="apartment", zone="Doral",
        address="5300 NW 87th Ave #312", city="Doral", state="FL", zip_code="33178",
        bedrooms=2, bathrooms=_d("2.0"), sqft=1100, url="https://example.com/listings/SIM-DOR-001",
        description="Gated community, fitness center, resort pool. Available next month.",
    ),
    ListingDTO(
        external_id="SIM-DOR-002", title="Cozy 2BR rental near Downtown Doral",
        price=_d(2600), listing_type="rent", property_type="apartment", zone="Doral",
        address="8400 NW 52nd St #210", city="Doral", state="FL", zip_code="33166",
        bedrooms=2, bathrooms=_d("2.0"), sqft=980, url="https://example.com/listings/SIM-DOR-002",
        description="Walk to Downtown Doral shops and restaurants.",
    ),
    ListingDTO(
        external_id="SIM-WYN-001", title="Wynwood loft — 1BR with private terrace",
        price=_d(639000), listing_type="sale", property_type="loft", zone="Wynwood",
        address="250 NW 24th St #410", city="Miami", state="FL", zip_code="33127",
        bedrooms=1, bathrooms=_d("1.5"), sqft=1150, url="https://example.com/listings/SIM-WYN-001",
        description="Industrial-chic loft in the arts district.",
    ),
    ListingDTO(
        external_id="SIM-EDG-001", title="Edgewater income property — 4 units",
        price=_d(2900000), listing_type="sale", property_type="multi_unit", zone="Edgewater",
        address="500 NE 29th St", city="Miami", state="FL", zip_code="33137",
        bedrooms=8, bathrooms=_d("4.0"), sqft=4200, url="https://example.com/listings/SIM-EDG-001",
        description="Value-add 4-plex, walking distance to the bay. Strong rental demand.",
    ),
    ListingDTO(
        external_id="SIM-LH-001", title="1BR rental in Little Havana",
        price=_d(1950), listing_type="rent", property_type="apartment", zone="Little Havana",
        address="1450 SW 8th St #3", city="Miami", state="FL", zip_code="33135",
        bedrooms=1, bathrooms=_d("1.0"), sqft=620, url="https://example.com/listings/SIM-LH-001",
        description="Charming unit steps from Calle Ocho.",
    ),
]


# ── Fetch ──────────────────────────────────────────────────────────────────


async def fetch_listings(*, city: str | None = None, limit: int = 200) -> list[ListingDTO]:
    """Return listings from the configured feed (SIMULATED curated set or RESO)."""
    s = get_settings()

    if s.LISTINGS_SIMULATED:
        items = _SIMULATED
        if city:
            items = [x for x in items if (x.city or "").lower() == city.lower()]
        return items[:limit]

    if not s.RESO_BASE_URL or not s.RESO_ACCESS_TOKEN:
        raise ListingsError(
            "MLS feed not configured: RESO_BASE_URL + RESO_ACCESS_TOKEN must be set, "
            "or set LISTINGS_SIMULATED=true for dev."
        )
    return await _fetch_reso(s.RESO_BASE_URL, s.RESO_ACCESS_TOKEN, city=city, limit=limit)


async def _fetch_reso(base_url: str, token: str, *, city: str | None, limit: int) -> list[ListingDTO]:
    """Query a RESO Web API (OData) feed and map to ListingDTO."""
    filt = "StandardStatus eq 'Active'"
    if city:
        filt += f" and City eq '{city}'"
    params = {"$filter": filt, "$top": str(min(limit, 200)), "$orderby": "ModificationTimestamp desc"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/Property",
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            log.error("RESO fetch failed: %d %s", resp.status_code, resp.text[:300])
            raise ListingsError(f"RESO HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()

    out: list[ListingDTO] = []
    for r in payload.get("value", []):
        key = str(r.get("ListingKey") or r.get("ListingId") or "")
        if not key:
            continue
        media = r.get("Media") or []
        photos = [m.get("MediaURL") for m in media if isinstance(m, dict) and m.get("MediaURL")][:12]
        sub = (r.get("PropertySubType") or "").lower()
        listing_type = "rent" if "lease" in sub or "rent" in sub else "sale"
        out.append(
            ListingDTO(
                external_id=key,
                title=r.get("UnparsedAddress") or f"Listing {key}",
                price=_d(r["ListPrice"]) if r.get("ListPrice") is not None else None,
                listing_type=listing_type,
                property_type=r.get("PropertySubType") or r.get("PropertyType"),
                description=r.get("PublicRemarks"),
                address=r.get("UnparsedAddress"),
                city=r.get("City"),
                state=r.get("StateOrProvince"),
                zip_code=r.get("PostalCode"),
                zone=r.get("SubdivisionName") or r.get("MLSAreaMajor"),
                bedrooms=r.get("BedroomsTotal"),
                bathrooms=_d(r["BathroomsTotalInteger"]) if r.get("BathroomsTotalInteger") is not None else None,
                sqft=r.get("LivingArea"),
                url=r.get("ListingURL"),
                photos=photos,
                raw={"reso_key": key, "listing_type": listing_type},
            )
        )
    return out


# ── Sync (upsert into the DB) ───────────────────────────────────────────────


async def sync_listings(db: AsyncSession, *, city: str | None = None) -> dict[str, int]:
    """Fetch listings and upsert into `properties` by (source, external_id).

    Returns counts {created, updated, total}. Source is RESO when a real feed is
    configured, MANUAL when SIMULATED.
    """
    s = get_settings()
    source = PropertySource.MANUAL if s.LISTINGS_SIMULATED else PropertySource.RESO
    listings = await fetch_listings(city=city)

    created = updated = 0
    for dto in listings:
        existing = (
            await db.execute(
                select(Property).where(
                    Property.source == source, Property.external_id == dto.external_id
                )
            )
        ).scalar_one_or_none()

        raw = dict(dto.raw)
        raw.setdefault("listing_type", dto.listing_type)

        if existing is None:
            db.add(
                Property(
                    source=source,
                    external_id=dto.external_id,
                    status=dto.status,
                    title=dto.title,
                    description=dto.description,
                    property_type=dto.property_type,
                    address=dto.address,
                    city=dto.city,
                    state=dto.state,
                    zip_code=dto.zip_code,
                    zone=dto.zone,
                    price=dto.price,
                    bedrooms=dto.bedrooms,
                    bathrooms=dto.bathrooms,
                    sqft=dto.sqft,
                    url=dto.url,
                    photos=dto.photos,
                    listed_at=dto.listed_at,
                    raw=raw,
                )
            )
            created += 1
        else:
            existing.status = dto.status
            existing.title = dto.title
            existing.description = dto.description
            existing.property_type = dto.property_type
            existing.address = dto.address
            existing.city = dto.city
            existing.state = dto.state
            existing.zip_code = dto.zip_code
            existing.zone = dto.zone
            existing.price = dto.price
            existing.bedrooms = dto.bedrooms
            existing.bathrooms = dto.bathrooms
            existing.sqft = dto.sqft
            existing.url = dto.url
            existing.photos = dto.photos
            existing.raw = raw
            updated += 1

    await db.commit()
    log.info("Listings sync: source=%s created=%d updated=%d", source.value, created, updated)
    return {"created": created, "updated": updated, "total": created + updated}


# ── Matching ─────────────────────────────────────────────────────────────────


async def match_properties_for_lead(lead: Lead, db: AsyncSession, *, limit: int = 6) -> list[Property]:
    """Return active listings that fit the lead's criteria, best first.

    Matches on intent (rent vs sale), neighborhood (`zone`), budget, and property
    type. Lead has no bedroom field, so beds are not filtered.
    """
    rows = (
        await db.execute(select(Property).where(Property.status == PropertyStatus.ACTIVE))
    ).scalars().all()

    want_rent = lead.intent == LeadIntent.RENT
    out: list[Property] = []
    for p in rows:
        listing_type = (p.raw or {}).get("listing_type", "sale")
        # Intent gate: rent leads see rentals; everyone else sees sales.
        if want_rent and listing_type != "rent":
            continue
        if not want_rent and listing_type == "rent":
            continue

        if lead.zone and p.zone:
            if lead.zone.lower() not in p.zone.lower() and p.zone.lower() not in lead.zone.lower():
                continue
        if lead.property_type and p.property_type:
            if lead.property_type.lower() not in p.property_type.lower():
                continue
        if lead.budget_max is not None and p.price is not None:
            # 10% headroom over the stated max.
            if p.price > lead.budget_max * Decimal("1.10"):
                continue
        if lead.budget_min is not None and p.price is not None:
            if p.price < lead.budget_min * Decimal("0.90"):
                continue
        out.append(p)

    out.sort(key=lambda p: (p.price if p.price is not None else Decimal("0")))
    return out[:limit]

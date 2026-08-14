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

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import String, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Lead, LeadIntent, Property, PropertySource, PropertyStatus, SyncState

log = logging.getLogger(__name__)


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
    source_modified_at: datetime | None = None  # RESO ModificationTimestamp (for the sync cursor)
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


async def fetch_listings(
    *, city: str | None = None, limit: int = 200, modified_since: datetime | None = None
) -> list[ListingDTO]:
    """Return listings from the configured feed (SIMULATED curated set or RESO).

    `modified_since` applies only to the real RESO feed (incremental replication);
    the SIMULATED set ignores it.
    """
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
    out: list[ListingDTO] = []
    async for page in _fetch_reso_pages(
        s.RESO_BASE_URL,
        s.RESO_ACCESS_TOKEN,
        modified_since=modified_since,
        city=city,
        page_size=min(limit, s.RESO_PAGE_SIZE),
        max_pages=s.RESO_MAX_PAGES,
    ):
        out.extend(page.listings)
        if len(out) >= limit:
            return out[:limit]
    return out


# ── RESO Web API (OData) adapter — MLS Grid / REcolorado ─────────────────────

RESO_SOURCE_KEY = "reso"  # SyncState.source for the REcolorado/MLS Grid feed

# StandardStatus (RESO) → our PropertyStatus. Lower-cased keys; unknown → OFF_MARKET
# (safe default: never shown to a lead). VERIFY the exact status set REcolorado emits.
_STATUS_MAP: dict[str, PropertyStatus] = {
    "active": PropertyStatus.ACTIVE,
    "active under contract": PropertyStatus.PENDING,
    "pending": PropertyStatus.PENDING,
    "closed": PropertyStatus.SOLD,
    "canceled": PropertyStatus.OFF_MARKET,
    "cancelled": PropertyStatus.OFF_MARKET,
    "withdrawn": PropertyStatus.OFF_MARKET,
    "expired": PropertyStatus.OFF_MARKET,
    "hold": PropertyStatus.OFF_MARKET,
    "incomplete": PropertyStatus.OFF_MARKET,
    "delete": PropertyStatus.OFF_MARKET,
    "coming soon": PropertyStatus.OFF_MARKET,  # not publicly showable yet → out of matches
}

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 0.5  # seconds; exponential backoff. Patched to ~0 in tests.

# MLS Grid caps a request at 5000 records, but drops the cap to 1000 as soon as
# $expand is used — and we always expand Media. $top above this errors out.
_MAX_TOP_WITH_EXPAND = 1000


def _map_status(standard_status: str | None, mlg_can_view: object = None) -> PropertyStatus:
    """RESO StandardStatus → PropertyStatus. MLS Grid's MlgCanView=false means we may
    not display the record → force OFF_MARKET regardless of its status."""
    if mlg_can_view is False:
        return PropertyStatus.OFF_MARKET
    return _STATUS_MAP.get((standard_status or "").strip().lower(), PropertyStatus.OFF_MARKET)


def _parse_dt(value: object) -> datetime | None:
    """Parse a RESO ISO-8601 timestamp (…Z / offset) into a tz-aware datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _odata_str(value: str) -> str:
    """A single-quoted OData string literal, escaping embedded quotes ('')."""
    return "'" + value.replace("'", "''") + "'"


def _odata_dt(dt: datetime) -> str:
    """OData v4 Edm.DateTimeOffset literal — bare (no quotes), millisecond precision.

    MLS Grid stamps ModificationTimestamp to the millisecond ("…T00:55:41.516Z").
    Truncating to the second makes the `ge` cursor re-scan a whole second every run,
    and would silently skip records if it were ever switched to `gt`.
    """
    u = dt.astimezone(UTC)
    return f"{u.strftime('%Y-%m-%dT%H:%M:%S')}.{u.microsecond // 1000:03d}Z"


def _city_matches(dto: ListingDTO, city: str | None) -> bool:
    return not city or (dto.city or "").strip().lower() == city.strip().lower()


def _backoff(attempt: int) -> float:
    return min(_RETRY_BASE_DELAY * (2**attempt), 8.0)


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _reso_client() -> httpx.AsyncClient:
    """Build the HTTP client for RESO calls. Isolated so tests inject a MockTransport
    by monkeypatching this function."""
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
    transport = httpx.AsyncHTTPTransport(retries=2)  # connection-level retries
    return httpx.AsyncClient(timeout=timeout, transport=transport)


async def _reso_get(
    client: httpx.AsyncClient, url: str, token: str, params: dict | None
) -> dict:
    """GET one RESO page, retrying with backoff on 429/5xx/timeouts (honors Retry-After)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        # Required by MLS Grid: every response is compressed.
        "Accept-Encoding": "gzip,deflate",
    }
    attempt = 0
    while True:
        try:
            resp = await client.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= _MAX_RETRIES:
                raise ListingsError(f"RESO request failed after retries: {exc}") from exc
            await asyncio.sleep(_backoff(attempt))
            attempt += 1
            continue
        if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            await asyncio.sleep(_retry_after(resp) or _backoff(attempt))
            attempt += 1
            continue
        if resp.status_code >= 400:
            log.error("RESO fetch failed: %d %s", resp.status_code, resp.text[:300])
            raise ListingsError(f"RESO HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()


_PROPERTY_WIDTHS = {
    column.name: column.type.length
    for column in Property.__table__.columns
    if isinstance(column.type, String) and column.type.length
}


# Written as codes, not prose. Truncating one produces a value that is wrong
# rather than short — "Colorado" becoming "Co" is not a two-letter state, it is
# a state that does not exist — and wrong survives every check downstream while
# short does not.
_US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def _state_code(value: object) -> str | None:
    """A two-letter code, or nothing. Never two letters of a longer word."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) == 2 and text.isalpha():
        return text.upper()
    mapped = _US_STATES.get(text.lower())
    if mapped is None and text:
        log.warning("listing state %r is neither a code nor a name I know, dropping it", text[:40])
    return mapped


def _zip_code(value: object) -> str | None:
    """The postal code out of whatever the feed put in the field.

    "80202-1234 Suite 400" truncated at ten happens to give the right answer;
    "80202 Denver CO" gives "80202 Denv", which is not a postal code at all.
    Match the shape instead of trusting the length.
    """
    if not isinstance(value, str):
        return None
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", value)
    if match:
        return match.group(0)
    if value.strip():
        log.warning("listing postal code %r does not look like one, dropping it", value[:40])
    return None


def _fits(value: object, column: str) -> object:
    """Trim a feed value to its column, reading the width from the schema.

    Nothing here can rely on the model's `@validates` net: `_upsert_page` writes
    a page with one Core `INSERT … ON CONFLICT`, which never touches an ORM
    attribute. And a value that does not fit does not fail its own listing — the
    page is written in a single statement and its cursor is committed with it,
    so the page fails, the cursor never advances, and every later run refetches
    exactly the same page. One record stalls the whole feed until a human
    notices.

    This is for prose — a title, an address, a neighbourhood — where a trimmed
    value is still a true one. Coded fields go through `_state_code` and
    `_zip_code` instead, because two letters of "Colorado" is not a shorter
    state, it is a wrong one.
    """
    if not isinstance(value, str):
        return value
    limit = _PROPERTY_WIDTHS.get(column)
    if limit is None or len(value) <= limit:
        return value
    log.warning(
        "listing field %s was %d characters against a column of %d, trimming: %s…",
        column,
        len(value),
        limit,
        value[:40],
    )
    return value[:limit]


def _map_reso_record(r: dict) -> ListingDTO | None:
    """Map one RESO Property record to a ListingDTO (None if it has no key)."""
    key = str(r.get("ListingKey") or r.get("ListingId") or "")
    if not key:
        return None
    # RESO allows 255 for a ListingKey and this column is 120. One over-long key
    # does not fail its own listing: `_upsert_page` writes the page in a single
    # INSERT … ON CONFLICT, and `_sync_reso` commits the rows and the cursor
    # together — so the page fails, the cursor never advances, and the next run
    # refetches the same page and fails identically. One record stalls the whole
    # feed, permanently, until somebody notices by hand.
    #
    # Skipping the record costs one listing out of a page and keeps the feed
    # moving. It is logged loudly because a listing silently missing from the
    # matcher is its own kind of harm.
    if len(key) > 120:
        log.warning(
            "skipping a listing whose key is %d characters (the column holds 120): %s…",
            len(key),
            key[:40],
        )
        return None
    media = [m for m in (r.get("Media") or []) if isinstance(m, dict) and m.get("MediaURL")]
    media.sort(key=lambda m: m["Order"] if isinstance(m.get("Order"), int) else 1_000_000)
    photos = [m["MediaURL"] for m in media][:12]
    # Rentals live in PropertyType ("Residential Lease" / "Commercial Lease"), not in
    # PropertySubType — a lease's subtype is still "Single Family Residence" etc.
    kind = f"{r.get('PropertyType') or ''} {r.get('PropertySubType') or ''}".lower()
    listing_type = "rent" if ("lease" in kind or "rent" in kind) else "sale"
    baths = r.get("BathroomsTotalDecimal")
    if baths is None:
        baths = r.get("BathroomsTotalInteger")
    return ListingDTO(
        external_id=key,
        title=_fits(r.get("UnparsedAddress") or f"Listing {key}", "title"),
        price=_d(r["ListPrice"]) if r.get("ListPrice") is not None else None,
        listing_type=listing_type,
        status=_map_status(r.get("StandardStatus"), r.get("MlgCanView")),
        property_type=_fits(r.get("PropertySubType") or r.get("PropertyType"), "property_type"),
        description=r.get("PublicRemarks"),
        address=_fits(r.get("UnparsedAddress"), "address"),
        city=_fits(r.get("City"), "city"),
        # `state` holds two characters. A feed answering "Colorado" instead of
        # "CO" does not lose the state — it takes the page down with it.
        state=_state_code(r.get("StateOrProvince")),
        zip_code=_zip_code(r.get("PostalCode")),
        zone=_fits(r.get("SubdivisionName") or r.get("MLSAreaMajor"), "zone"),
        bedrooms=r.get("BedroomsTotal"),
        bathrooms=_d(baths) if baths is not None else None,
        sqft=r.get("LivingArea"),
        url=None,  # MLS Grid's Property payload has no ListingURL field
        photos=photos,
        source_modified_at=_parse_dt(r.get("ModificationTimestamp")),
        raw={
            "reso_key": key,
            "listing_type": listing_type,
            "standard_status": r.get("StandardStatus"),
            "modification_timestamp": r.get("ModificationTimestamp"),
            "mlg_can_view": r.get("MlgCanView"),
            "list_office_name": r.get("ListOfficeName"),
            "list_agent_name": r.get("ListAgentFullName"),
        },
    )


@dataclass
class ResoPage:
    """One page of the RESO feed.

    `listings` is already narrowed to the requested city, but `max_modified` comes
    from EVERY record the page returned. MLS Grid requires the replication cursor to
    track the greatest ModificationTimestamp *received*, not the greatest one stored —
    with a client-side city filter those differ, and using the stored one would re-pull
    the same window forever.
    """

    listings: list[ListingDTO]
    max_modified: datetime | None


async def _fetch_reso_pages(
    base_url: str,
    token: str,
    *,
    modified_since: datetime | None = None,
    city: str | None = None,
    page_size: int = 200,
    max_pages: int = 50,
) -> AsyncIterator[ResoPage]:
    """Yield pages of the RESO feed, following @odata.nextLink.

    Only OriginatingSystemName + ModificationTimestamp go into $filter: MLS Grid
    exposes a fixed set of searchable fields and City is not one of them, so the city
    narrowing happens client-side. $orderby is not a supported segment either — the
    feed already arrives ordered by ModificationTimestamp and the cursor takes the page
    max. Requests are spaced to stay under MLS Grid's 2 req/s ceiling.

    Incremental: with `modified_since`, only records with ModificationTimestamp >=
    cursor (>= so boundary records sharing the cursor's exact timestamp are re-seen and
    idempotently upserted). ALL statuses are ingested so status transitions drive
    delta-delete downstream (the matcher filters to ACTIVE).
    """
    s = get_settings()
    filt = f"OriginatingSystemName eq {_odata_str(s.RESO_ORIGINATING_SYSTEM)}"
    if modified_since is not None:
        filt += f" and ModificationTimestamp ge {_odata_dt(modified_since)}"
    params: dict | None = {
        "$filter": filt,
        "$top": str(max(1, min(page_size, _MAX_TOP_WITH_EXPAND))),
        "$expand": "Media",
    }
    url: str | None = f"{base_url.rstrip('/')}/Property"
    min_interval = max(0.0, s.RESO_MIN_REQUEST_INTERVAL_SECONDS)
    last_request_at: float | None = None
    pages = 0
    async with _reso_client() as client:
        while url and pages < max_pages:
            if last_request_at is not None and min_interval:
                wait = min_interval - (time.monotonic() - last_request_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            last_request_at = time.monotonic()
            payload = await _reso_get(client, url, token, params)
            params = None  # @odata.nextLink already carries the query string
            received = [dto for r in payload.get("value", []) if (dto := _map_reso_record(r))]
            yield ResoPage(
                listings=[d for d in received if _city_matches(d, city)],
                max_modified=max(
                    (d.source_modified_at for d in received if d.source_modified_at),
                    default=None,
                ),
            )
            url = payload.get("@odata.nextLink")
            pages += 1
    if url and pages >= max_pages:
        log.info(
            "RESO pagination stopped at RESO_MAX_PAGES=%d; the cursor resumes the rest next run",
            max_pages,
        )


# ── Sync (upsert into the DB) ───────────────────────────────────────────────


async def sync_listings(
    db: AsyncSession, *, city: str | None = None, full: bool = False
) -> dict[str, int]:
    """Fetch listings and upsert into `properties` by (source, external_id).

    Returns counts {created, updated, total}. SIMULATED upserts the curated set as
    MANUAL in one commit. A real feed replicates from RESO/MLS Grid incrementally —
    pages commit one at a time and the cursor advances after each, so a mid-run crash
    resumes from the last durable page. `full=True` ignores the cursor (full backfill).
    """
    s = get_settings()
    if not s.LISTINGS_SIMULATED:
        if not s.RESO_BASE_URL or not s.RESO_ACCESS_TOKEN:
            raise ListingsError(
                "MLS feed not configured: RESO_BASE_URL + RESO_ACCESS_TOKEN must be set, "
                "or set LISTINGS_SIMULATED=true for dev."
            )
        return await _sync_reso(db, city=city, full=full)

    source = PropertySource.MANUAL
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


async def _upsert_page(
    db: AsyncSession, source: PropertySource, dtos: list[ListingDTO]
) -> tuple[int, int]:
    """Bulk upsert one page of listings by (source, external_id) via INSERT … ON
    CONFLICT (race-safe against a concurrent worker/cron). Returns (created, updated).
    Does NOT commit — the caller owns the transaction boundary."""
    by_key: dict[str, ListingDTO] = {}
    for d in dtos:
        if d is not None:
            by_key[d.external_id] = d  # de-dup within the page (keep last / most recent)
    if not by_key:
        return (0, 0)

    keys = list(by_key.keys())
    existing = set(
        (
            await db.execute(
                select(Property.external_id).where(
                    Property.source == source, Property.external_id.in_(keys)
                )
            )
        )
        .scalars()
        .all()
    )

    rows = []
    for d in by_key.values():
        raw = dict(d.raw)
        raw.setdefault("listing_type", d.listing_type)
        rows.append(
            {
                "source": source,
                "external_id": d.external_id,
                "status": d.status,
                "title": d.title,
                "description": d.description,
                "property_type": d.property_type,
                "address": d.address,
                "city": d.city,
                "state": d.state,
                "zip_code": d.zip_code,
                "zone": d.zone,
                "price": d.price,
                "bedrooms": d.bedrooms,
                "bathrooms": d.bathrooms,
                "sqft": d.sqft,
                "url": d.url,
                "photos": d.photos,
                "listed_at": d.listed_at,
                "raw": raw,
            }
        )

    stmt = pg_insert(Property).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_={
            col: getattr(stmt.excluded, col)
            for col in (
                "status", "title", "description", "property_type", "address", "city",
                "state", "zip_code", "zone", "price", "bedrooms", "bathrooms", "sqft",
                "url", "photos", "raw",
            )
        },
    )
    await db.execute(stmt)
    created = sum(1 for k in keys if k not in existing)
    return (created, len(keys) - created)


async def _sync_reso(
    db: AsyncSession, *, city: str | None = None, full: bool = False
) -> dict[str, int]:
    """Incremental RESO replication: per-page upsert + commit + cursor advance."""
    s = get_settings()
    row = (
        await db.execute(select(SyncState).where(SyncState.source == RESO_SOURCE_KEY))
    ).scalar_one_or_none()
    if row is None:
        db.add(SyncState(source=RESO_SOURCE_KEY))
        await db.commit()
        cursor = None
    else:
        cursor = None if full else row.cursor_modified_at

    # A filtered run is a manual import of one slice, not a sweep of the feed,
    # so it must not move the marker the sweep depends on.
    advances_cursor = not city
    total_created = total_updated = 0
    max_seen = cursor
    try:
        async for page in _fetch_reso_pages(
            s.RESO_BASE_URL,
            s.RESO_ACCESS_TOKEN,
            modified_since=cursor,
            city=city,
            page_size=s.RESO_PAGE_SIZE,
            max_pages=s.RESO_MAX_PAGES,
        ):
            # The cursor advances on EVERY page, even one the city filter emptied —
            # otherwise those records come back on the next run, forever.
            #
            # But ONLY when nothing was filtered out. `city` is applied on our
            # side, so a city-scoped run sees every record and imports a few;
            # advancing the shared cursor past the rest told the unfiltered
            # background worker they were already handled. One
            # `POST /properties/sync?city=Denver` therefore made every Boulder
            # listing modified in that window invisible forever — including the
            # ones that had just gone under contract, which the agent kept
            # offering at a stale price.
            if advances_cursor and page.max_modified and (
                max_seen is None or page.max_modified > max_seen
            ):
                max_seen = page.max_modified
            created = updated = 0
            if page.listings:
                created, updated = await _upsert_page(db, PropertySource.RESO, page.listings)
            await db.execute(
                update(SyncState)
                .where(SyncState.source == RESO_SOURCE_KEY)
                .values(
                    cursor_modified_at=max_seen,
                    last_run_at=datetime.now(UTC),
                    last_created=total_created + created,
                    last_updated=total_updated + updated,
                    last_error=None,
                )
            )
            await db.commit()  # page rows + cursor advance commit atomically
            total_created += created
            total_updated += updated
    except Exception as exc:  # noqa: BLE001 — record the failure, then re-raise
        await db.rollback()
        await db.execute(
            update(SyncState)
            .where(SyncState.source == RESO_SOURCE_KEY)
            .values(last_run_at=datetime.now(UTC), last_error=str(exc)[:500])
        )
        await db.commit()
        raise

    log.info(
        "RESO sync: created=%d updated=%d cursor=%s", total_created, total_updated, max_seen
    )
    return {
        "created": total_created,
        "updated": total_updated,
        "total": total_created + total_updated,
    }


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
        # budget_* may be float (freshly set from the classifier) or Decimal (from
        # the DB) — normalize so we never do float * Decimal.
        if lead.budget_max is not None and p.price is not None:
            if p.price > Decimal(str(lead.budget_max)) * Decimal("1.10"):  # 10% headroom
                continue
        if lead.budget_min is not None and p.price is not None:
            if p.price < Decimal(str(lead.budget_min)) * Decimal("0.90"):
                continue
        out.append(p)

    out.sort(key=lambda p: (p.price if p.price is not None else Decimal("0")))
    return out[:limit]

def listing_broker(office: str | None, source: object = None) -> str | None:
    """The broker to credit beside a listing, or None if there is none to credit.

    Colorado requires the listing broker to be named wherever an IDX listing
    reaches a consumer. The obligation sits on the agency's real-estate
    licence, so callers render this themselves rather than asking a language
    model to repeat it.

    Returns the name only; each surface phrases it in its own language
    ("Cortesía de …" in chat, a localized label in the dashboard). Errs towards
    crediting: any name present is credited whatever the source, and a feed
    listing with no name falls back to the feed itself, so one missing field
    cannot silently drop the credit.
    """
    from app.models.property import PropertySource

    name = (office or "").strip()
    if name:
        return name
    origin = getattr(source, "value", source)
    if origin in (
        PropertySource.RESO.value,
        PropertySource.IDX.value,
        PropertySource.MLS.value,
    ):
        return "REcolorado"
    return None

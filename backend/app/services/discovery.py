"""Discovery — find business leads across Google Maps / Yelp / LinkedIn / Colorado SOS.

SIMULATED-first (mirrors app/services/listings.py): when DISCOVERY_SIMULATED=true
(default) it returns a curated synthetic set so the whole UX works with zero keys.
Otherwise each source uses its real adapter when its key is configured — Colorado SOS
is free (public Socrata API); Yelp needs YELP_API_KEY (free tier); Google Maps needs
OUTSCRAPER_API_KEY; LinkedIn needs APIFY_API_KEY. Adapters degrade to [] without a key.

Ported/adapted from the Eko AI Main sales platform's discovery agent.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Lead, LeadStatus

log = logging.getLogger(__name__)

# Legacy business sources (still used under the hood — e.g. Colorado SOS powers
# the investor-LLC category). The product-facing surface is the lead categories.
VALID_SOURCES = ("google_maps", "yelp", "linkedin", "colorado_sos")

# Real-estate lead categories — how realtors actually prospect (see
# docs/discovery-realestate-research.md). SELLER categories carry listing intent;
# BUYER categories carry purchase/rent intent.
LEAD_CATEGORIES = (
    "fsbo",            # For Sale By Owner — seller
    "expired",         # Expired listing — seller
    "absentee",        # Absentee / out-of-state owner — seller
    "preforeclosure",  # Pre-foreclosure / distressed — seller
    "high_equity",     # High-equity / likely-to-sell — seller
    "investor_llc",    # Real-estate investor LLC — buyer (real via Colorado SOS)
    "renter",          # Renter / relocator — buyer
)
SELLER_CATEGORIES = ("fsbo", "expired", "absentee", "preforeclosure", "high_equity")

_COLORADO_SODA_API = "https://data.colorado.gov/resource/4ykn-tg5h.json"


@dataclass
class BusinessDTO:
    """A discovered lead — an owner/consumer (real-estate categories) or a business."""

    business_name: str
    source: str  # the lead category (fsbo/expired/...) or a legacy business source
    category: str | None = None  # human label
    description: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    motivation: str | None = None       # why they'd transact ("listing expired 2 wks ago")
    timeline: str | None = None         # immediate | 3-6mo | exploring
    property_type: str | None = None    # house | condo | townhome | commercial | land
    est_value: str | None = None        # estimated property value, when known
    raw: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return {
            "business_name": self.business_name,
            "source": self.source,
            "category": self.category,
            "email": self.email,
            "phone": self.phone,
            "website": self.website,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "motivation": self.motivation,
            "timeline": self.timeline,
            "property_type": self.property_type,
            "est_value": self.est_value,
        }


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_BAD_EMAIL_RE = re.compile(r"@(example|test|domain|email)\.(com|org|net)$|@localhost$", re.IGNORECASE)


def sanitize_email(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower()
    if not _EMAIL_RE.match(cleaned) or _BAD_EMAIL_RE.search(cleaned):
        return None
    return cleaned


# ── Curated SIMULATED real-estate leads (Denver-metro CO, matches the demo) ────
# Each lead is an owner/consumer with a real-estate motivation + timeline, so the
# whole search → import → enrich → /leads flow works with zero API keys.
_SIMULATED_LEADS: list[BusinessDTO] = [
    # FSBO — For Sale By Owner (sellers listing without an agent)
    BusinessDTO("Daniel & Rosa Vega", "fsbo", category="For Sale By Owner", phone="+13035552201",
                address="2841 Stuart St", city="Denver", state="CO", zip_code="80212",
                motivation="Listed FSBO 18 days ago, no offers yet", timeline="immediate",
                property_type="house", est_value="$685,000"),
    BusinessDTO("Marcus Bell", "fsbo", category="For Sale By Owner", phone="+13035552202",
                address="1190 S Galena St", city="Aurora", state="CO", zip_code="80247",
                motivation="FSBO listing, relocating for work in 60 days", timeline="immediate",
                property_type="townhome", est_value="$420,000"),
    BusinessDTO("Karen Okafor", "fsbo", category="For Sale By Owner", phone="+13035552203",
                address="745 Pearl St", city="Boulder", state="CO", zip_code="80302",
                motivation="Selling by owner, frustrated with showings", timeline="3-6mo",
                property_type="condo", est_value="$540,000"),
    # Expired listings (failed to sell with a prior agent — highest ROI)
    BusinessDTO("Thomas Reilly", "expired", category="Expired listing", phone="+13035552211",
                address="5520 W 29th Ave", city="Denver", state="CO", zip_code="80212",
                motivation="Listing expired 2 weeks ago, was on market 142 days", timeline="immediate",
                property_type="house", est_value="$760,000"),
    BusinessDTO("Angela Pruitt", "expired", category="Expired listing", phone="+13035552212",
                address="3033 E Arizona Ave", city="Denver", state="CO", zip_code="80210",
                motivation="Expired after a price-reduction, still motivated", timeline="immediate",
                property_type="house", est_value="$612,000"),
    BusinessDTO("Greg Hammond", "expired", category="Expired listing", phone="+13035552213",
                address="660 S Alton Way", city="Aurora", state="CO", zip_code="80012",
                motivation="Listing expired, agent contract lapsed", timeline="3-6mo",
                property_type="condo", est_value="$315,000"),
    # Absentee / out-of-state owners (own where they don't live → investment exits)
    BusinessDTO("Lillian Brooks", "absentee", category="Absentee owner",
                address="1424 Newport St (owner mails to Phoenix, AZ)", city="Denver", state="CO", zip_code="80220",
                motivation="Out-of-state owner (mailing addr in AZ), owns 11 yrs", timeline="exploring",
                property_type="house", est_value="$575,000"),
    BusinessDTO("Raymond Cho", "absentee", category="Absentee owner",
                address="9803 E Peakview Ave (owner in Seattle, WA)", city="Aurora", state="CO", zip_code="80111",
                motivation="Absentee landlord, mailing addr out of state", timeline="3-6mo",
                property_type="townhome", est_value="$455,000"),
    # Pre-foreclosure / distressed (motivated/forced sale)
    BusinessDTO("Dewayne Carter", "preforeclosure", category="Pre-foreclosure",
                address="4715 Perry St", city="Denver", state="CO", zip_code="80212",
                motivation="Notice of default recorded last month", timeline="immediate",
                property_type="house", est_value="$498,000"),
    BusinessDTO("Sandra Mejía", "preforeclosure", category="Pre-foreclosure",
                address="2208 Florence St", city="Aurora", state="CO", zip_code="80010",
                motivation="Lis pendens filed, behind on payments", timeline="immediate",
                property_type="house", est_value="$372,000"),
    # High-equity / likely-to-sell (long tenure + equity → predictive seller)
    BusinessDTO("Patricia Nolan", "high_equity", category="High-equity owner",
                address="1280 Josephine St", city="Denver", state="CO", zip_code="80206",
                motivation="Owns 22 yrs, ~85% equity, empty-nester", timeline="exploring",
                property_type="house", est_value="$890,000"),
    BusinessDTO("Frank & Doris Whitaker", "high_equity", category="High-equity owner",
                address="3550 S Harlan St", city="Littleton", state="CO", zip_code="80123",
                motivation="Mortgage nearly paid, likely downsizing", timeline="3-6mo",
                property_type="house", est_value="$640,000"),
    # Investor LLCs (buyers — real via Colorado SOS in live mode)
    BusinessDTO("Cherry Creek Renovations LLC", "investor_llc", category="Real-estate investor LLC",
                description="Colorado registered LLC, real-estate activity", address="3000 E 1st Ave",
                city="Denver", state="CO", zip_code="80206",
                motivation="Active CO real-estate LLC — likely buyer/flipper", timeline="immediate",
                property_type="investment"),
    BusinessDTO("Highlands Capital Holdings LLC", "investor_llc", category="Real-estate investor LLC",
                description="Colorado registered LLC, real-estate activity", address="3578 W 32nd Ave",
                city="Denver", state="CO", zip_code="80211",
                motivation="Buy-and-hold investor LLC", timeline="3-6mo", property_type="investment"),
    # Renters / relocators (buyers — lease ending, may convert to purchase)
    BusinessDTO("Emily Tran", "renter", category="Renter / relocator", phone="+13035552251",
                email="emily.tran@example.net", address="Capitol Hill", city="Denver", state="CO",
                motivation="Lease ends in 75 days, asking about buying", timeline="3-6mo",
                property_type="condo", est_value="~$350,000 budget"),
    BusinessDTO("Jaylen Foster", "renter", category="Renter / relocator", phone="+13035552252",
                address="Stapleton / Central Park", city="Denver", state="CO",
                motivation="Relocating to Denver, pre-approved buyer", timeline="immediate",
                property_type="house", est_value="~$525,000 budget"),
]


def _simulated(query: str, city: str | None, category: str, max_results: int) -> list[BusinessDTO]:
    q = (query or "").lower()
    items = [b for b in _SIMULATED_LEADS if b.source == category]
    if city:
        cl = city.lower()
        city_matches = [b for b in items if (b.city or "").lower() == cl]
        if city_matches:  # don't over-filter the demo to empty
            items = city_matches
    if q:  # optional free-text refine over name/motivation/property_type
        ql = [b for b in items if q in (b.business_name + " " + (b.motivation or "") + " "
                                        + (b.property_type or "")).lower()]
        if ql:
            items = ql
    return items[:max_results]


# ── Real adapters (active only when DISCOVERY_SIMULATED=false + key present) ──


async def _colorado_sos(query: str, city: str | None, max_results: int) -> list[BusinessDTO]:
    """Free public Socrata API — no key needed."""
    where = [f"lower(entityname) like '%{query.lower()}%'"]
    if city:
        where.append(f"principalcity = '{city.upper()}'")
    params = {"$where": " and ".join(where), "$limit": min(max_results, 100), "$order": "entityformdate DESC"}
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(_COLORADO_SODA_API, params=params)
        resp.raise_for_status()
        rows = resp.json()
    out: list[BusinessDTO] = []
    for e in rows:
        name = e.get("entityname")
        if not name:
            continue
        etype = e.get("entitytype") or "Business"
        out.append(BusinessDTO(
            business_name=name.strip(), source="colorado_sos", category=etype,
            description=f"Colorado registered {etype}. Status: {e.get('entitystatus', 'Unknown')}.",
            address=e.get("principaladdress1"), city=e.get("principalcity"),
            state=e.get("principalstate") or "CO", zip_code=e.get("principalzipcode"), raw=e,
        ))
    return out


async def _yelp(query: str, city: str, state: str | None, max_results: int) -> list[BusinessDTO]:
    s = get_settings()
    if not s.YELP_API_KEY:
        return []
    location = f"{city}, {state}" if state else city
    async with httpx.AsyncClient(timeout=30.0, headers={"Authorization": f"Bearer {s.YELP_API_KEY}"}) as c:
        resp = await c.get(
            "https://api.yelp.com/v3/businesses/search",
            params={"term": query, "location": location, "limit": min(max_results, 50), "sort_by": "best_match"},
        )
        resp.raise_for_status()
        businesses = resp.json().get("businesses", [])
    out: list[BusinessDTO] = []
    for b in businesses:
        name = (b.get("name") or "").strip()
        if not name:
            continue
        loc = b.get("location", {})
        cats = b.get("categories", [])
        out.append(BusinessDTO(
            business_name=name, source="yelp",
            category=cats[0].get("title") if cats else None,
            phone=b.get("phone") or b.get("display_phone") or None,
            website=b.get("url"), address=", ".join(loc.get("display_address", []) or []) or None,
            city=loc.get("city"), state=loc.get("state"), zip_code=loc.get("zip_code"), raw=b,
        ))
    return out


async def _google_maps(query: str, city: str, state: str | None, max_results: int) -> list[BusinessDTO]:
    """Via Outscraper Google Maps API (OUTSCRAPER_API_KEY)."""
    s = get_settings()
    if not s.OUTSCRAPER_API_KEY:
        return []
    search_query = f"{query} in {city}, {state}" if state else f"{query} in {city}"
    async with httpx.AsyncClient(timeout=60.0, headers={"X-API-KEY": s.OUTSCRAPER_API_KEY}) as c:
        resp = await c.get(
            "https://api.app.outscraper.com/maps/search-v3",
            params={"query": search_query, "limit": min(max_results, 500), "region": "us", "async": "false"},
        )
        resp.raise_for_status()
        data = resp.json()
    places = data.get("data", []) if isinstance(data, dict) else data
    # Outscraper nests results one level deep per query.
    flat = places[0] if places and isinstance(places[0], list) else places
    out: list[BusinessDTO] = []
    for p in flat:
        if not isinstance(p, dict):
            continue
        name = p.get("name") or p.get("title")
        if not name:
            continue
        out.append(BusinessDTO(
            business_name=name.strip(), source="google_maps",
            category=p.get("type") or p.get("category"),
            phone=p.get("phone") or p.get("phone_number"), email=sanitize_email(p.get("email")),
            website=p.get("site") or p.get("website"), address=p.get("full_address") or p.get("address"),
            city=p.get("city"), state=p.get("state"), zip_code=p.get("postal_code"), raw=p,
        ))
    return out


async def _linkedin(query: str, city: str, state: str | None, max_results: int) -> list[BusinessDTO]:
    """LinkedIn profiles via SerpApi Google search (SERPAPI_API_KEY) — site:linkedin.com/in."""
    s = get_settings()
    if not s.SERPAPI_API_KEY:
        return []
    q = f'site:linkedin.com/in "{query}" {city} {state or ""}'.strip()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            "https://serpapi.com/search",
            params={"engine": "google", "q": q, "num": min(max_results, 20), "api_key": s.SERPAPI_API_KEY},
        )
        resp.raise_for_status()
        organic = resp.json().get("organic_results", [])
    out: list[BusinessDTO] = []
    for r in organic:
        link = r.get("link", "") or ""
        if "linkedin.com/in" not in link:
            continue
        title = (r.get("title") or "").strip()
        name = title.split(" | ")[0].split(" - ")[0].strip()
        if not name:
            continue
        category = title.split(" - ", 1)[1].strip() if " - " in title else (title.split(" | ", 1)[1].strip() if " | " in title else None)
        out.append(BusinessDTO(
            business_name=name, source="linkedin", category=category,
            website=link, description=r.get("snippet"), city=city, state=state, raw=r,
        ))
    return out


async def _attom_owners(category: str, city: str, state: str, max_results: int) -> list[BusinessDTO]:
    """Property/owner-record categories (absentee / preforeclosure / high_equity)
    via the ATTOM Property Data API. Key-gated; returns [] without ATTOM_API_KEY
    (SIMULATED data covers the demo). ATTOM exposes owner mailing address (→ absentee),
    pre-foreclosure filings, and equity — the public-records signals realtors farm."""
    s = get_settings()
    if not s.ATTOM_API_KEY:
        return []
    # ATTOM REST (apikey header). The exact endpoint/filters differ per category;
    # this is the integration point — wire the specific property endpoint per plan.
    async with httpx.AsyncClient(timeout=45.0, headers={"apikey": s.ATTOM_API_KEY, "accept": "application/json"}) as c:
        resp = await c.get(
            "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/address",
            params={"cityname": city, "state": state, "pagesize": min(max_results, 50)},
        )
        resp.raise_for_status()
        rows = (resp.json() or {}).get("property", []) or []
    out: list[BusinessDTO] = []
    for p in rows:
        addr = (p.get("address") or {})
        line = addr.get("line1") or addr.get("oneLine")
        if not line:
            continue
        out.append(BusinessDTO(
            business_name=(p.get("owner") or {}).get("owner1", {}).get("lastname") or line,
            source=category, category={"absentee": "Absentee owner", "preforeclosure": "Pre-foreclosure",
                                       "high_equity": "High-equity owner"}.get(category, category),
            address=line, city=addr.get("locality") or city, state=addr.get("countrySubd") or state,
            zip_code=addr.get("postal1"), property_type=(p.get("summary") or {}).get("proptype"), raw=p,
        ))
    return out


# ── Orchestration ────────────────────────────────────────────────────────────


async def discover(
    *, query: str = "", city: str, state: str = "CO", max_results: int = 50, category: str,
) -> list[BusinessDTO]:
    """Find real-estate leads for one category. SIMULATED-first; real per-category
    when its key is set (Colorado SOS is free for investor LLCs; ATTOM for owner
    records). Categories without a wired free feed return [] in real mode."""
    if category not in LEAD_CATEGORIES:
        category = "fsbo"
    s = get_settings()

    if s.DISCOVERY_SIMULATED:
        return _simulated(query, city, category, max_results)

    results: list[BusinessDTO] = []
    try:
        if category == "investor_llc":
            for b in await _colorado_sos(query or "realty", city, max_results):
                b.source, b.category = "investor_llc", "Real-estate investor LLC"
                b.motivation = b.motivation or "Active CO real-estate LLC — likely buyer/investor"
                results.append(b)
        elif category in ("absentee", "preforeclosure", "high_equity"):
            results += await _attom_owners(category, city, state, max_results)
        else:
            # fsbo / expired / renter — need a licensed/portal feed (not free).
            log.info("Discovery category %s has no free real feed; configure a provider.", category)
    except Exception as exc:  # noqa: BLE001
        log.warning("Discovery real source for %s failed: %s", category, exc)

    # Dedupe by (name, city).
    seen: set[tuple[str, str]] = set()
    out: list[BusinessDTO] = []
    for b in results:
        b.email = sanitize_email(b.email)
        key = (b.business_name.lower(), (b.city or "").lower())
        if b.business_name and key not in seen:
            seen.add(key)
            out.append(b)
    return out[:max_results]


# ── Import → Lead rows ───────────────────────────────────────────────────────


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def lead_identifier(b: BusinessDTO) -> str:
    """The unique Lead.phone value for a discovered business.

    The `phone` column is a generic identifier (Phase 3). Prefer a real contact
    (phone, then email, then website); many sources (Colorado SOS, LinkedIn)
    carry none, so fall back to a stable synthetic key derived from the business
    so the lead still imports AND re-imports dedupe instead of duplicating.
    """
    real = (b.phone or b.email or b.website or "").strip()
    if real:
        return real[:254]
    return f"discovery:{b.source}:{_slug(b.business_name)}:{_slug(b.city or '')}"[:254]


async def import_business_leads(
    items: list[BusinessDTO], db: AsyncSession, *, source_label: str = "discovery"
) -> dict[str, Any]:
    """Create Lead rows from selected businesses. Dedupe by identifier (the unique
    `phone` column); existing leads are skipped, not duplicated. Returns the IDs of
    newly created leads so the caller can enrich them."""
    created_ids: list[int] = []
    skipped = 0
    for b in items:
        if not b.business_name:
            skipped += 1
            continue
        identifier = lead_identifier(b)
        existing = (await db.execute(select(Lead).where(Lead.phone == identifier))).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue
        lead = Lead(
            phone=identifier,
            name=b.business_name,
            status=LeadStatus.NEW,
            zone=b.city,
            property_type=b.property_type,
            meta={
                "source": b.source or source_label,
                "discovery": True,
                "category": b.category,
                "lead_category": b.source if b.source in LEAD_CATEGORIES else None,
                "website": b.website,
                "address": b.address,
                "email": b.email,
                "phone": b.phone,
                "motivation": b.motivation,
                "timeline": b.timeline,
                "est_value": b.est_value,
                "synthetic_identifier": not (b.phone or b.email or b.website),
            },
        )
        db.add(lead)
        await db.flush()
        created_ids.append(lead.id)
    await db.commit()
    return {
        "created": len(created_ids),
        "skipped": skipped,
        "total": len(created_ids) + skipped,
        "lead_ids": created_ids,
    }

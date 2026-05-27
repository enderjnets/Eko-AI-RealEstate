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

VALID_SOURCES = ("google_maps", "yelp", "linkedin", "colorado_sos")
_COLORADO_SODA_API = "https://data.colorado.gov/resource/4ykn-tg5h.json"


@dataclass
class BusinessDTO:
    business_name: str
    source: str
    category: str | None = None
    description: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
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


# ── Curated SIMULATED set (Denver/CO businesses a realtor would prospect) ──────
_SIMULATED: list[BusinessDTO] = [
    BusinessDTO("Mile High Mortgage Group", "google_maps", category="Mortgage broker",
                phone="+13035550111", email="info@milehighmortgage.com", website="https://milehighmortgage.com",
                address="1600 Broadway, Denver, CO 80202", city="Denver", state="CO"),
    BusinessDTO("Rocky Mountain Home Inspections", "google_maps", category="Home inspector",
                phone="+13035550122", email="hello@rmhinspections.com", website="https://rmhinspections.com",
                address="2nd Ave, Denver, CO 80206", city="Denver", state="CO"),
    BusinessDTO("Front Range Title Co.", "google_maps", category="Title company",
                phone="+13035550133", website="https://frontrangetitle.com",
                address="999 18th St, Denver, CO 80202", city="Denver", state="CO"),
    BusinessDTO("Summit Moving & Storage", "yelp", category="Movers",
                phone="+13035550144", website="https://summitmoving.example", address="Aurora, CO", city="Aurora", state="CO"),
    BusinessDTO("Bloom Interior Staging", "yelp", category="Home staging",
                phone="+13035550155", email="studio@bloomstaging.com", website="https://bloomstaging.example",
                address="Boulder, CO", city="Boulder", state="CO"),
    BusinessDTO("Aspen Property Management LLC", "yelp", category="Property management",
                phone="+13035550166", email="leasing@aspenpm.example", city="Denver", state="CO"),
    BusinessDTO("Jordan Reyes — Realtor", "linkedin", category="Real estate agent",
                email="jordan.reyes@kw.example", website="https://linkedin.com/in/jordanreyes", city="Denver", state="CO"),
    BusinessDTO("Priya Nair — Commercial Broker", "linkedin", category="Commercial real estate",
                email="priya.nair@cbre.example", website="https://linkedin.com/in/priyanair", city="Denver", state="CO"),
    BusinessDTO("Cherry Creek Renovations LLC", "colorado_sos", category="Limited Liability Company",
                description="Colorado registered LLC. Status: Good Standing.",
                address="3000 E 1st Ave", city="Denver", state="CO", zip_code="80206"),
    BusinessDTO("Highlands Realty Partners LLC", "colorado_sos", category="Limited Liability Company",
                description="Colorado registered LLC. Status: Good Standing.",
                address="32nd Ave", city="Denver", state="CO", zip_code="80211"),
    BusinessDTO("Mountain View Builders Inc", "colorado_sos", category="Corporation",
                description="Colorado registered Corporation. Status: Good Standing.",
                city="Littleton", state="CO", zip_code="80120"),
]


def _simulated(query: str, city: str | None, sources: list[str], max_results: int) -> list[BusinessDTO]:
    q = (query or "").lower()
    items = [b for b in _SIMULATED if b.source in sources]
    if city:
        cl = city.lower()
        # keep matches for the city, but don't over-filter the demo to empty
        city_matches = [b for b in items if (b.city or "").lower() == cl]
        if city_matches:
            items = city_matches
    if q:
        ql = [b for b in items if q in (b.category or "").lower() or q in b.business_name.lower()]
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


# ── Orchestration ────────────────────────────────────────────────────────────


async def discover(
    *, query: str, city: str, state: str = "CO", max_results: int = 50, sources: list[str]
) -> list[BusinessDTO]:
    """Search the requested sources and return deduped business leads."""
    sources = [s for s in (sources or []) if s in VALID_SOURCES] or ["google_maps"]
    s = get_settings()

    if s.DISCOVERY_SIMULATED:
        return _simulated(query, city, sources, max_results)

    results: list[BusinessDTO] = []
    if "colorado_sos" in sources:
        try:
            results += await _colorado_sos(query, city, max_results)
        except Exception as exc:  # noqa: BLE001
            log.warning("Colorado SOS failed: %s", exc)
    if "yelp" in sources:
        try:
            results += await _yelp(query, city, state, max_results)
        except Exception as exc:  # noqa: BLE001
            log.warning("Yelp failed: %s", exc)
    if "google_maps" in sources:
        try:
            results += await _google_maps(query, city, state, max_results)
        except Exception as exc:  # noqa: BLE001
            log.warning("Google Maps failed: %s", exc)
    if "linkedin" in sources:
        results += await _linkedin(query, city, state, max_results)

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
            meta={
                "source": b.source or source_label,
                "discovery": True,
                "category": b.category,
                "website": b.website,
                "address": b.address,
                "email": b.email,
                "phone": b.phone,
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

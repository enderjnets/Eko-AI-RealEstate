# Discovery v2 — sourcing real-estate leads (research + design)

> Goal: Discovery must find **people likely to buy / rent / sell** real estate
> (houses, apartments, commercial), not generic businesses. This documents how
> realtors actually source leads, which data is accessible, the compliance rules,
> and the design we ship.

## 1. How realtors source leads (by ROI)

Seller leads (a listing = the highest-value outcome for an agent):

| Lead type | Why they sell | 2026 list/convert signal | Where the data lives |
|---|---|---|---|
| **Expired listings** | Tried to sell, failed | **Highest ROI** — ~44% list rate, ~30-day cycle | MLS (expired status) |
| **FSBO** (For Sale By Owner) | Selling alone, often give up | ~27.8% list rate, ~43-day cycle | Zillow FSBO, Craigslist, FSBO.com, FB Marketplace |
| **FRBO** (For Rent By Owner) | Tired landlords → sell | Medium | Zillow/Craigslist rentals |
| **Absentee / out-of-state owners** | Own where they don't live → investment exits | High | County assessor (owner mailing ≠ property address) |
| **Pre-foreclosure / tax-lien / distressed** | Forced/motivated sale | High | County recorder (NOD/lis pendens), tax office |
| **High-equity / long-tenure** | Equity unlocks a move | Predictive | Public records + mortgage/AVM data |
| **Vacant properties** | Carrying cost → sell | High | USPS vacancy, public records |
| **Probate / inherited** | Heirs sell inherited property (8–10 mo window) | Niche, high | Probate court records (Catalyze AI's niche) |
| **Predictive "likely to sell"** | ML over 25+ signals, 12-mo horizon | Scored propensity | SmartZip / Offrs / Catalyze AI |

Buyer leads: renters approaching lease-end, relocators/new-movers, investors
(often LLCs), and online portal inquiries (Zillow Premier Agent / Realtor.com —
paid, consent-based).

## 2. Data sources & APIs

- **ATTOM Data** — 160M+ US properties, REST API (JSON/XML): ownership, mailing
  address (→ absentee), foreclosure, tax, equity, sales history. Enterprise key.
- **PropStream** — investor platform, 20 ready lead lists (pre-foreclosure,
  absentee, vacant, tax liens, high-equity); has an API.
- **Estated / Regrid / BatchData / HouseCanary / PropertyRadar** — property +
  owner data APIs (paid).
- **County assessor / recorder** — the *free* primary source. Assessor DB exposes
  owner mailing address (absentee = mailing ≠ situs); recorder exposes NOD /
  lis pendens (pre-foreclosure) + recent deeds. Often CSV export, varies by county.
- **Colorado SOS (Socrata)** — *free, no key* — registered business entities →
  real-estate **investor LLCs** (buyers). Already wired in v1.
- **Vulcan7 / REDX / Landvoice** — expired/FSBO/FRBO subscriptions (dialer/CRM,
  not open APIs).

## 3. Compliance (non-negotiable — baked into the product copy)

- **TCPA**: automated/prerecorded marketing calls + texts to mobiles need prior
  express written consent (PEWC); the FCC 2024 one-to-one rule makes consent
  seller-specific. Manual live dials don't need PEWC but still must respect DNC +
  calling hours (8am–9pm local). Statutory damages $500–$1,500 **per violation**.
- **DNC**: scrub against the federal registry **and** 11 state registries —
  including **Colorado**, our demo market — before calling.
- **Portal ToS**: scraping Zillow/Realtor.com violates their terms; use licensed
  data (ATTOM/PropStream) or public records, not scraping.

→ The Discovery UI shows a short DNC/TCPA reminder; imported leads are prospects,
not consented contacts.

## 4. Design — Discovery v2

Reorient the search from "4 business sources" to **real-estate lead categories**
that mirror how agents prospect. SIMULATED-first (curated realistic owner/consumer
leads, zero keys) like every other integration; real per-category when its key is
set.

| Category | Intent | Real source (when keyed) | SIMULATED |
|---|---|---|---|
| `fsbo` — For Sale By Owner | seller | (portal/licensed feed) | ✅ |
| `expired` — Expired listings | seller | MLS/RESO | ✅ |
| `absentee` — Absentee / out-of-state owners | seller | ATTOM (mailing≠situs) | ✅ |
| `preforeclosure` — Pre-foreclosure / distressed | seller | ATTOM / county recorder | ✅ |
| `high_equity` — High-equity / likely-to-sell | seller | ATTOM / predictive | ✅ |
| `investor_llc` — Real-estate investor LLCs | buyer | **Colorado SOS (free, real)** | ✅ |
| `renter` — Renters / relocators | buyer | (rental feed) | ✅ |

Each discovered lead carries: name, property/mailing address, city/state, the
**category**, a **motivation** (e.g. "listing expired 2 wks ago"), a **timeline**
(immediate / 3-6 mo / exploring), property type and an estimated value when known.
On import these land in `Lead.meta`; enrichment then classifies `intent`
(buy/rent/valuation) + scores using the motivation/timeline/equity signals, so
the dashboard ranks the hottest sellers/buyers first.

Real provider keys (all optional; SIMULATED otherwise): `ATTOM_API_KEY` for the
property/owner categories; Colorado SOS needs no key. Documented in
[`setup-discovery.md`](setup-discovery.md).

## Sources

- [REDX — Best Real Estate Leads 2026 ranking](https://www.redx.com/blog/best-real-estate-leads-2026-ranking-guide/)
- [FitSmallBusiness — Best FSBO lead sources](https://fitsmallbusiness.com/best-fsbo-lead-sources/)
- [Vulcan7 — Absentee owner lists guide](https://www.vulcan7.com/2025/07/the-ultimate-guide-to-absentee-owner-lists-in-real-estate-prospecting/)
- [ATTOM Property Data API](https://www.attomdata.com/solutions/property-data-api/)
- [PropStream](https://www.propstream.com/)
- [HouseCanary — 10 best real estate APIs 2026](https://www.housecanary.com/blog/real-estate-api)
- [SmartZip — predictive seller leads](https://smartzip.com/)
- [Catalyze AI](https://www.catalyzeai.com/real-estate/main)
- [REDX — DNC / TCPA guide for agents](https://www.redx.com/blog/agents-dnc-list-tcpa-guide/)
- [ClickPoint — 2026 TCPA / consent / state regs guide](https://blog.clickpointsoftware.com/tcpa-one-to-one-consent-can-spam-state-regulations)
- [DealMachine — absentee owner lists](https://www.dealmachine.com/blog/your-ultimate-guide-to-absentee-owner-lists)

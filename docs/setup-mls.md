# Connecting a real MLS / IDX feed (RESO Web API)

Eko AI Realtors ingests listings through the **RESO Web API** — the OData-based
standard most USA MLSs now expose. In dev the listings service runs SIMULATED
(a curated Miami dataset), so the `/properties` dashboard and per-lead matches
work with zero setup. This guide wires a real feed for a pilot.

## What you need from the MLS / IDX vendor

A licensed agent/broker gets RESO Web API access from their MLS (or an IDX
aggregator like Bridge Interactive / Trestle / MLS Grid). You need:

- **Base URL** — the RESO Web API endpoint, e.g.
  `https://api.mlsgrid.com/v2` or `https://api.bridgedataoutput.com/api/v2/OData/<dataset>`.
- **Access token** — a long-lived bearer token (server token), kept secret.

> The exact field names follow the RESO Data Dictionary (`ListingKey`,
> `ListPrice`, `BedroomsTotal`, `City`, `StandardStatus`, `Media`, …). The
> mapping lives in `backend/app/services/listings.py::_fetch_reso` — adjust there
> if your MLS uses non-standard fields.

## Configure

In `.env`:

```bash
LISTINGS_SIMULATED=false
LISTINGS_PROVIDER=reso
RESO_BASE_URL=https://api.your-mls.com/v2
RESO_ACCESS_TOKEN=your-long-lived-server-token
```

Then restart and run a sync:

```bash
docker compose up -d
docker compose exec backend python scripts/sync_listings.py --city Miami
```

`sync_listings` upserts by `(source, external_id)` so it is safe to re-run. The
`source` is recorded as `reso` for real feeds (vs `manual` for the SIMULATED set).

## Keep it fresh (cron)

Listings change constantly. Schedule a periodic sync on the host:

```cron
*/30 * * * *  cd /path/to/Eko-AI-RealEstate && /usr/bin/docker compose exec -T backend python scripts/sync_listings.py >/dev/null 2>&1
```

## How matching works

`match_properties_for_lead` (used by `GET /api/v1/leads/{id}/matches` and the
dashboard's **Propiedades sugeridas** section) filters **active** listings by:

- **Intent** — `rent` leads see rentals; `buy` / `valuation` see for-sale.
- **Zone** — the lead's `zone` is matched against the listing's neighborhood
  (`zone`) substring-wise, both directions.
- **Budget** — listing price ≤ `budget_max` (+10% headroom), ≥ `budget_min` (−10%).
- **Property type** — substring match when the lead has one.

Results are sorted by price (ascending) and capped (default 6).

## Compliance note

IDX/MLS data carries display rules (attribution, refresh frequency, what may be
shown publicly). The **public demo** runs SIMULATED data precisely to avoid
displaying real MLS listings to the open internet. For a customer install,
follow the rules in their MLS's IDX agreement.

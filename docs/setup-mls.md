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
RESO_BASE_URL=https://api.mlsgrid.com/v2
RESO_ACCESS_TOKEN=your-long-lived-server-token
RESO_ORIGINATING_SYSTEM=recolorado
LISTINGS_SYNC_ENABLED=true
```

Then restart and run a sync:

```bash
docker compose up -d
docker compose exec backend python scripts/sync_listings.py
```

## REcolorado via MLS Grid

REcolorado ships its RESO Web API through [MLS Grid](https://docs.mlsgrid.com/api-documentation/api-version-2.0).
Its constraints are not the generic RESO ones, and getting them wrong either errors
the request or gets the token suspended:

| Constraint | Value |
|---|---|
| `OriginatingSystemName` | `recolorado` (lowercase, required on **every** request) |
| Key prefix | `REC` on keys/MlsIds, `REC_` on local fields |
| Searchable fields | `OriginatingSystemName`, `ModificationTimestamp`, `StandardStatus`, `PropertyType`, `ListingId`, `MlgCanView`, `ListOfficeMlsId` — **and nothing else** |
| `$top` | 1000 max with `$expand` (5000 without), 500 if unset |
| `$orderby` / `$select` | not supported on expanded resources; we send neither |
| Rate limits | **2 req/s**, 7200/h, 40 000/24 h, 4 GB/h, 60 GB/24 h |
| Cadence | every 15 min is what MLS Grid recommends |

Two consequences baked into `services/listings.py`:

- **`--city` filters client-side.** `City` is not searchable, so the whole feed is
  downloaded and narrowed in memory. The replication cursor still advances over
  *every record received*, not just the ones kept — otherwise the discarded ones
  come back on every run.
- **Requests are spaced** by `RESO_MIN_REQUEST_INTERVAL_SECONDS` (0.5s = 2 req/s).
  Do not lower it.

Before the first full import, email support@mlsgrid.com to request a **Grace
Period** — the backfill would otherwise trip the hourly limits.

Check replication health at any time:

```bash
curl -s localhost:8011/api/v1/properties/sync-status
```

`last_error` is where a failing background worker shows up; the logs alone are easy
to miss.

> ⚠️ **Not ready to show real listings yet.** Photos still come through as raw
> MLS Grid `MediaURL`s. Those may only be used to download a local copy — never
> rendered directly — and since June 2026 fetching them requires sending the OAuth
> token as the `User-Agent`, which a browser cannot do. Displaying REcolorado
> listings publicly also requires honouring `MlgCanUse` (IDX vs VOW/BO/PT) and
> stripping the `REC` prefix. That work is tracked separately.

`sync_listings` upserts by `(source, external_id)` so it is safe to re-run. The
`source` is recorded as `reso` for real feeds (vs `manual` for the SIMULATED set).

## Keep it fresh

With `LISTINGS_SYNC_ENABLED=true` the backend replicates in-process every
`LISTINGS_SYNC_INTERVAL_SECONDS` (900 = the 15 min MLS Grid recommends), so no cron
is needed. To drive it externally instead, leave the flag off and schedule:

```cron
*/15 * * * *  cd /path/to/Eko-AI-RealEstate && /usr/bin/docker compose exec -T backend python scripts/sync_listings.py >/dev/null 2>&1
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

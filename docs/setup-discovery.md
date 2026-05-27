# Discovery — lead search + file import (Phase 12)

Discovery lets a realtor **proactively source leads** instead of only waiting for
inbound messages. Two ways in:

1. **Search** four sources — Google Maps, Yelp, LinkedIn, Colorado SOS — for
   businesses (mortgage brokers, inspectors, movers, title cos, property
   managers, agents…).
2. **Import a file** — upload an existing contact database in **any format**
   (PDF, JPG/PNG, TXT, CSV, XLSX, HTML); we extract the contacts for you.

Both end in a **preview-and-select** step: nothing is saved until you tick the
rows you want and hit **Import**. Imported rows become `Lead`s (`status=new`,
`meta.source`).

### Import → enrichment

- Every selected business is created as a `Lead`. The unique identifier falls
  back **phone → email → website → synthetic** (`discovery:<source>:<slug>:<city>`),
  so businesses with **no contact info** (common for Colorado SOS and LinkedIn)
  still import — and re-imports **dedupe** on that key instead of duplicating.
- Right after import, each new lead is **enriched** by the LLM
  (`POST /api/v1/discovery/enrich/{lead_id}`): a normalized business type, how a
  realtor should treat the contact (`partner_type`), a one-line summary, an
  outreach angle, and tags — stored in `meta.enrichment`. The UI shows a
  **progress bar** while this runs, then a **"View in Leads"** link.
- Enrichment is graceful: if the LLM is unavailable or returns bad JSON, the lead
  is still saved with `meta.enrichment.status="failed"` (never lost).

UI: `/discovery`. API: `/api/v1/discovery/{search,upload,import,enrich/{id}}`
(auth-gated).

---

## SIMULATED mode (default — no keys)

`DISCOVERY_SIMULATED=true` (the default) serves a **curated set of plausible
Colorado businesses** across the four sources. The whole flow — search → preview
→ import, and file upload → preview → import — works with **zero API keys and no
external calls**. This is what the public demo runs.

File import still uses the LLM (Kimi/MiniMax) to read the uploaded text — that's
the normal product LLM, no extra account.

---

## Going real — which source needs which key

Set `DISCOVERY_SIMULATED=false`, then each source lights up **only if its key is
present** (otherwise it just returns nothing — it never errors the search):

| Source | Env var | Cost | Notes |
|---|---|---|---|
| **Colorado SOS** | *(none)* | **Free** | Public Socrata API (`data.colorado.gov`). Always on — registered CO business entities. The cheapest real source to lead with. |
| **Yelp** | `YELP_API_KEY` | Free tier | Yelp Fusion API. Good for local service businesses. |
| **Google Maps** | `OUTSCRAPER_API_KEY` | Paid | Via [Outscraper](https://outscraper.com). Highest coverage; metered. |
| **LinkedIn** | `SERPAPI_API_KEY` | Paid | Via [SerpApi](https://serpapi.com) (`site:linkedin.com/in` Google search). Finds agent/broker profiles. |

These reuse the **same keys already configured in the Eko AI sales platform**
(`~/Eko-AI-main/.env`) — copy `YELP_API_KEY`, `OUTSCRAPER_API_KEY`,
`SERPAPI_API_KEY` into this product's `.env` and flip `DISCOVERY_SIMULATED=false`.

> Lead with **Colorado SOS (free)** + **Yelp (free tier)**. Google Maps and
> LinkedIn rely on paid/metered providers and scraping ToS — keep them off
> unless you have budget for the keys.

---

## File import

| Setting | Default | Meaning |
|---|---|---|
| `FILE_IMPORT_MAX_MB` | `25` | Upload size cap (HTTP 413 above it). |

Supported formats and how the text is pulled out:

| Format | Extractor |
|---|---|
| PDF | `pypdf` |
| XLSX / XLSM | `openpyxl` |
| JPG / PNG / images | OCR via `pytesseract` (system `tesseract-ocr`, installed in the backend image) |
| CSV / TSV / TXT / JSON | UTF-8 decode |
| HTML / HTM | decode + tag strip |

The extracted text (capped at ~12k chars) is sent to the LLM in `json_mode` with
a prompt to return contacts as a JSON array. Bad/garbled output degrades to an
empty list — it never crashes the request. Low-res photos may extract little;
the preview lets you discard junk before importing.

---

## Quick check it's wired

```bash
# Simulated search (no keys needed)
curl -s -X POST localhost:8011/api/v1/discovery/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"mortgage","city":"Denver","sources":["google_maps","yelp","colorado_sos"]}'

# Upload a CSV
printf 'name,phone\nAcme Realty,+13035550000\n' > /tmp/leads.csv
curl -s -X POST localhost:8011/api/v1/discovery/upload -F 'file=@/tmp/leads.csv'
```

(If `AUTH_ENABLED=true`, add the session cookie from `/login` first.)

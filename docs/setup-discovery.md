# Discovery — real-estate lead search + file import

Discovery lets a realtor **proactively source leads** instead of only waiting for
inbound messages. It searches by **real-estate lead category** (how agents
actually prospect) — see [`discovery-realestate-research.md`](discovery-realestate-research.md)
for the research behind it. Two ways in:

1. **Search by lead category**:
   - **Sellers**: `fsbo` (For Sale By Owner), `expired` (expired listings),
     `absentee` (out-of-state owners), `preforeclosure` (distressed),
     `high_equity` (long-tenure / likely-to-sell).
   - **Buyers**: `investor_llc` (real-estate investor LLCs — **real via Colorado
     SOS, free**), `renter` (renters / relocators).
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

File import still uses the LLM (Kimi → MiniMax → Groq → Ollama) to read the
uploaded text — that's the normal product LLM, no extra account.

---

## Going real — which category needs which key

`DISCOVERY_SIMULATED=true` (default) serves curated realistic CO leads for every
category with **zero keys** — the demo runs on this. Set
`DISCOVERY_SIMULATED=false` to hit real sources; each category lights up only if
its source is wired (otherwise it returns nothing — never errors the search):

| Category | Source | Env var | Cost |
|---|---|---|---|
| `investor_llc` (buyers) | Colorado SOS (Socrata) | *(none)* | **Free** |
| `absentee` / `preforeclosure` / `high_equity` (sellers) | ATTOM Property API | `ATTOM_API_KEY` | Paid |
| `fsbo` / `expired` / `renter` | licensed feed / portal | — | n/a yet |

- **`investor_llc`** is the cheapest real category — Colorado SOS is free, no key.
- **ATTOM** (`ATTOM_API_KEY`, [attomdata.com](https://www.attomdata.com/solutions/property-data-api/))
  powers the owner-record seller categories (mailing≠situs → absentee; NOD/lis
  pendens → pre-foreclosure; equity → high-equity).
- **FSBO / expired / renter** need a licensed feed (PropStream/portal/MLS) — no
  free source; they stay SIMULATED until a provider is configured.

> Compliance: discovered leads are **prospects, not consented contacts**. Scrub
> against the federal + state Do-Not-Call registries (Colorado has its own) and
> follow TCPA calling rules before outreach.

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

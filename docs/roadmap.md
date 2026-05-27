# Roadmap — Eko AI Realtors

Numbering is canonical post-USA-pivot (2026-05-25). The repo is the
customer-facing product; one office = one self-hosted deployment.

## Phase 0 · Bootstrap — ✅ done (`v0.0.1`)

Repo skeleton, Docker Compose stack (Postgres + Redis + backend + frontend),
health endpoint, landing placeholder.

## Phase 1 · CORE — ✅ done (`v0.1.0`)

WhatsApp Business Cloud API webhook (GET handshake + POST inbound with
HMAC-SHA256), LLM client (Kimi primary + MiniMax fallback, inline failover),
models (Lead / Conversation / Message / Property / AgentSettings), Alembic
baseline, intent classifier (`rent | buy | valuation | other` + entity
extraction), and the auto-response orchestrator. SIMULATED mode for dev.

## Phase 2 · Realtor dashboard — ✅ done (`v0.2.0`)

`/leads` list + `/leads/[id]` conversation view, lead metadata, and a
**manual takeover** toggle that pauses the AI for a given lead. `PATCH /leads/{id}`.

## Phase 3 · Multichannel + Email + Bilingual — ✅ done (`v0.3.0`)

**USA pivot**: target shifts to USA realtors. Channel-agnostic schema
(`wa_*` → `external_*`), Email channel via Resend (send + inbound webhook,
SIMULATED mode), and automatic ES/EN language detection + matching replies.

## Phase 4 · Composer + AI suggestions — ✅ done (`v0.4.0`)

Dashboard composer so the realtor can send a manual reply through the lead's
channel, plus a **Suggest replies** button that generates 3 editable LLM drafts.

## Phase 5 · Calendar booking — ✅ done (`v0.5.0`)

Cal.com integration: list slots, create booking, cancel. `VisitsSection` +
`BookingDialog` in the dashboard. SIMULATED mode (no Cal.com account needed for
dev); production via `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID`.

## Phase 6 · Installer + branding + public demo — ✅ done (`v0.6.0`)

- **Settings API + `/settings` page** — brand the instance (agency name/phone,
  agent persona, greeting, languages, business hours) from the dashboard.
- **`scripts/install.sh`** — one-command single-office installer: prereq check,
  `.env` with strong random secrets, build + up, migrations, branding. Channels
  stay SIMULATED unless opted in. See [`install.md`](install.md).
- **`scripts/seed_demo.py`** — idempotent demo dataset (Sunset Realty Group,
  Miami) so a public demo looks alive.
- **Public demo** at `inmo-demo.ekoaiautomation.com` via a dedicated Cloudflare
  Tunnel. See [`setup-demo.md`](setup-demo.md).
- **CI green** for the first time since Phase 1 (Postgres service + migrations,
  ruff config, frontend npm-cache fix).

## Phase 7 · MLS / IDX listings + matching — ✅ done (`v0.7.0`)

- **`Property` model reworked for the USA** (RESO source, status, beds/baths/sqft,
  address, photos…); Alembic `004`.
- **`services/listings.py`**: `fetch_listings` (SIMULATED Miami set / real **RESO
  Web API** OData), `sync_listings` (idempotent upsert), `match_properties_for_lead`
  (intent rent/sale + zone + budget + type).
- **Endpoints**: `GET /properties` (filters), `POST /properties/sync`,
  `GET /properties/{id}`, `GET /leads/{id}/matches`.
- **Frontend**: `/properties` grid + filters + sync button; **Propiedades
  sugeridas** on the lead detail with send-to-lead.
- SIMULATED by default; production via [`setup-mls.md`](setup-mls.md). Post-visit
  follow-up sequences (24h/72h/7d) will ride on this in a later iteration.

## Phase 8 · Lead intelligence — ✅ done (`v0.8.0`)

- **`leads.score`** (0-100) + **`score_breakdown`**; Alembic `005`.
- **`services/scoring.py`** — deterministic `compute_lead_score` (intent, budget,
  engagement, urgency, zone, recency, visit + WON/LOST/PAUSED status gate) with an
  explainable breakdown + tier. Recomputed after each inbound turn.
- **Endpoints**: `sort=score|recent` on the list, `GET /leads/digest`,
  `POST /leads/rescore-all`. `scripts/daily_digest.py` for cron.
- **Frontend**: `ScoreBadge` (🔥/🟡/⚪) in the table + lead detail; **HotLeadsPanel**
  on `/leads`.

## Phase 9 · SMS channel (Twilio) — ✅ done (`v0.9.0`)

- **`services/sms.py`** — `send_sms` (SIMULATED / real Twilio REST API),
  `verify_twilio_signature` (HMAC-SHA1), `parse_inbound_sms`.
- **`POST /api/v1/webhooks/sms`** — signature-validated inbound → orchestrator →
  empty TwiML; reply sent async via REST. Same multichannel path as WhatsApp/email.
- `SMS_SIMULATED=true` default; production via [`setup-twilio.md`](setup-twilio.md).

## Phase 10 · Autonomous nurture + in-conversation listings — ✅ done (`v0.11.0`)

- **Follow-ups**: `FollowUp` model + Alembic `006`. Booking a visit enqueues a
  24h reminder + post-visit sequence (24h / 72h / 7d). `process_due_followups`
  (in-process worker + `scripts/run_followups.py`) sends due ones, skipping human
  takeover / cancelled visits / the 72h nudge if the lead replied.
- **In-conversation listings**: the orchestrator injects real matched listings
  into the system prompt for buy/rent leads with a zone, so the agent offers them.

## Phase 11 · Pilot hardening — auth + analytics — ✅ done (`v0.12.0`)

- **Dashboard auth**: single shared password (`DASHBOARD_PASSWORD`), HMAC-signed
  cookie, `/login` + `AuthGuard`, `require_auth` gate on the data API (gated by
  `AUTH_ENABLED`; off for dev/demo, on for customer installs via the installer).
- **Analytics** (`/analytics` + `GET /api/v1/analytics`): funnel, conversion,
  by channel, by score tier, avg first-response, new leads per day.

## Phase 12 · Discovery — lead search + file import — ✅ done (`v0.13.0`)

Proactive lead sourcing (until now leads were inbound-only):

- **Search** across 4 sources — Google Maps, Yelp, LinkedIn, Colorado SOS — via
  `services/discovery.py` (SIMULATED-first like `listings.py`; real per-source
  when its key is set; Colorado SOS is free/no-key). Ported + adapted from the
  Eko AI sales platform's discovery agent (Paperclip dropped).
- **File import** (`services/file_import.py`): upload a contact DB in **any
  format** — PDF / JPG-PNG (OCR) / TXT / CSV / XLSX / HTML — text is extracted
  then run through the LLM (`json_mode`) to pull out contacts. Graceful: bad
  output → `[]`, never crashes.
- **Preview-and-select** flow: search/upload returns transient results; the user
  picks which to import → they become `Lead` rows (deduped by phone/email).
- API under `/api/v1/discovery` (`/search`, `/upload`, `/import`, protected).
  Frontend `/discovery` page + Discovery link in the nav.
- See [`setup-discovery.md`](setup-discovery.md) for which source needs which key.

## Phase 13 · Voice agent (VAPI / Retell) — ⏳ deferred

Inbound/outbound voice. Deferred until a provider account is set up.

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

## Phase 8 · SMS (Twilio) — ⏳ deferred

SMS as a first-class channel via Twilio. Deferred until a Twilio account is set
up. The multichannel architecture (Phase 3) already accommodates it.

## Phase 9 · Voice agent (VAPI / Retell) — ⏳ deferred

Inbound/outbound voice. Deferred until a provider account is set up.

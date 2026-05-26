# CHANGELOG

All notable changes to **Eko AI Realtors**.

## [0.10.0] — 2026-05-26

### Multilingual dashboard (English default + Spanish) with a language switcher

The realtor dashboard is now multilingual: **English by default, Spanish second**,
with a **language switcher** (globe + EN/ES) in the nav on **every page**.

- **`lib/i18n.tsx`** — client `LanguageProvider` + `useI18n` hook + full EN/ES
  dictionaries. The choice persists to `localStorage` and syncs `<html lang>`.
  `t(key)` falls back to English, then the key.
- **Every UI string** goes through `t()`: nav, pages, badges (status / intent /
  score / visit), leads table + detail, composer, suggestions, property matches,
  visits, booking dialog, properties grid, settings, takeover toggle, messages.
- **Locale-aware formatters** — `relativeTime` / `exactTime` / `formatBudget`
  (USD, en/es) + visit & booking dates follow the active language.
- Pages use a client `PageHeader`; the lead-detail page is now a client component.
  `/about` landing copy refreshed (MLS matching).

This pairs with the agent already replying in the lead's language (Phase 3) — now
the realtor's interface is bilingual too.

## [0.9.1] — 2026-05-26

### SMS hardening — A2P `MessagingServiceSid` + delivery status callbacks

Two production improvements to the SMS channel, surfaced by reading Twilio's API docs:

- **`send_sms` via `MessagingServiceSid`** — when `TWILIO_MESSAGING_SERVICE_SID`
  is set, outbound goes through the A2P 10DLC-registered Messaging Service (the
  Twilio-recommended path for US delivery) instead of the bare `From` number.
  Falls back to `TWILIO_PHONE_NUMBER`.
- **Delivery status callbacks** — new `POST /api/v1/webhooks/sms/status`. With
  `TWILIO_STATUS_CALLBACK_URL` set, `send_sms` asks Twilio to POST status updates
  (`sent` → `delivered`/`undelivered`/`failed` + `ErrorCode`); the backend
  reflects the final state on the outbound `Message` so the dashboard shows real
  delivery (and logs carrier errors like **30034** = A2P 10DLC unregistered).
- `config.py` + `.env.example` + compose: `TWILIO_MESSAGING_SERVICE_SID` +
  `TWILIO_STATUS_CALLBACK_URL`.
- **`docs/setup-twilio.md`** expanded: A2P 10DLC registration (Sole Proprietor vs
  Standard), the Messaging Service webhook override gotcha, and STOP/HELP opt-out
  (handled by Twilio's default Advanced Opt-Out).
- Tests **+4 (120 total)**: status mapper + status-callback e2e.

## [0.9.0] — 2026-05-26

### Phase 9 — SMS channel (Twilio)

A third channel: SMS via Twilio, on the same multichannel architecture as
WhatsApp and email. SIMULATED-first, so it works without an account.

#### Backend

- **`services/sms.py`** — `send_sms` (SIMULATED logs / real Twilio REST API),
  `verify_twilio_signature` (HMAC-SHA1 over the request URL + sorted POST params,
  keyed by the auth token), `parse_inbound_sms` → `ParsedMessage(channel="sms")`.
- **`POST /api/v1/webhooks/sms`** — parses Twilio's form, validates the signature
  (unless SIMULATED), hands off to the orchestrator, returns empty TwiML (the
  reply is sent asynchronously via REST). Signature URL comes from
  `TWILIO_WEBHOOK_URL` or is rebuilt from forwarded headers.
- Dispatcher gains an `sms` branch; idempotency via UNIQUE `messages.external_id`
  (the `MessageSid`).
- `config.py` + `.env.example` + compose: `SMS_SIMULATED` (default true) +
  `TWILIO_ACCOUNT_SID` / `AUTH_TOKEN` / `PHONE_NUMBER` / `WEBHOOK_URL`.
- `scripts/simulate_inbound_sms.py` for smoke testing.

#### Docs

- **`docs/setup-twilio.md`** — account + number + webhook + signature + cost/safety
  notes.

#### Tests

- **+9 (116 total)**: `test_sms_service.py` (7) + `test_sms_webhook_e2e.py` (2).

#### Roadmap

- Voice (VAPI/Retell) remains **Phase 10**, deferred until a provider account exists.

## [0.8.0] — 2026-05-26

### Phase 8 — Lead intelligence (scoring + prioritization + digest)

Leads are now scored and ranked so the realtor knows who to call first — no
external accounts needed (it scores signals the pipeline already produced).

#### Backend

- **`leads.score`** (0-100, indexed) + **`score_breakdown`** (JSON) — Alembic `005`.
- **`services/scoring.py`** — `compute_lead_score` is deterministic and cheap:
  intent (20) · budget (15) · engagement (15) · urgency (12) · zone (10) ·
  recency (10) · visit (10) · property_type (8), then a **status gate**
  (WON/LOST → 0, PAUSED → ½). Returns an explainable breakdown + tier. No
  per-lead LLM call. `rescore_lead` / `rescore_all` (grouped queries).
- The orchestrator **recomputes the score after every inbound turn**.
- **API**: `score`/`score_breakdown` in `LeadOut`; `sort=score|recent` (default
  `score`); `GET /leads/digest` (top hot/active leads); `POST /leads/rescore-all`.
- **`scripts/daily_digest.py`** — cron-friendly hot-leads digest.

#### Frontend

- **`ScoreBadge`** — 🔥 hot (≥67) / 🟡 warm (≥34) / ⚪ cold, in the leads table
  (now score-sorted) and the lead detail header.
- **`HotLeadsPanel`** — "Leads calientes — a quién llamar primero" on `/leads`,
  fed by `/leads/digest`.

#### Tests

- **+11 (107 total)**: `test_scoring.py` (8 pure) + `test_lead_digest.py` (3 API).

#### Roadmap

- SMS (Twilio) → **Phase 9**, Voice (VAPI/Retell) → **Phase 10** — both still
  deferred until the external accounts exist.

## [0.7.0] — 2026-05-25

### Phase 7 — MLS / IDX listings (RESO) + per-lead property matching

The agent now works against real-estate inventory: listings are ingested from a
RESO Web API feed (SIMULATED in dev), browsable at `/properties`, and matched to
each lead's intent / zone / budget on the lead detail.

#### Backend

- **`Property` model reworked for the USA**: `source` (`reso`/`idx`/`mls`/`manual`),
  `status` (`active`/`pending`/`sold`/`off_market`), `bedrooms`, `bathrooms`
  (half-baths, `2.5`), `sqft`, `property_type`, `address`/`city`/`state`/`zip_code`,
  `zone` (neighborhood), `latitude`/`longitude`, `photos`, `description`,
  `listed_at`. Alembic `004` drops + recreates the (empty) EU placeholder table.
- **`services/listings.py`**:
  - `fetch_listings` — SIMULATED returns a curated 9-listing Miami set; real mode
    queries a **RESO Web API** (OData) feed and maps the RESO Data Dictionary
    fields. Configured via `RESO_BASE_URL` + `RESO_ACCESS_TOKEN`.
  - `sync_listings` — idempotent upsert by `(source, external_id)`.
  - `match_properties_for_lead` — intent gate (rent vs sale) + zone + budget
    (±10%) + property type, ranked by price.
- **Endpoints**: `GET /properties` (filters), `POST /properties/sync`,
  `GET /properties/{id}`, `GET /leads/{id}/matches`.
- **`scripts/sync_listings.py`** ingest CLI (cron-friendly). Config + `.env.example`
  + compose env (`LISTINGS_SIMULATED` default true, `RESO_*` for prod).

#### Frontend

- **`/properties`** — grid of listing cards with zone / max-price filters and a
  **Sincronizar MLS** button.
- **`MatchesSection`** on the lead detail — "Propiedades sugeridas" matched to the
  lead, each with **Enviar al lead** (sends a formatted blurb via the composer).
- **Propiedades** nav link.

#### Docs

- **`docs/setup-mls.md`** — connecting a real RESO Web API / IDX feed + the
  matching rules + an IDX-compliance note (why the public demo stays SIMULATED).

#### Tests

- **+12 (96 total)**: `test_listings_service.py` (5) + `test_properties_api.py`
  (7 — idempotent sync, filters, 404s, buy-lead matches sale-only, rent-lead
  matches rentals-only).

## [0.6.0] — 2026-05-25

### Phase 6 — Single-customer installer + branding panel + public demo

The product is now installable by a single office in one command, brandable
from the dashboard, and demoable from a live public URL — and CI is green for
the first time since Phase 1.

#### Branding panel (Settings API + `/settings` page)

- **`GET/PUT /api/v1/settings`** over the `AgentSettings` singleton (auto-created
  with defaults). `PUT` is a partial update; `languages` is normalized to
  lowercase + de-duped. Empty body → 400, unknown field → 422.
- **`/settings`** dashboard page: agency name + phone, agent persona (system
  prompt), greeting template, languages (es/en/pt/fr chips), and business hours
  (per-day open/close or closed). A **Configuración** link is in the nav.
  Changes apply immediately to new auto-replies.

#### Single-customer installer

- **`scripts/install.sh`** — interactive installer: checks prerequisites
  (Docker/Compose/daemon), generates a `.env` with **strong random secrets**
  (`POSTGRES_PASSWORD`, `WHATSAPP_VERIFY_TOKEN`, mode `600`, never printed),
  builds + starts the stack, waits for the health check, runs
  `alembic upgrade head`, and sets the agency branding via the API. Channels stay
  **SIMULATED** unless explicitly opted in. `--no-prompt` for provisioning scripts.
- **`docs/install.md`** — full single-office install + channel-enable + upgrade
  guide (no GPU — the LLM is cloud-hosted Kimi + MiniMax).

#### Public demo

- **`backend/scripts/seed_demo.py`** — idempotent demo dataset (*Sunset Realty
  Group*, Miami): 6 bilingual EN/ES leads + realistic conversations + 2 visits
  (scheduled / completed). Every row is tagged `meta.demo=true`; `--reset` wipes
  only the demo rows, `--keep-settings` preserves branding.
- **`deploy/cloudflared/config.example.yml`** + **`docs/setup-demo.md`** — a
  **dedicated** Cloudflare Tunnel for `inmo-demo.ekoaiautomation.com`, isolated
  from the sales-platform tunnel. Safety model: all channels SIMULATED (a visitor
  can never trigger a real send), seed data only, optional Cloudflare Access.

#### CI (green for the first time since Phase 1)

- **Backend**: added a real Postgres service + `alembic upgrade head` so the
  DB-backed tests actually run instead of erroring on a missing server. Ruff now
  ignores the 3 rules that conflict with intentional idioms (`B008` FastAPI
  `Depends`/`Query` defaults, `UP042` `str`+`Enum` for pg_enum, `UP037`
  SQLAlchemy quoted forward-refs) and auto-fixes the rest.
- **Frontend**: dropped `cache: npm` (there's no `package-lock.json`, so the
  cache step was aborting the whole job before tsc/lint).

#### Tests

- **+7 (84 total)**: `test_settings_api.py` (GET auto-create, PUT update +
  persistence, partial update, languages normalize/dedupe, empty-body 400,
  unknown-field 422, empty-languages 422). The singleton model test no longer
  couples to a specific `agency_name`.

## [0.5.0] — 2026-05-25

### Phase 5 — Calendar booking (Cal.com) + dashboard VisitsSection

The realtor can now book property visits from the dashboard. `/leads/[id]`
shows a **Visitas** section under the conversation with upcoming + past
visits, an **Agendar visita** button that opens a slot picker (next 7 weekdays,
groups by day, click slot + optional address/notes → Confirm), and a per-card
cancel.

#### Backend

- **`Visit` model** + Alembic migration `003_phase5_visits` (5 columns +
  `external_booking_id` UNIQUE for idempotency + status enum).
- **`services/calendar_cal.py`** — Cal.com v2 API wrapper:
  - `list_available_slots(start, end, timezone, busy_starts)` —
    SIMULATED returns weekday slots at 10/11/14/15/16 in-memory; production
    calls Cal.com `/v2/slots/available` with `cal-api-version: 2024-08-13`.
  - `create_booking(start_time, attendee_name, email, phone, notes, tz, duration)`
    — SIMULATED returns `calcom-sim-<uuid>` ids no-network; real Cal.com
    `POST /v2/bookings` otherwise.
  - `cancel_booking(external_id)` — IDs starting with `calcom-sim-` always
    cancel locally even in production mode (lets you clean up dev data).
- **Endpoints**:
  - `GET /api/v1/leads/{id}/calendar/slots?days=7&timezone=UTC`
  - `POST /api/v1/leads/{id}/calendar/book` → `Visit`
  - `GET /api/v1/leads/{id}/visits`
  - `POST /api/v1/visits/{id}/cancel` `{reason?}`
- Slots **excludes already-booked starts** for the same lead (`busy_starts`
  set built from active visits) so no double-booking.
- Attendee email/phone auto-picked from `lead.phone` (email if it contains `@`,
  phone otherwise). Real Cal.com requires email; SIMULATED accepts phone-only.

#### Frontend

- **`VisitsSection`** — lists upcoming + past visits with status badges,
  formatted ES dates, address, notes, per-card cancel button.
- **`BookingDialog`** — modal slot picker grouped by day, optional address +
  notes, real-time validation, `router.refresh()` style update via
  `onBooked()` callback.
- **`VisitStatusBadge`** — color-coded badge for the 5 visit statuses.
- `lib/api.ts` — `calendarApi.slots/book` + `visitsApi.list/cancel` + types.

#### Config

- + `CALENDAR_SIMULATED=true` (dev default — no Cal.com account required)
- + `CALCOM_BASE_URL=https://api.cal.com`
- `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID` from Phase 0 now actually used.

#### Tests (+13, total 77)

- `test_calendar_service.py` (7): simulated slots weekday-only, hours match
  the constant, busy_starts filter, list_available_slots simulated branch,
  create_booking returns `calcom-sim-` id, cancel_booking returns True,
  `calcom-sim-` id cancels locally even when SIMULATED=false.
- `test_visits_api.py` (6): /slots returns weekday slots, /slots 404 on
  missing lead, /book persists Visit with `calcom-sim-` id, /visits lists
  inserted, cancel flips status + rejects re-cancel, /slots excludes
  already-booked starts (no double-booking).

#### Docs

- `docs/setup-calcom.md` — Cal.com account + event type + API key + smoke
  test + troubleshooting matrix.

## [0.4.0] — 2026-05-25

### Phase 4 — Composer manual + AI reply suggestions

Completes the human-takeover loop. Phase 2 added the toggle that pauses the AI
agent; Phase 4 adds the UI to actually reply from the dashboard, plus an AI
helper that drafts 3 options the realtor can pick / edit / send.

#### Frontend

- **`Composer`** component below the chat in `/leads/[id]`: textarea +
  character counter (0/4000) + Send button. Sends via the lead's last-active
  channel — no channel picker needed for the common case.
- **"Sugerir respuestas"** button generates 3 alternative replies from the
  LLM. Each suggestion is a clickable card that fills the textarea — the
  realtor can edit before sending. Powered by the same Kimi + MiniMax fallback
  used by the agent itself.
- `router.refresh()` after a successful send → the new outbound bubble appears
  immediately, no page reload.
- Errors render inline below the composer (no toast/modal), keeping the
  realtor's attention on the conversation.

#### Backend

- **`POST /api/v1/leads/{id}/messages`** — accepts `{ "text": ..., "subject"?: ... }`.
  Auto-picks the channel from the most recently-active Conversation. For email,
  derives `Re: <subject>` from the last inbound + threads via `In-Reply-To`
  header. Persists as `Message(sender=HUMAN, direction=OUTBOUND)` and routes
  through the existing `_dispatch_send()` dispatcher.
- **`POST /api/v1/leads/{id}/suggestions`** — accepts `{ "count": int }`
  (clamped to `[1, 5]`). Builds a system prompt asking for a JSON array of N
  diverse short replies + the language-steering line from Phase 3. Parses the
  array tolerantly (matches first `[...]` block, drops empties, coerces to
  strings).
- **Degrades gracefully**: any LLM failure / invalid JSON / missing lead /
  empty conversation returns `{"suggestions": [], "error": "..."}` with HTTP
  200 so the UI shows an empty state instead of crashing.

#### Orchestrator

- Two new functions in `app/services/conversation.py`:
  - `send_human_message(lead_id, text, db, subject?)` — dispatches via the
    existing channel dispatcher and persists with `sender=HUMAN`.
  - `generate_reply_suggestions(lead_id, db, count=3)` — re-uses the same
    history-build + language-detection pipeline as the auto-reply, but with a
    "give me 3 options as a JSON array" prompt.

#### Tests

- **63 passing** on live ROG Postgres (+8 new):
  - human-send happy path (WhatsApp SIMULATED → outbound persists SENT
    with synthetic wamid).
  - human-send lead not found → `{status: error, error: lead_not_found}`.
  - human-send empty text → HTTP 400.
  - human-send lead without any Conversation → `error: no_active_conversation`.
  - suggestions happy path (3 quoted in valid JSON).
  - suggestions with prose around the JSON (parser extracts the array).
  - suggestions LLM returns non-JSON → empty list + error field.
  - suggestions count=99 clamps to 5.

## [0.3.0] — 2026-05-25

### Phase 3 — Multichannel + Email (Resend) + Bilingual (USA pivot)

**Strategic pivot**: target customers shift from EU real-estate offices
(WhatsApp-first) to USA realtors where SMS, Email and phone calls dominate.
WhatsApp remains an optional channel for international clients. Roadmap
reordered: Phase 4=SMS (Twilio), Phase 5=Voice (VAPI/Retell), Phase 6=Calendar
booking (moved from Phase 3), Phase 7=MLS/IDX, Phase 8=installer.

#### Multichannel refactor

- Schema rename to channel-agnostic names:
  - `messages.wa_message_id` → `external_id` (120 → 255 chars)
  - `messages.wa_status` → `delivery_status`
  - `conversations.wa_thread_id` → `external_thread_id` (80 → 255)
  - `leads.phone` widened 32 → 254 chars (RFC 5321 max email length — same
    column doubles as identifier for whatsapp/sms/voice and email)
- New `messages.subject` column (nullable, email-only).
- New `conversations.channel` index (queries filter on it constantly).
- `ParsedMessage` moved to `app/services/_common.py` with `channel`,
  `external_id`, `from_identifier`, `content`, `subject`, `thread_id` —
  single shared type emitted by every channel parser.
- Orchestrator routes outbound through `_dispatch_send(channel, ...)` →
  `whatsapp_send` / `email_send` (lazy imports). One conversation per
  `(lead, channel)`: a lead writing via both WhatsApp AND email gets two
  active conversations.

#### Email channel (Resend)

- `services/email.py`:
  - `send_email(to, subject, body_text, in_reply_to)` POSTs to
    `api.resend.com/emails` with threading headers.
  - `parse_inbound_email(payload)` returns `ParsedMessage(channel="email")`
    with subject + `thread_id` from In-Reply-To/References/Message-ID.
  - `verify_resend_signature(...)` Svix-style HMAC-SHA256 with multi-sig
    header support (key rotation).
  - `EMAIL_SIMULATED=true` (dev default) logs outbound instead of POSTing —
    no Resend account or domain DNS required.
- `POST /api/v1/webhooks/email` — same idempotency contract as the WhatsApp
  webhook (200 + UNIQUE `external_id` catches retries).
- New env vars: `EMAIL_SIMULATED`, `RESEND_API_KEY`, `RESEND_FROM`,
  `RESEND_WEBHOOK_SECRET`.

#### Bilingual agent

- `services/i18n.py` — `detect_language()` (langdetect, deterministic seed) +
  `pick_supported_language()` (clamps to AgentSettings.languages whitelist) +
  `language_instruction()` (steering line for the system prompt).
- Orchestrator detects on the **latest inbound only** (no bias from historical
  AI replies), picks `target_lang`, appends an "IDIOMA: el cliente escribe
  en X. Responde EXCLUSIVAMENTE en X" line to the system prompt.
- Classifier accepts optional `language_hint` so it disambiguates words like
  "rent" (EN) vs "renta" (ES, can mean income). JSON output values still
  English (rent/buy/valuation/other) regardless of input language.

#### Dashboard

- `MessageBubble` renders a channel icon next to the sender label (envelope
  email / message-circle WhatsApp / message-square SMS / phone voice) +
  shows the email subject above the bubble when channel="email".
- `LeadsTable` shows a heuristic glyph (email vs phone) next to the
  identifier so the realtor knows at a glance which channel the lead used.
- API client (`lib/api.ts`) interfaces updated to new field names.

#### Tests

- **55 passing** on live ROG Postgres (+10 new):
  - `test_email_service.py` (8) — signature accept/reject/missing/wrong-secret/
    multi-sig-one-matches + parser minimal/threading/html-fallback/non-received
    skipped/missing-from-skipped + send_email SIMULATED.
  - `test_i18n.py` (9) — detect ES/EN, short-text fallback, pick_supported,
    language_instruction both personas, unknown lang fallback.
  - `test_email_webhook_e2e.py` (1) — end-to-end POST → Lead (email
    identifier), Conversation(channel="email"), 2 Messages with subject +
    threading.
- Existing tests updated to use `external_id` / `delivery_status`.

## [0.2.0] — 2026-05-25

### Phase 2 — Realtor dashboard (UI for the Phase 1 backend)

What was protocol-only after v0.1.0 now has a face. The realtor can open
`http://<host>:3004/leads` and see the leads the AI captured, drill into
any conversation, and click one button to take over from the agent.

#### Frontend (Next.js 14 App Router)

- **`/leads`** — paginated list with status + intent filters (querystring-based,
  Suspense-wrapped so SSR works). Each row shows name, phone, status badge,
  intent badge, zone, budget range, relative time of last message, and a "Humano"
  pill when human_takeover is on.
- **`/leads/[id]`** — detail page with:
  - Lead header (avatar, name, phone, status + intent badges, last activity).
  - Metadata grid (zona, presupuesto, tipo, urgencia, created/updated timestamps).
  - **Takeover toggle** (top-right of header) — one-click PATCH to flip
    `human_takeover`. While ON, the orchestrator skips AI auto-reply (Phase 1
    already enforces this).
  - Conversation thread (chat-style bubbles, inbound left/outbound right,
    per-message LLM provider badge + Meta delivery status + timestamps).
- **`/about`** — public-facing landing kept (the Phase 0 placeholder) for
  sharing the product link. `/` redirects to `/leads`.
- **API client** — typed in `frontend/lib/api.ts` (Lead, Conversation, Message
  interfaces + `leadsApi.list/get/patch` + `conversationsApi.get`). All requests
  go through same-origin `/api/...`, which `next.config.js` rewrites to the
  backend container — works identically from LAN, Tailscale, or future
  Cloudflare tunnel without per-env URLs.
- **Components**: `Nav`, `StatusBadge`, `IntentBadge`, `FilterBar`, `LeadsTable`,
  `MessageBubble`, `LeadDetail`, `TakeoverToggle`. All Tailwind, Eko-violet
  palette, lucide-react icons.

#### Backend

- **`PATCH /api/v1/leads/{id}`** — partial update endpoint. Accepts any subset
  of `name | status | intent | zone | budget_min | budget_max | property_type |
  urgency | human_takeover`. Empty body → 400. Unknown field → 422 (Pydantic
  `extra='forbid'`). Missing lead → 404.

#### docker-compose

- Frontend now reads `INTERNAL_API_URL` at runtime for the rewrite (defaults
  to `http://backend:8000`). Build arg `NEXT_PUBLIC_API_URL` defaulted to `/api`
  since client JS no longer touches an absolute backend URL.

#### Tests

- `test_leads_api.py` (+8): list envelope, get 404, PATCH takeover roundtrip,
  PATCH partial update preserves untouched fields, PATCH empty 400, PATCH
  unknown field 422, PATCH invalid enum 422, PATCH 404. Total **33 passing**.

#### Brand

- Final rename Inmobiliario → **Eko AI Realtors** in `<title>`, landing copy,
  README, CLAUDE.md.

## [0.1.0] — 2026-05-25

### Phase 1 CORE — WhatsApp 24/7 + Kimi/MiniMax fallback + Lead capture

The product is now functional end-to-end at the protocol layer: an inbound
WhatsApp message → upsert Lead → save inbound message → classify intent →
generate AI reply → save outbound message → send. Frontend dashboard is still
Phase 2 (next).

#### Identity & infrastructure

- `CLAUDE.md` at repo root: anti-patterns ("never touch sales platform repos
  or containers"), port map across all 4 stacks on the ROG, brand name
  "Eko AI Realtors" vs repo name `Eko-AI-RealEstate`, LLM decisions
  (Kimi+MiniMax, NOT Anthropic OAuth for customer traffic), phase status.
- `docker-compose.yml` port remap to `5434/6381/8011/3004` (no collisions with
  sales prod, sales main dev, or pricing-v2 preview).
- Container rename `eko-realestate-*` for unambiguous identity.
- `.github/workflows/ci.yml`: ruff + pytest (backend) + tsc + lint (frontend)
  on every PR to main.
- GitHub repo: 10 topics, milestones for Phases 1–5, brand-aligned description.
- Memory file `project_eko_ai_realestate.md` + MEMORY.md pointer for
  cross-session continuity.

#### Database (SQLAlchemy 2 async + Alembic)

- `backend/app/db/base.py` — async engine + sessionmaker + get_db() FastAPI dep
  + `pg_enum()` helper (uses `.value` lowercase for Postgres enum members, not
  Python NAME).
- 5 models in `backend/app/models/`:
  - `Lead` — phone (UNIQUE), name, status enum (7 states), intent enum
    (rent/buy/valuation/other), budget_min/max, zone, property_type, urgency,
    last_message_at, human_takeover, meta (JSON), timestamps.
  - `Conversation` — lead_id FK CASCADE, channel, wa_thread_id, status, summary,
    started_at/last_at.
  - `Message` — conversation_id FK CASCADE, direction (inbound/outbound), sender
    (lead/agent/human), content, **UNIQUE wa_message_id** (webhook idempotency),
    wa_status, llm_provider, llm_model, created_at.
  - `Property` — placeholder for Phase 4 (Idealista/Fotocasa scrapers).
  - `AgentSettings` — singleton (id=1) with Spanish defaults for agent_persona,
    greeting_template, languages, business_hours.
- Baseline migration `20260525_1200_phase1_baseline.py` creates the 5 tables
  + indices + FK cascades + enum types.

#### LLM client (Kimi primary + MiniMax fallback)

- `backend/app/services/llm.py` — single entry `generate_reply()`. Inline
  fallback per request: if Kimi times out / 429 / 5xx, retries against MiniMax
  in the same request before raising `LLMUnavailable`.
- Both providers use the `anthropic` Python SDK with custom `base_url`
  (Anthropic-messages protocol).
- `json_mode=True` appends a "return JSON only" steer for the classifier.
- A/B test script (`backend/scripts/llm_ab_test.py`) ran 5 representative
  Spanish realtor prompts through both providers; results:
  - Kimi: avg 3,371 ms / 5/5 OK / more concise
  - MiniMax: avg 5,626 ms / 5/5 OK / more conversational
  - Decision: keep Kimi primary, MiniMax fallback (both produce natural ES).

#### Intent classifier

- `backend/app/services/classifier.py` — `classify_intent(messages)` returns
  `IntentResult` Pydantic schema (intent + confidence 0-1 + entities).
- Entities extracted: zone, budget_min, budget_max, property_type, urgency.
- Coerces `"1.500€"` strings to `1500.0` floats.
- Three failure modes degrade gracefully to `intent=OTHER + raw_response`:
  LLMUnavailable, JSON not parseable, JSON valid but schema mismatch.

#### WhatsApp webhook + orchestrator

- `backend/app/services/whatsapp.py`:
  - `verify_signature()` — HMAC-SHA256 with `WHATSAPP_APP_SECRET`,
    constant-time compare.
  - `parse_inbound_message()` — flattens Meta's nested
    entry/changes/value/messages tree; non-text types persisted as
    `[imagen]/[audio]/[video]/...` placeholders.
  - `send_text_message()` — POSTs to Meta Graph API; LOGS instead when
    `WHATSAPP_SIMULATED=true` (dev default).
- `backend/app/services/conversation.py` — `handle_inbound_message()`
  orchestrates the full 10-step turn: lead upsert → conv get-or-create →
  idempotency check → save inbound → human_takeover bypass → build history →
  classify intent (apply if confidence ≥ 0.55, never overwrite existing values)
  → load AgentSettings → generate reply → save outbound (PENDING) → send →
  update status (SENT/FAILED).
- `backend/app/api/v1/webhooks/whatsapp.py`:
  - `GET /api/v1/webhooks/whatsapp` — Meta verification handshake.
  - `POST /api/v1/webhooks/whatsapp` — signature verify (skipped in SIMULATED)
    → parse → orchestrator per message; always returns 200 unless body is
    malformed (Meta retries non-200; idempotency handles retries cleanly).
- Startup log warning if `WHATSAPP_SIMULATED=true` AND `APP_ENV=production`.

#### API routes

- `GET /api/v1/leads` — paginated list with `?status=` + `?intent=` filters.
- `GET /api/v1/leads/{id}` — detail.
- `GET /api/v1/conversations/{lead_id}` — most recent conversation + full
  message history ordered chronologically.

#### Tests (23 total, all passing on live ROG Postgres)

- `test_signature.py` (7) — HMAC valid, invalid, missing, wrong-prefix,
  body-tampered, wrong-secret, empty-secret.
- `test_llm_fallback.py` (4) — primary OK no fallback, primary timeout →
  fallback, both fail → LLMUnavailable, primary unconfigured → skip to fallback.
- `test_classifier.py` (7) — clean JSON, confidence clamp, prose-wrapped JSON,
  invalid JSON degrades, invalid enum degrades, LLMUnavailable degrades,
  budget coercion.
- `test_webhook_e2e.py` (4) — GET handshake accept, GET handshake reject,
  inbound text creates lead + reply, duplicate wa_message_id is idempotent
  (only 2 messages persist after 2 POSTs).
- `test_models.py` (2) — Lead/Conversation/Message roundtrip,
  AgentSettings singleton defaults.
- `test_health.py` (1) — health endpoint contract.

#### Scripts & docs

- `backend/scripts/simulate_inbound.py` — CLI to POST a simulated WhatsApp
  payload to the webhook for manual testing.
- `backend/scripts/llm_ab_test.py` — side-by-side LLM A/B with 5 Spanish
  realtor prompts.
- `docs/setup-whatsapp.md` — full production setup walkthrough (Meta App
  creation, secrets, webhook registration, troubleshooting matrix).
- `docs/architecture.md` — trust boundary + stack rationale (Postgres,
  Ollama-as-option, port choices).
- `docs/roadmap.md` — Phase 1 ✅ done, Phase 2-5 status.

## [0.0.1] — 2026-05-25

### Bootstrap

- Repo initialized with project skeleton (FastAPI + Next.js + Postgres + Redis)
- `docker-compose.yml` brings up the full stack locally
- Health endpoint at `GET /api/v1/health`
- Placeholder landing page on the frontend
- README + architecture + roadmap docs
- `.env.example` with the env vars required for Phase 1 (WhatsApp + LLM + DB)

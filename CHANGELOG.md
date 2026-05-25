# CHANGELOG

All notable changes to **Eko AI Realtors**.

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

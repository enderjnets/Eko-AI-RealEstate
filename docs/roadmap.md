# Roadmap — Eko AI Realtors

## Phase 0 · Bootstrap — ✅ done (`v0.0.1`, 2026-05-25)

- Repo created, project structure laid out.
- Docker Compose stack: Postgres + Redis + backend + frontend.
- Health endpoint.
- Landing placeholder.

## Phase 1 · CORE — ✅ done (`v0.1.0`, 2026-05-25)

The differentiator: a WhatsApp agent that answers inbound 24/7, captures and classifies leads, with hosted LLMs (Kimi 2.6 primary + MiniMax M2.7 fallback). All on one Docker Compose stack ready to deploy to the customer's hardware (or VPS) when piloting starts.

- ✅ Webhook receiver for Meta WhatsApp Business Cloud API:
  - GET handshake with `hub.challenge` echo.
  - POST inbound with HMAC-SHA256 signature verification (`X-Hub-Signature-256`).
- ✅ LLM client (`app/services/llm.py`): Kimi primary + MiniMax fallback **inline per request** (no separate watchdog). Uses the `anthropic` SDK with custom `base_url`.
- ✅ Models: `Lead`, `Conversation`, `Message`, `Property`, `AgentSettings` (singleton).
- ✅ Alembic baseline migration.
- ✅ Intent classifier (`rent | buy | valuation | other`) + entity extraction (zone, budget, property_type, urgency). Pydantic schema validated; graceful degradation to OTHER on bad LLM output.
- ✅ Auto-response orchestrator (`app/services/conversation.py`):
  1. Receive WhatsApp message → verify signature → parse.
  2. Find or create Lead by phone (idempotency via UNIQUE `wa_message_id`).
  3. Persist inbound Message + update `Lead.last_message_at`.
  4. Honor `human_takeover` flag (skip AI reply when on).
  5. Classify intent → apply to Lead if confidence ≥ 0.55.
  6. Generate reply with Kimi/MiniMax + agency persona.
  7. Persist outbound Message → send via Graph API (or LOG in SIMULATED mode).
- ✅ Tests: 23 total (signature/HMAC + LLM fallback + classifier + webhook E2E + models + health).
- ✅ A/B script `scripts/llm_ab_test.py` validated both providers against 5 realtor prompts in Spanish.
- ✅ Simulator `scripts/simulate_inbound.py` for manual CLI smoke testing.
- ✅ Doc `docs/setup-whatsapp.md` for the production Meta Business App registration.
  5. Send via WhatsApp Cloud API
- Unit tests with simulated WhatsApp payloads (no real Meta calls).

## Phase 2 · Realtor dashboard

- `/leads` list view: phone, intent, last message, status (`active`, `won`, `lost`).
- `/leads/[id]` conversation view: chat history, intent, lead score, suggested next reply.
- **Manual takeover**: a switch that pauses the agent for this lead — human-only replies thereafter.
- **Override edit**: human edits the suggested reply before it's sent.
- Localhost-only by default (no auth complexity for V1; add basic-auth before exposing to a customer LAN).

## Phase 3 · Calendar booking

- Cal.com integration: list slots, create booking, send confirmation through WhatsApp.
- Google Calendar provider as alternative (toggle via `CALENDAR_PROVIDER`).
- Conversational flow:
  - Agent recognizes "quiero ver" / "puedo visitar" intent.
  - Replies with 3 available slots (next 7 days).
  - Lead picks one → booking created → confirmation sent.
  - Visit appears in dashboard.

## Phase 4 · Listings + Follow-up

- **Scrapers** (Playwright):
  - Idealista: filter by zone, daily cron, save to `Property` table.
  - Fotocasa: same.
- **Dashboard view**: `/properties` list with filters.
- **Conversational use**: agent can recommend a property from the local database when a lead asks "tienes algo en X zona?".
- **Post-visit follow-up sequence**:
  - 24 h after the visit: "¿Qué te pareció la propiedad? ¿Quieres ver algo similar?"
  - 72 h: nudge if no reply.
  - 7 d: "Tenemos nuevas propiedades parecidas. ¿Te las paso?"
  - Each step is queued with Celery beat and skipped if the human takes over.

## Phase 5 · Deployment & Onboarding

- Single-customer installer script (`scripts/install.sh`):
  - Verifies hardware meets minimum (RTX 3060+ or Mac M1 16 GB+).
  - Pulls images, pulls model, initializes DB.
  - Walks the user through `.env` setup (WhatsApp, Cal.com).
- Customer-facing admin panel for branding (logo, agency name, default greeting).
- Public demo at `inmo-demo.ekoaiautomation.com` (ROG-hosted, Cloudflare tunnel).

# Roadmap — Eko AI Inmobiliario

## Phase 0 · Bootstrap (this commit)

- ✅ Repo created, project structure laid out.
- ✅ Docker Compose stack: Postgres + Redis + Ollama + backend + frontend.
- ✅ Health endpoint.
- ✅ Landing placeholder.

## Phase 1 · CORE (next session)

The differentiator: a WhatsApp agent that answers inbound, captures and classifies leads, with a local LLM.

- Webhook receiver for Meta WhatsApp Business Cloud API.
  - Verify token handshake (`GET /webhooks/whatsapp` with `hub.challenge`).
  - Message receiver (`POST /webhooks/whatsapp`) with signature verification (`X-Hub-Signature-256`).
- Ollama client (`app/services/llm.py`) with conversation streaming.
- Models: `Lead`, `Conversation`, `Message`, `Property`.
- Alembic baseline migration.
- Intent classifier (`rent | buy | valuation`) — zero-shot prompt against the local model.
- Auto-response loop:
  1. Receive WhatsApp message
  2. Find or create the Lead (by phone number)
  3. Append Message to Conversation
  4. Generate reply with Ollama (using conversation history + intent + agency profile prompt)
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

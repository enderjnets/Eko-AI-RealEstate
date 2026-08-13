# CLAUDE.md — Eko AI Realtors

> Project anchor for Claude (and any other AI agent) working in this repository.
> Read top-to-bottom before making changes. Anti-patterns are non-negotiable.

## What this is

**Eko AI Realtors** is the **customer-facing product** sold to real-estate
agencies. Since 2026-08-06 it is a **multi-tenant mother system**: one
installation we operate, with each client agency as an `Organization` inside it.
The Phase 6 single-customer installer (`scripts/install.sh`) is legacy — kept,
not deleted, because `org_id` is present everywhere and a dedicated deployment is
simply an install with one org.

Isolation between agencies is enforced by **Postgres row-level security**, not by
remembering to filter. Read `backend/app/db/base.py` and
`backend/tests/test_tenant_isolation.py` before touching any query: the app
connects as a role *without* `BYPASSRLS` on purpose, and pointing
`DATABASE_URL_APP` at the owner would make every isolation test pass while
isolating nothing.

It provides:

1. A **WhatsApp 24/7 agent** that answers inbound leads in Spanish.
2. **Lead capture + intent classification** (`rent | buy | valuation`) into a
   local database.
3. **Visit booking** via Cal.com / Google Calendar.
4. **Listings ingest** from Idealista / Fotocasa (Phase 4).
5. **Post-visit follow-up sequences** (Phase 4).
6. A **realtor dashboard** for human oversight + manual takeover (Phase 2).

The repo / GitHub project name is `Eko-AI-RealEstate`. The **brand name** for
the product, used in README / landing / marketing copy, is **"Eko AI Realtors"**
(the more recognizable customer-facing name). Keep both in sync.

## Three parallel lines of work (DO NOT confuse)

| Line | Repo / Branch | Worktree | Purpose | Who works it |
|---|---|---|---|---|
| **Eko AI Main** | `Eko-AI-Business-Automation` rama `main` | `~/Eko-AI-main` | The sales platform **we** use to sell Eko AI services | A separate Claude session |
| **Pricing v2 marketing** | `Eko-AI-Business-Automation` rama `feature/pricing-v2` | `~/Eko-AI-Bussinnes-Automation` | Marketing page **inside the sales platform** that advertises this product (Eko AI Realtors) and other verticals | (Preview container `eko-frontend-pricing-v2:3002`) |
| **Eko AI Realtors** ← this repo | `Eko-AI-RealEstate` rama `main` | `~/Eko-AI-RealEstate` | The customer product itself | **You, here.** |

## CRITICAL Anti-patterns — read every time

1. **NEVER touch `~/Eko-AI-Bussinnes-Automation/` or `~/Eko-AI-main/`** from
   sessions working in this repo. Those are the sales platform; modifying them
   here would clobber the other session's work and risk production.
2. **NEVER touch containers `eko-frontend` (`:3001`), `eko-backend` (`:8000`),
   `eko-db` (`:5432`), `eko-redis` (`:6379`), `eko-pipeline` (`:8002`),
   `eko-celery-*`.** They are production of the sales platform. Customers see
   them.
3. **NEVER touch containers `eko-frontend-main`, `eko-backend-main`,
   `eko-db-main`, `eko-redis-main`** (the `:3003 / :8010 / :5433 / :6380`
   parallel "main dev" stack). They belong to the other session.
4. **NEVER touch `eko-frontend-pricing-v2` (`:3002`).** That is the preview of
   the pricing-v2 marketing branch.
5. **NEVER use Anthropic OAuth (Claude Max plan token) for the customer
   product LLM.** That is for our personal Claude Code / OpenClaw usage and
   would violate Anthropic ToS at scale. Use **Kimi + MiniMax** here, period.
6. **NEVER bake API keys, customer phone numbers, or WhatsApp tokens into
   committed files.** Always read from `.env` (gitignored).
7. **WhatsApp is DISABLED by default** (`WHATSAPP_ENABLED=false`). This is a US
   install: the channels are SMS, voice and email. Enable it only if a customer
   asks for it AND has a configured Meta Business app.

   **NEVER enable it with empty secrets.** `WHATSAPP_SIMULATED` does not only
   control sending — it also switches on INBOUND HMAC verification. With
   `WHATSAPP_APP_SECRET` empty, every inbound webhook returns 403 until Meta
   disables the subscription, and the startup line that mentioned WhatsApp at
   all disappears, so the install ends up quieter and more broken. The backend
   now refuses to start in that combination.

   (This rule used to read "NEVER ship `WHATSAPP_SIMULATED=true` to a customer
   install". Followed literally on an install with no Meta app — which is every
   install today — it produced exactly the outage above.)

## Port map (ROG `100.88.47.99` / `10.0.0.240`)

We coexist with three other stacks. Use exactly these ports for this product:

| Service | Port | Container |
|---|---|---|
| Postgres | **5434** | `eko-realestate-db` |
| Redis | **6381** | `eko-realestate-redis` |
| Backend (FastAPI) | **8011** | `eko-realestate-backend` |
| Frontend (Next.js) | **3004** | `eko-realestate-frontend` |

For the full port map across all four stacks, see
[`docs/architecture.md`](docs/architecture.md).

## Stack

- **Backend**: FastAPI 0.115 + SQLAlchemy 2 (async) + Alembic + Postgres 16 + Redis 7 + `anthropic` SDK
- **Frontend**: Next.js 14 (App Router) + TailwindCSS + lucide-react. **i18n** is
  a lightweight client context (`lib/i18n.tsx`, `useI18n().t(key)`) — English
  default + Spanish, switcher in the Nav. All UI strings go through `t()`; add
  new strings to BOTH the EN and ES dictionaries.
- **LLM provider (this product)**: **Kimi 2.6 `kimi-for-coding`** primary,
  **MiniMax M2.7** fallback. Both use the `anthropic-messages` HTTP protocol,
  so we use the `anthropic` Python SDK with custom `base_url`. Fallback is
  **inline per request** (not a separate cron / watchdog): if primary fails or
  times out, the same request retries against the fallback before erroring out.
- **WhatsApp**: Meta WhatsApp Business Cloud API (webhooks for inbound,
  Graph API for outbound). Signature verification with HMAC-SHA256 +
  `WHATSAPP_APP_SECRET`.
- **Calendar (Phase 3)**: Cal.com by default, Google Calendar as alternative
  (toggle via `CALENDAR_PROVIDER`).
- **Listings (Phase 7)**: RESO Web API (OData) — the USA MLS/IDX standard — via
  `app/services/listings.py`. SIMULATED Miami set in dev; real feed via
  `RESO_BASE_URL` + `RESO_ACCESS_TOKEN`. (The earlier EU plan of scraping
  Idealista/Fotocasa was dropped in the USA pivot.)
- **Container**: Docker Compose. **Ollama is intentionally NOT in the default
  stack** — it is documented as an option for Phase 5 single-customer installs
  that want full on-prem LLM, but day-to-day dev + MVP uses the hosted LLM
  providers above.

## Conventions

### Commits
Conventional commits with **scope**:

- `feat(whatsapp): …` — WhatsApp webhook / sending / signature
- `feat(llm): …` — Anything in `app/services/llm.py` / `classifier.py`
- `feat(db): …` — Models, migrations, Alembic
- `feat(api): …` — New endpoints
- `feat(frontend): …` — Next.js pages / components
- `fix(<scope>): …` — Bug fixes
- `chore: …` — Tooling, CI, docs, port remaps, identity setup
- `docs: …` — README, architecture, roadmap edits only

End each commit with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
when an AI session helped write it.

### Branches & releases
- `main` is the stable trunk. Every commit on `main` should be deployable.
- Each **Phase** lives in its own branch: `phase-1-core`, `phase-2-dashboard`,
  `phase-3-calendar`, `phase-4-scrapers-followup`, `phase-5-installer`.
- At the close of each Phase: PR to `main` → review → merge → tag `v0.X.0`
  → `gh release create vX.Y.Z --latest --generate-notes`.
- **Version bump rule**: any commit to `main` that ships customer-visible
  behavior MUST bump `frontend/lib/version.ts` and prepend a `CHANGELOG.md`
  entry, then be tagged + released. No exceptions.

### Code style
- Backend: `ruff` (configured in `backend/pyproject.toml`). Line length 100.
- Frontend: `next lint` + `tsc --noEmit` (zero errors).
- **Default to writing NO comments.** Only add a comment when the *why* is
  non-obvious. Never explain *what* code does — well-named identifiers should
  carry that.
- Tests: `pytest` + `pytest-asyncio`. No `conftest.py` central — fixtures
  inline per test file (lightweight pattern, mirrors the sales platform repo).

### Database
- **Alembic** for all schema changes (not raw SQL files). Migrations live in
  `backend/migrations/versions/`. One migration per logical change. Always
  generate with a descriptive name.
- **Models** in `backend/app/models/`. Re-export every model from
  `backend/app/models/__init__.py` so Alembic autogenerate sees them.
- **Async sessions**: use `get_db()` dep from `backend/app/db/base.py`.
  `expire_on_commit=False` is intentional — needed for FastAPI response
  serialization after commit.
- **Multi-tenancy**: every tenant-owned table carries `org_id` and is covered by
  an RLS policy. New models that belong to an agency MUST add `org_id` and get a
  policy in a migration, or they will be readable by every tenant. `properties`
  and `sync_state` are deliberately shared (one REcolorado feed as Software
  Vendor). Do not reach for `get_bypass_session_factory()` to make a query
  "work" — it removes the tenant boundary for that query. It exists only for
  login (which has to resolve *which* org the user belongs to), the background
  workers (which sweep every org via `run_for_every_org`), and the platform
  routes for demo signups.
- **Identity is global, business data is per-tenant.** `allowed_users.email` and
  `accounts.email` are globally unique — login must resolve one person before it
  knows their org. `leads.phone`, `messages.external_id`,
  `visits.external_booking_id` and `user_activity.email` are unique per org.
  Scoping an identity key by org makes every login lookup raise
  `MultipleResultsFound` and locks people out permanently.
- **A bypass session is not stamped.** `before_flush` fills `org_id` from the
  acting org; on a bypass session there is none, so every `db.add()` there must
  pass `org_id` explicitly.
- **Anything crossing the tenant boundary needs `require_platform_admin`, not
  `require_admin`** — the latter authorises the admin of *some* organization,
  and every client agency has one.

### Onboarding a second agency

Inbound messages are attributed by **destination**, via `channel_routes`
(destination → org, managed at `/api/v1/platform/routes`). Before adding a
second tenant, map its Twilio number, WhatsApp `phone_number_id` and mailbox —
an unmapped destination is refused rather than filed under the wrong agency,
and `webhook_org_or_refuse` is the single place that decides. The refusal is
acknowledged with 200 on WhatsApp, email and voice — nothing is written, but
those providers retry a failure until they disable the endpoint, which would
take the channel down for every tenant. SMS keeps its 503: Twilio does not
redeliver inbound and shows it as error 11200 where an operator looks. A
destination left unmapped therefore loses real messages quietly — alert on
`refusing inbound`.

All four channels are wired: SMS, WhatsApp, email and voice. Voice's
extractor is **not verified against a live VAPI account** (there is none), so it
yields nothing on any shape it does not recognise — which makes the caller fall
back or refuse rather than guess an organization.

Attribution takes **every** destination a message carries, not one: an email
names all its recipients, and a VAPI payload carries either the E.164 number or
the opaque phone-number id depending on the message type. Exactly one agency
addressed is the answer; two is refused. Picking by position is what filed a
lead's thread under the agency that was merely CC'd.

**Outbound identity is per organization too**, and it has to be: with one global
Twilio number, agency B's lead was answered from agency A's number, replied to
it, and the rest of the conversation was written into A. `channel_routes` holds
the *names* of the environment variables with each agency's credentials — never
the values, which stay in `.env`. NULL means the global configuration, so a
single-customer install is unaffected.

Platform access is the `su` claim, granted only to `PLATFORM_ADMIN_EMAILS`.
Naming the default org is deliberately not enough: org 1 is a real client
agency, so its admins would have inherited it.

### LLM
- All LLM calls go through `app/services/llm.py:generate_reply()`. Do not
  instantiate `anthropic.AsyncAnthropic` directly elsewhere.
- For structured outputs (intent classifier, entity extraction), use the
  `json_mode=True` flag and validate the result against a Pydantic model.
  If validation fails, log the raw response and fall back to a safe default
  (e.g., `intent=OTHER`). Never crash on bad LLM output.

### WhatsApp
- All sends go through `app/services/whatsapp.py:send_text_message()`.
- Inbound flow: webhook → `verify_signature` → orchestrator
  (`app/services/conversation.py`) → DB writes → LLM call → DB writes → send.
- **Idempotency**: every inbound message has a `wa_message_id`. We add a
  UNIQUE constraint on `messages.wa_message_id` and catch `IntegrityError`
  → return 200 OK silently. Meta retries duplicates; we must not generate
  duplicate replies.

## Operational URLs (dev / MVP)

| What | URL |
|---|---|
| **Dashboard — sign in here** | **https://inmo-demo.ekoaiautomation.com** |
| **Public capture form** (no login — this is the point) | **https://inmo-demo.ekoaiautomation.com/contact** |
| Backend OpenAPI | http://10.0.0.240:8011/docs (or http://100.88.47.99:8011/docs via Tailscale) |
| Backend health | http://10.0.0.240:8011/api/v1/health |
| Frontend, direct on the LAN | http://10.0.0.240:3004 — works, but **Google sign-in cannot** |
| Postgres | `localhost:5434` (bound only to 127.0.0.1 on the ROG; tunnel via Tailscale for remote) |
| Redis | `localhost:6381` (same) |

`inmo-demo.ekoaiautomation.com` is live: a Cloudflare tunnel on the ROG points
it at this install.

**Sign in on the domain, not on the IP.** The Google button builds its redirect
from `window.location.origin`, so on the LAN address it asks Google for
`http://10.0.0.240:3004/api/v1/auth/login/google/callback` and gets
`Error 400: redirect_uri_mismatch`. Adding that URI to the Google console is
not an option — Google rejects raw IP addresses as origins and redirect URIs on
Web clients, accepting only `localhost` and public domains. The IP is fine for
`curl`, for `/docs` and for the password login; it can never do Google, which
is the only path that issues the `su` claim.

**Getting in as the platform operator**: sign in with Google at the domain as an
address listed in `PLATFORM_ADMIN_EMAILS`. The office password deliberately
does not grant `su` (see `app/services/auth.py`), so it opens the dashboard but
not `/api/v1/platform`.

## Phase status (post-USA-pivot 2026-05-25)

- ✅ **Phase 0** — Bootstrap (`v0.0.1`, commit `66b7d7d`, 2026-05-25)
- ✅ **Phase 1** — CORE WhatsApp + LLM + Lead capture (`v0.1.0`, 2026-05-25). 25/25 tests.
- ✅ **Phase 2** — Realtor dashboard (`v0.2.0`, 2026-05-25). 33/33 tests.
- ✅ **Phase 3** — Multichannel + Email (Resend) + Bilingual (`v0.3.0`, 2026-05-25). USA pivot. 55/55 tests. WhatsApp keeps working as `channel="whatsapp"`; email is now `channel="email"`. Agent auto-detects ES/EN and replies in same language.
- ✅ **Phase 4** — Manual reply composer + AI reply suggestions (`v0.4.0`, 2026-05-25). 64/64 tests passing. `Composer` in `/leads/[id]` with "Sugerir respuestas" button (3 LLM-generated drafts the realtor can edit + send).
- ✅ **Phase 5** — Calendar booking via Cal.com (`v0.5.0`, 2026-05-25). 77/77 tests passing. `VisitsSection` + `BookingDialog` in `/leads/[id]`. SIMULATED mode default (no Cal.com account needed in dev); production wiring via `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID`. Endpoints under `/api/v1/leads/{id}/calendar/*` and `/api/v1/visits/*`.
- ✅ **Phase 6** — Single-customer installer + branding panel + public demo (`v0.6.0`, 2026-05-25). 84/84 tests passing. `GET/PUT /api/v1/settings` + `/settings` branding page; `scripts/install.sh` one-command installer; `scripts/seed_demo.py` demo dataset; `deploy/cloudflared/` + `docs/setup-demo.md` for `inmo-demo.ekoaiautomation.com`. **CI green for the first time** (Postgres service + migrations + ruff config + frontend npm-cache fix).
- ✅ **Phase 7** — MLS / IDX listings (RESO) + per-lead matching (`v0.7.0`, 2026-05-25). 96/96 tests. `Property` reworked for USA (RESO/IDX/MLS source, status, beds/baths/sqft, address/photos); Alembic `004`. `services/listings.py` (SIMULATED Miami set / real RESO Web API OData) + `match_properties_for_lead`. Endpoints `/properties*` + `/leads/{id}/matches`. Frontend `/properties` + MatchesSection. `LISTINGS_SIMULATED=true` default; prod via `docs/setup-mls.md`.
- ✅ **Phase 8** — Lead intelligence (`v0.8.0`, 2026-05-26). 107/107 tests. `leads.score` (0-100) + `score_breakdown`; Alembic `005`. `services/scoring.py` deterministic `compute_lead_score` (intent/budget/engagement/urgency/zone/recency/visit + WON/LOST/PAUSED gate), recomputed after each inbound turn. Endpoints `sort=score|recent`, `GET /leads/digest`, `POST /leads/rescore-all`. Frontend `ScoreBadge` (🔥/🟡/⚪) + `HotLeadsPanel`. `scripts/daily_digest.py`.
- ✅ **Phase 9** — SMS channel (Twilio) (`v0.9.0`, 2026-05-26). 116/116 tests. `services/sms.py` (send + HMAC-SHA1 `verify_twilio_signature` + `parse_inbound_sms`), `POST /api/v1/webhooks/sms` (empty TwiML, reply via REST), `sms` branch in the dispatcher. `SMS_SIMULATED=true` default; prod via `docs/setup-twilio.md`. Same multichannel path as WhatsApp/email.
- ✅ **Phase 10** — Autonomous nurture + in-conversation listings (`v0.11.0`, 2026-05-26). 126/126 tests. `FollowUp` model + Alembic `006`; `services/followups.py` (enqueue_for_visit + process_due_followups, skip human_takeover/cancelled/72h-if-replied); in-process worker (`FOLLOWUPS_ENABLED`) + `scripts/run_followups.py`. Orchestrator injects real matched listings into the system prompt for buy/rent leads with a zone. (Fix: matcher `Decimal(str())` to avoid float*Decimal crash.)
- ✅ **Phase 11** — Pilot hardening: dashboard auth + analytics (`v0.12.0`, 2026-05-26). 132/132 tests. `services/auth.py` (HMAC-signed cookie token) + `/login` + `AuthGuard` + `require_auth` gate on the data API, gated by `AUTH_ENABLED` (off for dev/demo, on via installer password; prod WARN if off). `/analytics` + `GET /api/v1/analytics` (funnel/conversion/channel/tier/avg-response/per-day).
- ✅ **Phase 12** — Discovery: lead search (4 sources) + import from any file (`v0.13.0`, 2026-05-26). 145/145 tests. `services/discovery.py` (SIMULATED-first like listings; ported from the sales platform — Paperclip dropped; real adapters Colorado SOS=free Socrata / Yelp Fusion / Google Maps=Outscraper / LinkedIn=SerpApi, each → [] without its key) + `services/file_import.py` (PDF pypdf / XLSX openpyxl / images OCR pytesseract+tesseract-ocr / CSV-TXT-HTML stdlib → LLM json_mode extract, graceful []). Preview-and-select → `Lead` rows deduped by phone/email (no new table). API `/api/v1/discovery/{search,upload,import}` (protected). Frontend `/discovery` (DiscoveryPanel 4 source chips + ResultsList + FileImport drag-drop). `DISCOVERY_SIMULATED=true` default; reuses sales-platform YELP/OUTSCRAPER/SERPAPI keys. See `docs/setup-discovery.md`.
- ✅ **Auth add-on** — Google Sign In (GIS) + admin-managed team access (`v0.16.0`, 2026-05-27). Session token now carries identity + role (`admin`|`member`); password login = admin (master). `/login` shows the "Sign in with Google" button (`@react-oauth/google`); backend `POST /api/v1/auth/login/google` verifies the ID token (`google-auth`) and resolves the email against the access list. Allow-list moved env → DB (`allowed_users`, Alembic `008`); admins manage it in **Settings → Team** (`/api/v1/team` CRUD under `require_admin`). `GOOGLE_ADMIN_EMAILS` pins immutable bootstrap admins; API refuses to remove the last admin. Entire Settings page is admin-only now. See `docs/setup-google-signin.md`.
- ⏳ **Phase 13** — Voice agent (VAPI / Retell) — deferred until provider account is set up

For per-phase details see [`docs/roadmap.md`](docs/roadmap.md).

## References

- **Repo**: https://github.com/enderjnets/Eko-AI-RealEstate (private)
- **Parallel-work context doc** (cross-session sync):
  `~/Downloads/EKO_PARALLEL_CONTEXT.md` (kept in sync at each Phase close)
- **Personal memory pointer**:
  `~/.claude/projects/-Users-enderj/memory/project_eko_ai_realestate.md`
- **Active plan**:
  `~/.claude/plans/puedes-verificar-a-ver-delegated-teacup.md` (Phase 1)

### Hueco conocido: no hay rate limiting (aceptado, documentado)

No existe límite de peticiones en ninguna capa. Los recursos que se pagan una
sola vez para toda la instalación — el presupuesto de LLM (Kimi/MiniMax), el
saldo de Twilio del operador cuando una agencia no trae el suyo, la licencia de
REcolorado — están ahora tras `require_platform_admin` en los sitios donde se
gastan en bloque (`/properties/sync`, todo `/discovery`). Lo que queda abierto
es el gasto por conversación: una agencia con mucho tráfico entrante consume
LLM que las demás necesitan para responder, y no hay cuota por organización
contra la que cobrarlo. Antes de cobrar por uso hay que medirlo por `org_id`.

### Precondición dura para escalar: un solo worker, una sola réplica

`tenant_resolver._cache` (TTL 15 s) y `reset_cache()` viven **en el proceso**.
Con el despliegue actual —`Dockerfile` arranca uvicorn sin `--workers`, una
sola réplica en compose— es correcto. En cuanto haya N workers o N réplicas,
crear una agencia solo invalida la caché del worker que atendió el POST: los
demás siguen viendo una sola organización hasta 15 s, y en esa ventana un
mensaje entrante sin ruta cae en la primera agencia. Eso es una escritura
cruzada entre inquilinos, y es permanente.

**Antes de añadir `--workers` o una segunda réplica**, la invalidación de esa
caché tiene que dejar de ser local al proceso (Redis pub/sub, o releer el
`updated_at` máximo de `organizations` en cada resolución).

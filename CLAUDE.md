# CLAUDE.md — Eko AI Realtors

> Project anchor for Claude (and any other AI agent) working in this repository.
> Read top-to-bottom before making changes. Anti-patterns are non-negotiable.

## What this is

**Eko AI Realtors** is the **customer-facing product** sold to real-estate
agencies (target: 2–10 person offices in Spain / EU / LATAM). It runs on the
customer's own hardware (or their own VPS) and provides:

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
7. **NEVER ship `WHATSAPP_SIMULATED=true` to a customer install.** It is a
   dev / test mode that logs instead of sending. The backend logs a warning at
   startup if it sees `WHATSAPP_SIMULATED=true` together with
   `APP_ENV=production` — investigate before any green-light.

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
- **Frontend**: Next.js 14 (App Router) + TailwindCSS + lucide-react
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
- **Scraping (Phase 4)**: Playwright (Idealista + Fotocasa have anti-bot, so
  no `requests`-based scraping).
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
| Backend OpenAPI | http://10.0.0.240:8011/docs (or http://100.88.47.99:8011/docs via Tailscale) |
| Backend health | http://10.0.0.240:8011/api/v1/health |
| Frontend (landing placeholder) | http://10.0.0.240:3004 |
| Postgres | `localhost:5434` (bound only to 127.0.0.1 on the ROG; tunnel via Tailscale for remote) |
| Redis | `localhost:6381` (same) |

`inmo-demo.ekoaiautomation.com` is reserved for Phase 5 (Cloudflare tunnel
ingress to be added when we go to first pilot).

## Phase status

- ✅ **Phase 0** — Bootstrap (`v0.0.1`, commit `66b7d7d`, 2026-05-25)
- ✅ **Phase 1** — CORE WhatsApp + LLM + Lead capture (`v0.1.0`, merge commit `95fa5ec`, 2026-05-25). PR #1 closed. GitHub Release latest. 25/25 tests passing on live ROG Postgres. Kimi 2.6 + MiniMax 2.7 A/B validated against 5 Spanish realtor prompts.
- 🔨 **Phase 2** — Realtor dashboard (Next.js list + chat view + manual takeover). To start in branch `phase-2-dashboard`.
- ⏳ **Phase 3** — Calendar booking
- ⏳ **Phase 4** — Listings scrapers + post-visit follow-up
- ⏳ **Phase 5** — Single-customer installer + public demo subdomain

For per-phase details see [`docs/roadmap.md`](docs/roadmap.md).

## References

- **Repo**: https://github.com/enderjnets/Eko-AI-RealEstate (private)
- **Parallel-work context doc** (cross-session sync):
  `~/Downloads/EKO_PARALLEL_CONTEXT.md` (kept in sync at each Phase close)
- **Personal memory pointer**:
  `~/.claude/projects/-Users-enderj/memory/project_eko_ai_realestate.md`
- **Active plan**:
  `~/.claude/plans/puedes-verificar-a-ver-delegated-teacup.md` (Phase 1)

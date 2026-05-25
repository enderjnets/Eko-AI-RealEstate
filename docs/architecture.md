# Architecture — Eko AI Inmobiliario

## High-level flow

```
   Lead's phone                          Customer's office hardware
   ───────────                           ─────────────────────────────
   ┌──────────┐         Meta WA          ┌──────────────────────────┐
   │ WhatsApp │─────► Business Cloud ────►  ngrok / cloudflare TUN  │
   └──────────┘         API               │            ▼            │
        ▲                                 │  FastAPI webhook        │
        │                                 │            ▼            │
        │           Meta WA API ◄───────  │  Conversation logic     │
        │                                 │            ▼            │
        └─────────────────────────────────│  Ollama (local LLM)     │
                                          │            ▼            │
                                          │  Postgres ◄── Lead, Msg │
                                          │            ▼            │
                                          │  Next.js dashboard      │
                                          └──────────────────────────┘
                                                Realtor (human)
```

## Trust boundary

- **Inside the box**: Lead data, conversations, property listings, valuations. Encrypted at rest in Postgres.
- **Crossing the boundary**: Only the WhatsApp messages themselves transit Meta's WA Cloud API (this is unavoidable — WhatsApp is hosted by Meta). Everything else is local.
- **Never crosses**: No cloud LLM, no analytics, no telemetry. The LLM runs in Ollama, models pulled once at install time.

## Why FastAPI + Next.js

Same patterns as our other Eko products → shared mental model, faster onboarding for any engineer who already knows our sales platform. Different DB (this product has its own `eko_realestate` schema; no schema sharing).

## Why Ollama (not vLLM or llama.cpp directly)

- Stable HTTP API, easy to swap models.
- Handles model serving + queuing on the GPU.
- One-line install on Mac (M1+) and Linux (NVIDIA).
- Already proven on the team's `100.88.47.99` ROG.

## Why Postgres (not SQLite)

- One customer install = one machine, but the realtor agency may have 2–10 employees using the dashboard concurrently.
- WhatsApp inbound rate can spike (open house weekend) — Postgres handles it cleanly.

## Why "5433 / 8001 / 3003" ports

The ROG already hosts Eko-AI-Business-Automation on 5432 / 8000 / 3001 (and the pricing-v2 preview on 3002). This product needs to coexist on the same machine during demo / development. Shifted ports avoid collisions.

## Files of interest

- `backend/app/main.py` — FastAPI app, CORS, router registration.
- `backend/app/config.py` — All env-driven settings.
- `backend/app/api/v1/health.py` — Health endpoint (Phase 0).
- `backend/app/api/v1/webhooks/whatsapp.py` — *Phase 1 target*.
- `backend/app/services/llm.py` — *Phase 1 target* — Ollama client.
- `frontend/app/page.tsx` — Public landing placeholder.
- `frontend/app/(dashboard)/...` — *Phase 2 target* — realtor dashboard.

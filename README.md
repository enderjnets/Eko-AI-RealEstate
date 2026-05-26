# Eko AI Realtors

> The AI agent for real-estate offices that answers leads 24/7 — on your own
> stack. One office = one self-hosted deployment, your data in your own database.

## What it does

A small, focused product for real-estate agencies (target: USA realtors, also
EU/LATAM):

1. **24/7 multichannel agent** — Inbound leads arrive via **WhatsApp**, **Email**,
   or **SMS** (Twilio); the AI answers, qualifies, and helps book visits. (Voice is
   on the roadmap.)
2. **Lead capture + intent classification** — Every conversation creates a
   structured lead, auto-tagged `rent | buy | valuation`, with zone, budget,
   property type, and urgency extracted.
3. **Bilingual** — Detects the lead's language and replies in kind (English /
   Spanish), configurable per deployment. The **dashboard UI is also bilingual**
   (English default + Spanish) with a language switcher on every page.
4. **Realtor dashboard** — Monitor conversations, **take over** from the AI,
   compose replies (with **AI-suggested drafts**), and manage visits.
5. **Visit booking** — Cal.com integration (slots → booking → confirmation),
   with a SIMULATED mode for dev.
6. **Listings + matching** — Ingest MLS/IDX inventory via a RESO Web API feed,
   browse it at `/properties`, and auto-match listings to each lead's intent,
   zone, and budget (SIMULATED dataset in dev).
7. **Lead intelligence** — Every lead gets a 0-100 priority score (🔥/🟡/⚪) from
   intent, budget, engagement, urgency, recency, and visits, so the realtor sees
   who to call first; plus a daily "hot leads" digest.
8. **Brandable** — Set the agency name, agent persona, greeting, languages, and
   business hours from a **Settings** page; one-command installer for a new office.

## Why a dedicated deployment

- **Data ownership** — Lead conversations, names, budgets stay in the office's
  own database. Not commingled with anyone else's.
- **One office = one stack** — Each customer gets an isolated Docker Compose
  deployment (their own Postgres / Redis / backend / frontend). No multi-tenant
  blast radius.
- **No per-seat cloud SaaS lock-in** — The office runs it on a small VPS or box.
- **LLM** — Cloud-hosted **Kimi 2.6** (primary) + **MiniMax M2.7** (fallback),
  both spoken over the `anthropic-messages` protocol with inline failover. On-prem
  LLM (Ollama) is an optional swap, not required.

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI (Python 3.11) + SQLAlchemy async + Alembic |
| Database | Postgres 16 |
| Queue / cache | Redis 7 |
| LLM | Kimi 2.6 (`kimi-for-coding`) primary + MiniMax M2.7 fallback (cloud, anthropic protocol). Ollama optional. |
| Frontend | Next.js 14 (App Router) + TailwindCSS |
| Channels | WhatsApp Business Cloud API + Email (Resend) + SMS (Twilio). Voice planned. |
| Calendar | Cal.com (Google Calendar planned) |
| Listings | RESO Web API (OData) — the USA MLS/IDX standard |
| Container | Docker Compose |

## Quick start (dev)

```bash
git clone git@github.com:enderjnets/Eko-AI-RealEstate.git
cd Eko-AI-RealEstate
cp .env.example .env
# Edit .env — at minimum set KIMI_API_KEY + MINIMAX_API_KEY
# Channels default to SIMULATED (log instead of send) — no external accounts needed
docker compose up -d
docker compose exec backend alembic upgrade head
# Frontend: http://localhost:3004   ·   Backend: http://localhost:8011/docs
# Seed the public-demo dataset so the dashboard looks alive:
docker compose exec backend python scripts/seed_demo.py
# Simulate a WhatsApp inbound message end-to-end:
docker compose exec backend python scripts/simulate_inbound.py \
    "+13055550111" "Hi, I'm looking for a 2-bed condo in Brickell under 850k"
```

## Install for a single office

```bash
./scripts/install.sh
```

The interactive installer checks prerequisites, generates a `.env` with strong
random secrets, builds + starts the stack, runs migrations, and sets the agency
branding. See [`docs/install.md`](docs/install.md) for the full guide,
[`docs/setup-whatsapp.md`](docs/setup-whatsapp.md) /
[`docs/setup-calcom.md`](docs/setup-calcom.md) to enable the real channels, and
[`docs/setup-demo.md`](docs/setup-demo.md) to expose a public demo URL.

## Project roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the phased plan.

| Phase | Status |
|---|---|
| 0. Bootstrap | ✅ done (`v0.0.1`) |
| 1. WhatsApp + LLM + lead capture + classification | ✅ done (`v0.1.0`) |
| 2. Realtor dashboard (Next.js) | ✅ done (`v0.2.0`) |
| 3. Multichannel + Email (Resend) + bilingual (USA pivot) | ✅ done (`v0.3.0`) |
| 4. Manual reply composer + AI reply suggestions | ✅ done (`v0.4.0`) |
| 5. Calendar booking (Cal.com) | ✅ done (`v0.5.0`) |
| 6. Single-customer installer + branding panel + public demo | ✅ done (`v0.6.0`) |
| 7. MLS / IDX listings (RESO) + per-lead matching | ✅ done (`v0.7.0`) |
| 8. Lead intelligence (scoring + prioritization + digest) | ✅ done (`v0.8.0`) |
| 9. SMS channel (Twilio) | ✅ done (`v0.9.0`) |
| 10. Voice agent (VAPI / Retell) — deferred until provider account ready | ⏳ |

## Relationship to other Eko AI projects

This repo is the **customer-facing product** for the real-estate vertical, sold
under the Eko AI brand. It is intentionally **separate** from
[`Eko-AI-Business-Automation`](https://github.com/enderjnets/Eko-AI-Business-Automation)
(the Eko AI sales platform that **we** use to sell this product). Different
deployments, different stacks, different data lifecycles.

## License

Proprietary. © 2026 Eko AI Automation. All rights reserved.

# Eko AI Inmobiliario

> The AI agent for real-estate offices that works 24/7 on your own hardware.
> **Zero cloud data leakage** — runs 100% on-prem with a local LLM.

## What it does

A small, focused product for real-estate agencies:

1. **WhatsApp Business 24/7** — Inbound leads arrive via WhatsApp; a local AI agent answers, qualifies, and schedules visits.
2. **Lead capture + intent classification** — Every conversation creates a structured lead. The agent auto-tags the intent: `rent | buy | valuation`.
3. **Visit booking** — When the lead asks to see a property, the agent offers calendar slots (Cal.com or Google Calendar) and books one in.
4. **Listings ingest** — Optional scrapers pull new listings from Idealista / Fotocasa into the local database.
5. **Post-visit follow-up** — Automated 24h / 72h / 7d sequence keeps leads warm without manual work.
6. **Realtor dashboard** — A simple web UI where the human agent monitors conversations, takes over, edits, and manages visits.

## Why on-prem

- **GDPR / data sovereignty** — Client conversations, names, addresses, valuations stay on your hardware. Nothing transits a third-party cloud.
- **Lower cost at scale** — No per-token billing. The customer owns the hardware (~€1,500 PC with RTX 3060+ or Mac M1 16 GB+) and the model.
- **Offline resilience** — Works without internet (except for WhatsApp inbound/outbound webhooks, which can be queued).
- **Differentiation** — "El único agente inmobiliario que trabaja 100% offline en tu propia oficina."

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI (Python 3.11) + SQLAlchemy async + Alembic |
| Database | Postgres 16 |
| Queue / cache | Redis 7 |
| LLM | Ollama running `qwen2.5:14b` (≈ 9 GB, fast on RTX 3060 / M1) |
| Frontend | Next.js 14 (App Router) + TailwindCSS |
| WhatsApp | Meta WhatsApp Business Cloud API (webhooks) |
| Calendar | Cal.com (default) or Google Calendar |
| Scraping | Playwright (Idealista / Fotocasa) |
| Container | Docker Compose |

## Quick start (dev)

```bash
git clone git@github.com:enderjnets/Eko-AI-RealEstate.git
cd Eko-AI-RealEstate
cp .env.example .env
# Edit .env — at minimum set WHATSAPP_* and CALCOM_API_KEY
docker compose up -d
# Pull the LLM (first time, ~9 GB)
docker compose exec ollama ollama pull qwen2.5:14b
# Frontend: http://localhost:3001
# Backend:  http://localhost:8000/docs (OpenAPI)
```

## Production install (single customer)

See [`docs/deployment.md`](docs/deployment.md) — short version: one customer = one workstation running the full Docker Compose stack. Each customer is fully isolated.

## Project roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the phased plan.

| Phase | Status |
|---|---|
| 0. Bootstrap (this commit) | ✅ done |
| 1. WhatsApp + LLM + lead capture + classification | 🔄 next |
| 2. Realtor dashboard (Next.js) | ⏳ |
| 3. Calendar booking | ⏳ |
| 4. Listings scraper + post-visit follow-up | ⏳ |

## Relationship to other Eko AI projects

This repo is the **customer-facing product** for the real-estate vertical, sold under the Eko AI brand. It is intentionally **separate** from [`Eko-AI-Business-Automation`](https://github.com/enderjnets/Eko-AI-Business-Automation) (the Eko AI sales platform that **we** use to sell this product). Different deployments, different stacks (no Ollama in the sales platform, no Buffer/Resend here), different data lifecycles.

## License

Proprietary. © 2026 Eko AI Automation. All rights reserved.

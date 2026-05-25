# CHANGELOG

All notable changes to Eko AI Inmobiliario.

## [0.0.1] — 2026-05-25

### Bootstrap

- Repo initialized with project skeleton (FastAPI + Next.js + Postgres + Redis + Ollama)
- `docker-compose.yml` brings up the full stack locally
- Health endpoint at `GET /api/v1/health`
- Placeholder landing page on the frontend
- README + architecture + roadmap docs
- `.env.example` with the env vars required for Phase 1 (WhatsApp + LLM + DB)

### Out of scope this commit (planned for Phase 1)

- WhatsApp webhook receiver
- Ollama client with conversation streaming
- Lead / Conversation / Message models + migration
- Intent classifier (rent / buy / valuation)

export const CURRENT_VERSION = "0.2.0";

export interface VersionEntry {
  version: string;
  date: string;
  title: string;
  changes: string[];
}

export const CHANGELOG: VersionEntry[] = [
  {
    version: "0.2.0",
    date: "2026-05-25",
    title: "Phase 2 — Realtor dashboard (lista leads + chat view + human takeover)",
    changes: [
      "Dashboard frontend funcional en Next.js 14 App Router. Reemplaza el landing placeholder en `/` (que ahora redirige a `/leads`). La landing vieja queda accesible en `/about`.",
      "`/leads` — tabla de leads con filtros por status (Nuevo/Cualificado/Visitando/Post-visita/Cerrado/Perdido/Pausado) e intent (Alquiler/Compra/Tasación/Otro). Click en un lead → vista detalle.",
      "`/leads/[id]` — vista detalle con metadata del lead (nombre, teléfono, zona, presupuesto, tipo, urgencia, timestamps) + conversación completa estilo chat (burbujas inbound/outbound, indicador de provider LLM, status de envío Meta) + toggle de control humano.",
      "Toggle 'Humano vs IA' — botón que llama `PATCH /api/v1/leads/{id}` con `{human_takeover: true|false}`. Cuando está ON, el orchestrator NO genera respuesta automática para el siguiente mensaje entrante (Phase 1 ya respeta esta flag).",
      "Componentes: `Nav` (top bar con branding + links), `StatusBadge` + `IntentBadge` (paleta por categoría), `FilterBar` (querystring-based, Suspense para SSR), `LeadsTable` (lista con virtualización ligera), `MessageBubble` (chat-style con sender icons), `LeadDetail`, `TakeoverToggle`.",
      "API client tipado en `lib/api.ts` — interfaces TypeScript para Lead, Conversation, Message + funciones `leadsApi.list/get/patch` y `conversationsApi.get`. Helper `format.ts` con tiempos relativos en castellano + formato de presupuesto.",
      "Backend: nuevo endpoint `PATCH /api/v1/leads/{id}` con schema `LeadPatch` (partial update, `extra='forbid'` rechaza campos desconocidos con 422). Acepta name, status, intent, zone, budget_min/max, property_type, urgency, human_takeover.",
      "`next.config.js` proxya `/api/*` a `INTERNAL_API_URL` (default `http://backend:8000`) — cliente JS siempre habla same-origin, funciona desde LAN/Tailscale/futuro Cloudflare sin reconfigurar URLs.",
      "Tests +8: `test_leads_api.py` cubre list envelope, get 404, PATCH takeover toggle, PATCH partial update (status+zone sin tocar name), PATCH body vacío 400, PATCH campo desconocido 422, PATCH status inválido 422, PATCH 404. Total ahora: 33 tests.",
      "Brand rename completo Inmobiliario → Realtors en `<title>`, landing copy, README.",
    ],
  },
  {
    version: "0.1.0",
    date: "2026-05-25",
    title: "Phase 1 CORE — WhatsApp 24/7 agent with Kimi + MiniMax fallback",
    changes: [
      "Identity setup: CLAUDE.md raíz con anti-patterns + port map + 3-líneas-de-trabajo distinction; GitHub topics + 5 milestones; CI workflow (ruff + pytest + tsc + lint).",
      "Port remap: container stack `eko-realestate-*` en 3004/8011/5434/6381 para coexistir con la sales platform prod (3001/8000/5432/6379), su main dev paralela (3003/8010/5433/6380) y el preview pricing-v2 (3002). Cero colisión.",
      "DB layer: SQLAlchemy 2.x async + Alembic baseline migration. 5 modelos: Lead (con status/intent enums, budget, zone, urgency, human_takeover), Conversation, Message (UNIQUE wa_message_id para idempotencia de webhooks), Property (placeholder Phase 4), AgentSettings (singleton con persona en castellano + business_hours).",
      "LLM client: Kimi 2.6 primary + MiniMax M2.7 fallback. Fallback INLINE por request (si Kimi timeout/429/5xx, mismo request reintenta con MiniMax antes de fallar). Ambos via SDK `anthropic` con `base_url` distinto. A/B test script con 5 prompts ES típicos validó calidad real (Kimi ~3.4s avg, MiniMax ~5.6s; ambos producen castellano natural).",
      "Intent classifier: clasifica rent/buy/valuation/other + extrae zona, presupuesto, tipo, urgencia. Pydantic schema valida; degrada a OTHER + log raw_response cuando JSON inválido. Coerce \"1.500€\" → 1500.0.",
      "WhatsApp webhook: GET handshake verify (token + challenge), POST inbound con HMAC-SHA256 verify (`X-Hub-Signature-256`). Modo SIMULATED por default (loguea outbound en vez de POST a Meta) — desarrollo sin Meta Business App. Warning al startup si SIMULATED=true Y APP_ENV=production.",
      "Conversation orchestrator: inbound → upsert Lead → save inbound Message → classify intent (aplica si confidence ≥ 0.55) → genera reply con LLM → save outbound Message (status=PENDING) → send via WhatsApp Cloud API → update wa_message_id + status (SENT/FAILED). Idempotencia via UNIQUE wa_message_id (Meta retries no duplican leads).",
      "API routes: `GET /api/v1/leads` (lista paginada con filtros status/intent), `GET /api/v1/leads/{id}` (detail), `GET /api/v1/conversations/{lead_id}` (full history).",
      "Tests: 23 total — 4 LLM fallback (mocked anthropic SDK), 7 classifier (mocked LLM responses), 7 signature (HMAC valid/invalid/missing/tampered/wrong-secret), 2 webhook E2E (full flow + idempotency), 2 models (roundtrip + AgentSettings), 1 health. Live DB required for E2E + models.",
      "Script `simulate_inbound.py` para CLI testing manual: `python scripts/simulate_inbound.py \"+34666123456\" \"Hola...\"` → POST simulado al webhook.",
      "Doc `setup-whatsapp.md` con flow completo Meta App → secrets → webhook registration → production checklist + troubleshooting.",
    ],
  },
  {
    version: "0.0.1",
    date: "2026-05-25",
    title: "Bootstrap",
    changes: [
      "Repo skeleton: FastAPI backend + Next.js frontend + Postgres + Redis + Ollama via docker-compose.",
      "Health endpoint at GET /api/v1/health.",
      "Landing placeholder with brand-aligned design (Eko AI violet palette).",
      "README + roadmap + architecture docs.",
    ],
  },
];

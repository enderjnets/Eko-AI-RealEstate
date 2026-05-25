export const CURRENT_VERSION = "0.4.0";

export interface VersionEntry {
  version: string;
  date: string;
  title: string;
  changes: string[];
}

export const CHANGELOG: VersionEntry[] = [
  {
    version: "0.4.0",
    date: "2026-05-25",
    title: "Phase 4 — Composer manual + AI reply suggestions (completa el loop de takeover)",
    changes: [
      "Composer box en /leads/[id]: el realtor escribe una respuesta y la envía vía el canal del lead (WhatsApp/Email). Se persiste como Message(sender=HUMAN, direction=OUTBOUND) y se rutea por el dispatcher multichannel existente.",
      "Botón 'Sugerir respuestas': genera 3 borradores de respuesta vía LLM (Kimi/MiniMax). Cada sugerencia es clickeable y llena el textarea del composer — el realtor puede editarla antes de enviar.",
      "Backend nuevo: POST /api/v1/leads/{id}/messages (human send con auto-pick del canal de la última conversación activa; threading email via In-Reply-To del último inbound) + POST /api/v1/leads/{id}/suggestions (genera N respuestas en formato JSON array, degrada a [] + error en caso de LLM fail o JSON inválido).",
      "Orchestrator: 2 funciones nuevas — send_human_message + generate_reply_suggestions. Usan el dispatcher existente, la detección de idioma del Phase 3, y AgentSettings.languages.",
      "Auto-pick canal: si el lead tiene múltiples conversaciones activas (multichannel), el composer usa la última activa. Para email auto-prepende 'Re:' + In-Reply-To header.",
      "UX: 'count' clampado a [1, 5]. Composer muestra contador 0/4000 chars. Errores in-line (no toast/modal). router.refresh() tras send → nueva burbuja aparece en el chat sin recargar.",
      "Tests +8: human-send happy path (WhatsApp simulated routing), lead-not-found error, empty text 400, lead-without-conversation error, suggestions happy path, suggestions con prose alrededor del JSON, suggestions LLM fail degrade graceful, suggestions count clamp 99→5.",
    ],
  },
  {
    version: "0.3.0",
    date: "2026-05-25",
    title: "Phase 3 — Multichannel + Email (Resend) + Bilingual (USA pivot)",
    changes: [
      "Pivote estratégico USA: el target de clientes pasa de inmobiliarias EU (WhatsApp-first) a realtors USA donde dominan SMS, Email y llamadas. WhatsApp queda como canal opcional para clientes internacionales.",
      "Multichannel refactor: schema agnóstico al canal. Renames messages.wa_message_id→external_id, wa_status→delivery_status, conversations.wa_thread_id→external_thread_id. + messages.subject (email). leads.phone widened 32→254 chars (acepta emails como identifier). Alembic migration 002_phase3_multichannel preserva rows existentes.",
      "ParsedMessage común en services/_common.py — dataclass con channel, external_id, from_identifier, content, subject, thread_id. Cada canal (WhatsApp / Email / SMS / Voice) emite el mismo tipo.",
      "Orchestrator con dispatcher: handle_inbound_message ahora rutea outbound a whatsapp_send / email_send según conversation.channel. Lazy imports — un deploy puede no tener Resend SDK si no usa email.",
      "Email channel (Resend): services/email.py con send_email (threading via In-Reply-To + References), parse_inbound_email (Resend payload + HTML fallback), verify_resend_signature (Svix-style HMAC con multi-sig support). EMAIL_SIMULATED=true en dev (loguea outbound, no requiere cuenta Resend ni DNS).",
      "Webhook nuevo: POST /api/v1/webhooks/email — mismo contrato que WhatsApp (200 + UNIQUE external_id catches retries).",
      "Bilingüe: services/i18n.py con detect_language (langdetect, seed determinista) + pick_supported_language (whitelist AgentSettings.languages) + language_instruction (steering line ES/EN para el system prompt). Detecta del último inbound, NO bias en réplicas históricas del agente. Classifier acepta language_hint opcional.",
      "Dashboard: MessageBubble muestra channel icon (envelope email, message-circle WhatsApp, message-square SMS, phone voice) + asunto del email visible cuando applies. LeadsTable muestra heuristic-based glyph al lado del identificador (email vs phone).",
      "Backend: PATCH lead endpoint Phase 2 sigue funcionando. Pydantic schemas en conversations.py actualizados al naming nuevo (external_id / delivery_status / subject / external_thread_id).",
      "Tests: 55 total (45 + 10 nuevos = 8 email service + 9 i18n - 7 duplicados/colectados). E2E email crea Lead via address, Conversation(channel=email), 2 Messages con subject + threading.",
      "Frontend lib/api.ts: Message + Conversation interfaces alineadas al backend nuevo (external_id, delivery_status, subject, external_thread_id).",
      "Roadmap reordenado post-pivote USA: Phase 4=SMS (Twilio), Phase 5=Voice (VAPI/Retell), Phase 6=Calendar (movido desde Phase 3), Phase 7=MLS/IDX (USA equivalente Idealista), Phase 8=installer + demo subdomain.",
    ],
  },
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

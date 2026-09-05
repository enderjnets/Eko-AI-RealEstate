# PLAN — `/analytics` mide el embudo entero de Denver Home Story

> Escrito el 4-sep-2026 (madrugada, hora Denver) tras recorrer el código real, ejecutar
> la suite y medir producción. **Ejecutor: Opus 5**, fase por fase, máx. 3 intentos de
> corrección por fase, un commit convencional por fase, push, **sin merge ni PR sin
> pedirlo, sin desplegar sin autorización en un mensaje aparte**. Al aprobarse este
> plan, el primer paso de la ejecución es copiarlo tal cual a `PLAN.md` en la raíz del
> repo (el modo plan solo permitía escribir este fichero).

---

## 0. Estado de ejecución (al 4-sep-2026)

| Fase | Estado |
|---|---|
| F1 — eventos de la landing: esquema + endpoint [CRÍTICA] | ✅ hecha, `b53b539` |
| F2 — el tracker en la landing | ✅ hecha, `0fe036c` |
| **Checkpoint A** | ✅ **desplegado como 0.73.0**, `bf0476c`, migración `051` aplicada |
| F3 — historial del lead y llamadas de voz [CRÍTICA] | siguiente |
| F4 … F9 | sin empezar |

**Verificado en producción**, no en local: baliza válida `204` con fila escrita;
tipo desconocido, sesión mal formada y JSON roto → `400` sin escribir; el
presupuesto del formulario de captura intacto; **`country=US` llegó**, lo que
resuelve la incógnita §6.6 — las cabeceras de Cloudflare atraviesan el túnel y
el rewrite de Next. `region` y `city` siguen vacías: falta el clic de §7.4.

Las desviaciones respecto a lo escrito aquí están anotadas **en su fase**, no en
esta tabla, para que quien lea F1 vea por qué el código no dice lo que decía el
plan. Son cuatro: el tope diario de sesiones, el cuerpo de 16 KB, el `400` en
vez de `422`, y el `session_id` sin `pattern`.

---

## 1. Objetivo y alcance

**Objetivo.** Que `/analytics` responda, con números medidos y no inferidos, a la
cadena completa: *qué red y qué vídeo trajeron la visita → desde dónde y con qué
dispositivo → hasta qué sección de la landing llegó → si pulsó llamar o rellenó el
formulario → si se le respondió y cuánto tardó (IA / humano) → si se le devolvió la
llamada → si hubo cita (telefónica o visita) y si se realizó → si se cerró negocio y
de qué tipo*. Hoy la página muestra 5 cifras globales sin filtro de fechas
(`frontend/components/analytics/AnalyticsView.tsx`, 186 líneas; `backend/app/api/v1/analytics.py`,
108 líneas) y **ninguna** de esas preguntas se puede contestar.

**Qué se construye.** Cinco colectores que hoy no existen y una analítica que los lee:

1. Eventos de la landing (sesión anónima, sin cookies): vista, secciones, scroll, clics
   en «llamar» y «consulta», inicio y envío del formulario, red de origen, dispositivo,
   país/región/ciudad.
2. Historial del lead (`lead_events`): cada cambio de estado, cada llamada entrante con
   duración y motivo de fin, cada llamada registrada, cada cita puesta/cancelada/realizada,
   cada cierre.
3. Resultado de la cita (realizada / no vino) y registro del negocio cerrado (tipo, fecha,
   importe opcional).
4. UTM por plataforma en la llamada a la acción de cada post y en los enlaces de bio.
5. Métricas por vídeo: YouTube por API (público, gratis); TikTok e Instagram a mano
   (su API no las expone — medido, ver §6).
6. `GET /api/v1/analytics` v2 con rango de fechas en la zona horaria de la agencia, y la
   página `/analytics` reescrita, usable en el móvil.

**Fuera de alcance, dicho en voz alta.**
- Atribución **cierta** por vídeo. Los enlaces en descripciones de Shorts no son
  pulsables, TikTok e Instagram tampoco los hacen pulsables en el pie del vídeo, e
  Instagram borra el referrer. Lo que se puede saber por red es vía enlaces de bio con
  UTM; por vídeo, solo una **asociación temporal** (visitas y leads en las 48 h
  siguientes a cada publicación) etiquetada como tal. Fuentes en §6.
- Vistas de TikTok/Instagram por API (Buffer no las expone; las APIs nativas exigen
  apps propias con revisión de Meta/TikTok).
- Herramienta externa de analítica (GA4/Plausible/PostHog): no enlaza visita → lead →
  negocio, que es el punto; GA4 exige banner y lo bloquean los navegadores embebidos.
- Reparto de comisión o cualquier cálculo de nuestra factura sobre los cierres
  (prohibido en Colorado repartir comisión con quien no tiene licencia; el registro de
  cierres es **dato del CRM de la agencia**, no insumo de facturación).
- Página de política de privacidad (no existe; queda en decisiones §7).
- Exportar CSV, alertas por métricas, comparativas entre periodos más allá de la
  tendencia semanal.

---

## 2. Diagnóstico

### 2.1 Estado base (ejecutado el 4-sep-2026, rama `feat/landing-marca`, HEAD `4997cd3`, árbol limpio)

| Comprobación | Resultado real |
|---|---|
| Backend `pytest` desde base recreada (`eko_realestate_test`, migración a `050_publication_schedule`) | **1374 passed, 0 skipped**, 38 warnings, 4 min 49 s |
| Cobertura backend (`pytest-cov 7.1.0`, ya en el venv) | **80,8 %** total (9.683 sentencias). Ficheros que este plan toca: `analytics.py` 62 % (ver nota), `public.py` 90 %, `capture.py` 94 %, `voice.py` 86 %, `webhooks/voice.py` 72 %, `conversation.py` 84 %, `calls.py` 96 %, `visits.py` 75 %, `leads.py` 79 %, `buffer_publisher.py` 87 % |
| `ruff check app tests` | All checks passed |
| `npx tsc --noEmit` | sin errores |
| `npx vitest run` | **13 ficheros, 200 tests, 0 fallos** (975 ms) |
| `next build` con las `NEXT_PUBLIC_*` reales (`scratchpad/build_front.sh`) | **BUILD OK**, exit 0 |
| Producción (`/api/v1/health` por el dominio) | `0.71.1`; VPS HEAD `02f0ac8` |

Nota sobre el 62 % de `analytics.py`: las líneas «sin cubrir» son sentencias sueltas
intercaladas con otras cubiertas dentro de un handler que el test sí ejecuta
(afirma 200 y el cuerpo). Es el contador infra-midiendo un handler `async`, **no** un
hallazgo. El hallazgo real está en H7.

### 2.2 Lo que hay en producción (SELECTs de solo lectura, 4-sep)

| Dato | Medida | Consecuencia |
|---|---|---|
| Leads | 42 (37 `new`, 3 `qualified`, 1 `visiting`, 1 `post_visit`; **0 `won`, 0 `lost`**) | el embudo de hoy termina en «qualified» porque nadie escribe `won` |
| Leads con `meta.attribution` | **0 de 42**. Claves presentes en `meta`: `source`(31), `enrichment`, `discovery`… | la atribución UTM se captura desde v0.60 y **nunca se ha ejercido**; el 74 % de los leads son de Discovery/LinkedIn, no de la web |
| Conversaciones por canal | voice 5 · whatsapp 4 · email 3 · sms 1 · **web 0** | ningún lead ha entrado aún por el formulario de la landing |
| Mensajes salientes | email: 10 `ollama`, 2 `kimi`, 1 humano, 2 sin proveedor · voz: 55 agente + 2 `internal` | «si se les respondió» hoy mezcla IA, humano, respaldo enlatado y notas internas |
| `call_logs` | 1 (`no_answer`) | la consola de llamadas se ha usado una vez |
| Visitas | 3 `scheduled`, 1 `completed`, 1 `cancelled` (todas `showing`) | el `completed` se escribió a mano por SQL: **ningún código escribe `completed`/`no_show`** |
| Publicaciones | 15 `published` (5 por red), 3 `scheduled`; **`external_url` = 0 en todas** | las métricas por vídeo solo podrán empezar con las publicaciones nuevas |
| Organizaciones | 1 «Robbie & Natalia» `active`; 2 «Demo» `trial` | `routable_candidates` excluye la demo (`tenant_resolver.py:191-202`), así que el formulario sin `form key` resuelve a la org 1 — hasta que exista una segunda agencia real |
| `channel_routes` | **vacía**; `NEXT_PUBLIC_CAPTURE_FORM_KEY` **no está** en el `.env` del VPS | el tracker heredará exactamente el mismo mecanismo de resolución que el formulario |
| `user_activity.last_ip` más reciente | IPv6 pública (Comcast), 4-sep | `CF-Connecting-IP` **atraviesa** Cloudflare → cloudflared → rewrite de Next → backend; las cabeceras `cf-ip*` de geolocalización llegarán por el mismo camino |

### 2.3 Hallazgos, con evidencia y clasificación

**Bloqueantes para el objetivo** (sin ellos la página no puede decir lo que se pide):

| # | Hallazgo | Evidencia |
|---|---|---|
| H1 | **La atribución se captura y nunca se agrega.** `analytics.py` no lee `Lead.meta`; no hay `GROUP BY` por `utm_source` en ningún sitio | `backend/app/api/v1/analytics.py:34-98` (7 consultas, ninguna sobre `meta`); `services/capture.py:424-446` la guarda; `api/v1/leads.py:194-215` la expone solo lead a lead |
| H2 | **La landing no registra ningún evento**: ni vista, ni scroll, ni clic en `tel:`, ni inicio de formulario. El único hecho registrado es el POST del lead | grep `sendBeacon|gtag|plausible|posthog|track(` en `frontend/` → 0; `ConsultForm.tsx:46-52` solo lee UTMs de la URL |
| H3 | **No existe historial de estados.** `LeadStatus` cambia por `PATCH` a mano (`leads.py:514-552`) o desde la consola de llamadas (`services/calls.py:246-262`); nada guarda cuándo. `POST_VISIT` y `WON` **no los escribe ningún código** | grep `history|timeline|audit|status_changed` en `backend/app/models/` → solo prosa; lista completa de tablas en §2.2 |
| H4 | **Las llamadas de voz entran sin duración, sin motivo de fin, sin grabación**; el `analysis.summary` de VAPI se parsea y se tira | `services/voice.py:96-154` (`parse_end_of_call_report` extrae id, número, turnos, summary, structured); `services/conversation.py:564-663` (`ingest_voice_call` no escribe `conv.summary`) |
| H5 | **`VisitStatus.COMPLETED` / `NO_SHOW` / `CONFIRMED` no los escribe nadie**; el único cambio de estado de una visita es `CANCELLED` en `visits.py:622`. «Cita realizada» es inmedible | grep `VisitStatus\.` en `api/` y `services/` → solo lecturas salvo `:622` |
| H6 | **El CTA de los vídeos no lleva UTM**: `CONTENT_CTA_URL` se pega literal en el pie del post, igual para las tres redes | `services/content_writer.py:233-256` (`_with_cta`); `buffer_publisher.py:186-231` (`build_post_input` recibe `text` ya cerrado) |

**Importantes** (entran en fases, no las bloquean):

| # | Hallazgo | Evidencia |
|---|---|---|
| H7 | El único test de analítica **afirma forma, no valores**, y no hay test de aislamiento entre agencias para `/analytics` | `backend/tests/test_analytics.py:19-33`; `grep analytics backend/tests/` → solo ese fichero |
| H8 | `avg_first_response_seconds` cuenta **cualquier** mensaje saliente: notas `internal=True`, respaldo `provider="fallback"` y humanos por igual. El propio código dice que la analítica es la consumidora de ese discriminador y nunca lo lee | `analytics.py:73-97`; `services/llm.py:31-33`; `models/message.py:95-96,137` |
| H9 | Los días se agrupan en **UTC** (`func.date(Lead.created_at)`); la agencia vive en `America/Denver` (6-7 h de desfase en el borde del día) | `analytics.py:61-69`; `models/agent_settings.py:90-94` (`timezone`) |
| H10 | La atribución se **pierde al navegar** dentro del sitio: se lee de la URL al montar y no se persiste (`sessionStorage`) | `ConsultForm.tsx:46-52`; `lib/capture.ts:37-53` |
| H11 | «Conversión» = `won/(won+lost)` y la etiqueta dice «won/closed»; `console.py:40` trata `PAUSED` como cerrado y `analytics.py:44` no. Dos definiciones del mismo número | `analytics.py:43-44`; `frontend/lib/i18n.tsx:189,939`; `api/v1/console.py:40` |
| H12 | El limitador del router público es **compartido y estrecho** (5/IP/10 min, 60 globales/10 min); reutilizarlo para eventos agotaría el presupuesto del formulario | `api/v1/public.py:55-64,72,94` |
| H13 | Analytics es inalcanzable en la barra de escritorio por debajo de `2xl` (1536 px): vive en «Más» | `components/ui/Nav.tsx:144,334-338,378` |

**Menores** (backlog §5): etiquetas de canal sin traducir (`AnalyticsView.tsx:138`);
gráfica de 14 columnas con etiquetas de 9 px en 390 px; umbrales de score 67/34
duplicados en la consulta (`analytics.py:53-57`).

---

## 3. Comandos del proyecto (verificados hoy; son la definición de «terminado»)

```bash
# Backend — suite desde base recreada (NO es idempotente), con cobertura
docker exec eko-realestate-db psql -U eko -d postgres \
  -c "DROP DATABASE IF EXISTS eko_realestate_test WITH (FORCE)" \
  -c "CREATE DATABASE eko_realestate_test OWNER eko"
cd ~/Eko-AI-RealEstate/backend
PW=$(docker exec eko-realestate-db printenv POSTGRES_PASSWORD)
export DATABASE_URL="postgresql+asyncpg://eko:${PW}@localhost:5434/eko_realestate_test"
export DATABASE_URL_APP="postgresql+asyncpg://eko_app:eko_app_local_pass@localhost:5434/eko_realestate_test"
export WHATSAPP_ENABLED=true
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m pytest -q -p no:cacheprovider --cov=app --cov-report=term
./.venv/bin/python -m ruff check app tests --output-format=concise

# Frontend
cd ~/Eko-AI-RealEstate/frontend
npx tsc --noEmit
npx vitest run
zsh /private/tmp/claude-501/-Users-enderj/daf68445-32db-4d26-982f-bf7064311b03/scratchpad/build_front.sh   # next build con las NEXT_PUBLIC_* reales

# Imagen
cd ~/Eko-AI-RealEstate && docker build -f backend/Dockerfile backend
```

Referencia de verdes: **1374 backend / 200 frontend**, cobertura **80,8 %**. Cada fase
termina con esos cuatro bloques en verde, **sin saltados**, cobertura del código nuevo
≥ la del fichero que toca, y la(s) mutación(es) de la fase verificada(s): guardar copia,
mutar, ver el rojo, restaurar, `md5` idéntico.

**Guardianes que muerden** (leerlos antes de escribir, no después): `test_config_example.py`
+ `test_compose_env.py` = **3 ediciones por setting nuevo** (`config.py`, `.env.example`,
bloque `backend:` de `docker-compose.yml`, valores idénticos); `test_migration_ids.py`
(id ≤ 30 chars); `test_text_limits.py` (toda `String(N)` nueva exige entrada en `HANDLED`
→ **usar `Text`**); `test_content_gate_is_absolute.py` (barrido AST de `.post/.put/.request/
.upload/...` en cuerpos; **`.get` no está** en la lista); `test_opt_out_is_absolute.py`
(igualdad del conjunto de módulos con `.post`: un módulo nuevo con `.post()` sin exención
rompe dos aserciones); `test_advance_is_the_only_thing_that_writes_a_status` (barre ficheros
cuyo nombre contenga `content`); `landingConfigWiring.test.ts` (4 sitios por `NEXT_PUBLIC_*`,
**sin dígitos en el nombre**); `i18nParity.test.ts` (claves con **2 espacios** de sangría,
EN y ES idénticos, sin valores vacíos); `capture.test.ts` (lee `ATTRIBUTION_KEYS` del
fuente del backend → **no añadir claves de atribución**); `test_version_is_one_number.py`
(`APP_VERSION` = `CURRENT_VERSION` = cabecera de `CHANGELOG.md`).

Deploy (cuando se autorice, por checkpoint): `git bundle` → `scp ender-vps:/tmp/eko.bundle`
→ `git fetch && git merge --ff-only` → `docker compose build backend frontend` → **migrar
con la imagen nueva** (`docker compose run --rm -T backend alembic upgrade head`) →
`up -d backend frontend` → `curl https://inmo-demo.ekoaiautomation.com/api/v1/health`
→ versión. Backup del `.env` antes (`.env.bak.YYYYMMDD_vNNNN`). Reversión: `git reset --hard
<HEAD anterior>` + rebuild; **`alembic downgrade` borra los datos recogidos** — no es una
reversión gratuita, se dice en cada checkpoint.

---

## 4. Fases

Rama **`feat/analitica-embudo` desde `4997cd3`** (apilada sobre `feat/landing-marca`,
que es lo que corre en producción). Un commit por fase. Cinco checkpoints de deploy,
cada uno con su bump; la autorización de cada uno la da el dueño en un mensaje aparte.

| Checkpoint | Fases | Versión | Qué empieza a acumularse |
|---|---|---|---|
| A | F1 + F2 | ~~0.72.0~~ → **0.73.0** ✅ **desplegado 4-sep** | sesiones y eventos de la landing |
| B | F3 | ~~0.73.0~~ → **0.74.0** | historial del lead, llamadas con duración |
| C | F4 + F5 | ~~0.74.0~~ → **0.75.0** | citas realizadas, cierres, UTM por red |
| D | F6 | ~~0.75.0~~ → **0.76.0** | vistas de YouTube por vídeo |
| E | F7 + F8 | ~~0.76.0~~ → **0.77.0** | la página que lo enseña |

> **Renumerado el 4-sep.** Mientras esta rama se escribía, producción publicó
> su propia **0.72.0** (la puerta de la marca de agua leía el brillo de la foto,
> otra sesión). El plan reservaba ese número para el checkpoint A, así que toda
> la columna corre un escalón. No es un cambio de alcance: es que una rama
> paralela llegó antes al numerador.

El orden es el de la urgencia del dueño («pronto empezaremos a recibir visitas»): primero
los colectores, la página al final, cuando haya algo que pintar.

---

### F1 [CRÍTICA] — Eventos de la landing: esquema + endpoint público

**Objetivo verificable:** un `POST /api/v1/public/landing` anónimo deja una fila en
`landing_sessions` y N en `landing_events` de la org correcta, sin consumir el presupuesto
del formulario, sin guardar IP ni user-agent en crudo, y bajo RLS.

**Por qué es crítica:** es un endpoint público **sin captcha** que escribe en la base
(el único así en el producto), y un error de aislamiento o de límite se paga con la
disponibilidad del formulario de captura, que es el eslabón que produce leads.

**Archivos y cambios:**

- `backend/migrations/versions/20260904_1000_landing_sessions.py` — `revision =
  "051_landing_sessions"`, `down_revision = "050_publication_schedule"`. Calcar
  `20260830_1200_render_jobs.py` (RLS `ENABLE` + `FORCE`, política `USING/WITH CHECK
  (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)`, `GRANT
  SELECT, INSERT, UPDATE, DELETE` y `GRANT USAGE, SELECT ON SEQUENCE` a `APP_ROLE`).
  - `landing_sessions`: `id BigInteger PK`, `org_id BigInteger FK organizations CASCADE
    NOT NULL idx`, `session_key Text NOT NULL`, `UNIQUE (org_id, session_key)`,
    `first_seen_at`/`last_seen_at timestamptz NOT NULL`, `landing_path Text`, `lang Text`,
    `utm_source/utm_medium/utm_campaign/utm_content/utm_term Text NULL`,
    `referrer_host Text NULL`, `source Text NOT NULL` (derivado), `device Text`
    (`phone|tablet|desktop|unknown`), `browser Text`, `os Text`, `in_app Text NULL`
    (`instagram|tiktok|facebook|null`), `country Text NULL`, `region Text NULL`,
    `city Text NULL`, `screen_w Integer NULL`, `max_scroll_pct SmallInteger NOT NULL
    DEFAULT 0`, `sections_viewed JSONB NOT NULL DEFAULT '[]'`, `cta_clicks Integer NOT
    NULL DEFAULT 0`, `tel_clicks Integer NOT NULL DEFAULT 0`, `form_started_at timestamptz
    NULL`, `form_submitted_at timestamptz NULL`, `lead_id Integer FK leads ON DELETE SET
    NULL NULL idx`, `event_count Integer NOT NULL DEFAULT 0`, `created_at/updated_at`.
    Índice `(org_id, first_seen_at)`.
  - `landing_events`: `id BigInteger PK`, `org_id` (igual), `session_id BigInteger FK
    landing_sessions CASCADE NOT NULL idx`, `type Text NOT NULL`, `at timestamptz NOT
    NULL`, `meta JSONB NULL`, `created_at`. Índice `(org_id, at)`.
  - **Solo `Text`, ninguna `String(N)`** (evita `test_text_limits`). `downgrade()`
    completo.
- `backend/app/models/landing.py` (nuevo) + re-export en `models/__init__.py`:
  `LandingSession`, `LandingEvent`, y `LANDING_EVENT_TYPES = frozenset({"page_view",
  "section_view", "scroll", "cta_click", "tel_click", "form_start", "form_submit",
  "form_error"})`.
- `backend/app/services/landing_analytics.py` (nuevo, **funciones puras**, sin BD):
  - `referrer_host_of(url: str | None) -> str | None` (host en minúsculas, sin `www.`;
    `android-app://com.google.android.youtube` → `youtube.com`).
  - `source_of(utm_source: str | None, referrer_host: str | None) -> str`: prioridad
    `utm_source` normalizado (`youtube|tiktok|instagram|facebook|google|other`); si no,
    por host (`youtube.com|youtu.be→youtube`, `tiktok.com→tiktok`, `instagram.com|
    l.instagram.com→instagram`, `facebook.com|l.facebook.com|fb.com→facebook`,
    `google.*→google`, `bing.com|duckduckgo.com→search`, vacío→`direct`, resto→`other`).
  - `device_of(ua)`, `browser_of(ua)`, `os_of(ua)`, `in_app_of(ua)`: familias gruesas por
    regex (`Mobile|Android(?!.*Tablet)|iPhone→phone`, `iPad|Tablet→tablet`, resto
    `desktop`; `Instagram`→in_app instagram; `BytedanceWebview|musical_ly|TikTok`→tiktok;
    `FBAN|FBAV`→facebook). **El UA crudo no se guarda nunca.**
  - `geo_of(headers) -> (country, region, city)`: `cf-ipcountry` (descartar `XX`, `T1`),
    `cf-region-code`, `cf-ipcity`; `None` cuando falten.
  - `merge_session(session, batch, now)`: `last_seen_at=now`, `max_scroll_pct` monótono,
    `sections_viewed` = unión ordenada por primera vez, contadores `+=`, `form_started_at`
    solo si nulo, `event_count += len`.
- `backend/app/api/v1/public.py`:
  - Constantes propias: `EVENTS_PER_IP_LIMIT = 60`, `EVENTS_PER_IP_WINDOW = 600.0`,
    `EVENTS_GLOBAL_LIMIT = 3000`, `EVENTS_GLOBAL_WINDOW = 600.0`, `EVENTS_MAX_BODY = 16_384`
    `EVENTS_MAX_PER_BATCH = 25`, contadores separados (`_ev_hits`, `_ev_global_hits`) con
    el mismo mecanismo acotado (`MAX_TRACKED_IPS`); `reset_rate_limits()` los vacía también.
  - `class LandingEventIn(BaseModel)`: `t: str` (∈ `LANDING_EVENT_TYPES`), `meta: dict[str,
    str | int] | None` (≤ 5 claves, valores ≤ 120 chars). `class LandingBatchIn(BaseModel,
    extra="forbid")`: `form: str | None`, `session: str` (regex `^[0-9a-f]{32}$`), `path:
    str ≤ 200`, `lang: Literal["en","es"] | None`, `screen_w: int | None` (0-10000), `utm:
    dict[str,str] | None` (pasa por `clean_attribution` — misma lista blanca, **sin
    añadir claves**), `referrer: str | None ≤ 500`, `events: list[LandingEventIn]` (1..25).
  - `@router.post("/landing", status_code=204)`: orden fijo — (1) `_ev_ip_limited` → 429;
    (2) `raw = await request.body()`; `len(raw) > EVENTS_MAX_BODY` → 413; `json.loads` →
    400; `LandingBatchIn.model_validate` → **400** (el cuerpo llega como `text/plain` desde
    `sendBeacon`, por eso no se usa el parseo de Pydantic del cuerpo); (3) `_ev_global_limited`
    → 429; (4) `if not get_settings().LANDING_EVENTS_ENABLED: return` (204, nada escrito);
    (5) `org_id = await webhook_org_or_refuse(CHANNEL_WEB, body.form, fallback_when_unmapped=not
    body.form)` — en `WebhookOrgUnresolved` → log + 204 (una baliza no obtiene un oráculo);
    `set_org_id(org_id)`; (6) upsert de sesión: `INSERT … ON CONFLICT (org_id, session_key)
    DO NOTHING` + `SELECT`, `merge_session`, `add_all(LandingEvent(... at=now ...))`
    (**hora del servidor**, no la del cliente), `commit`. Respuesta siempre 204.
  - `capture` (`/leads`): `PublicLeadIn.session_id: str | None`, **`max_length=64`
    y deliberadamente SIN `pattern`**. El plan pedía «la misma regex», y eso era
    un error: un `pattern` en Pydantic devuelve 422 y **rechaza el formulario
    entero**, así que una clave de sesión corrupta costaría el lead. La forma se
    comprueba después, con `_SESSION_KEY.fullmatch`, y si no encaja sólo se
    pierde el enlace con la visita. Un lead vale más que su atribución. Tras el
    `commit` del lead: `UPDATE landing_sessions SET lead_id=:lead, form_submitted_at=now
    WHERE org_id=:org AND session_key=:sid AND lead_id IS NULL` (idempotente; en
    `duplicate` no se toca). **No entra en `ATTRIBUTION_KEYS`.**
- `backend/app/config.py` + `.env.example` + `docker-compose.yml` (bloque `backend:`):
  `LANDING_EVENTS_ENABLED: bool = True`, `LANDING_EVENTS_RETENTION_DAYS: int = 90`,
  **`LANDING_SESSIONS_PER_DAY: int = 20000`** (añadido al ejecutar, ver abajo).

  > **Añadido durante F1, y el plan lo necesitaba.** La auditoría de cierre
  > encontró un hallazgo BLOQUEANTE que este documento no preveía: el
  > limitador acota la **velocidad**, no el **total**. Con 60 balizas por IP y
  > ventana, **una sola dirección puede crear 8.640 filas permanentes al día**,
  > y ninguna de ellas caduca. La retención de `LANDING_EVENTS_RETENTION_DAYS`
  > no lo tapa: borra eventos, no sesiones. El tope va sobre la **creación de
  > sesiones**, por agencia y por día local — un visitante ya conocido sigue
  > pudiendo emitir, así que una avalancha no ciega la medición de quien ya
  > estaba leyendo.
- `backend/app/services/landing_analytics.py::purge_landing_events(db)`: `DELETE FROM
  landing_events WHERE at < now() - retention` (las sesiones se conservan). Se invoca
  como sentencia adicional del `try` de `_llm_monitor_loop` (`main.py:468-500`), el
  mismo sitio donde ya viven `run_render_watch_tick` y `run_fair_housing_tick`; **sin
  bucle nuevo**. Corre con `run_for_every_org`.
- `docs/public-capture-form.md`: sección «Eventos de la landing» (qué se guarda, qué no,
  retención, GPC).

**Casos borde que cubren los tests** (`backend/tests/test_public_landing_events.py`,
calcando `test_public_capture.py` con `ASGITransport` y `reset_rate_limits` autouse;
`backend/tests/test_landing_is_tenant_isolated.py` calcando
`test_content_rail_is_tenant_isolated.py`):
1. Lote válido → 204, 1 sesión, N eventos, `source` derivado, `at` = hora servidor.
2. Segundo lote misma `session` → misma fila; `max_scroll_pct` no baja; `sections_viewed`
   es unión; `cta_clicks` suma; `event_count` suma.
3. Tipo desconocido / 26 eventos / `session` mal formada → **400** y **nada**
   escrito. Escrito como 422 en el plan y cambiado al implementarlo: un 422
   describe una entidad que el cliente puede corregir, y aquí no hay cliente
   que lea la respuesta — una baliza es un disparo sin retorno. Un cuerpo mal
   formado es una petición mal formada.
4. Cuerpo > 16 KB → 413; JSON inválido → 400; `text/plain` válido → 204.
5. **Separación de presupuestos**: agotar `EVENTS_PER_IP_LIMIT` → 429 en `/landing` **y
   un POST a `/leads` sigue pasando**. (Mutación: reutilizar `_ip_limited` → rojo.)
6. Cabeceras `cf-ipcountry: US`, `cf-region-code: CO`, `cf-ipcity: Denver` → columnas;
   ausentes → `NULL`; `XX` → `NULL`.
7. UA de Instagram in-app → `device=phone`, `in_app=instagram`; **ninguna columna
   contiene el UA** (afirmar sobre `row.__dict__`).
8. `session_id` en `/leads` → `lead_id` y `form_submitted_at` puestos; una `session_key`
   de **otra org** no se enlaza; `duplicate` no re-enlaza.
9. `LANDING_EVENTS_ENABLED=false` → 204 y cero filas.
10. Aislamiento: sesiones de la org A invisibles bajo `org_scope(B)`; insert bajo B con
    `org_id=A` rechazado. (Mutación: quitar `FORCE ROW LEVEL SECURITY` de la migración →
    rojo.)
11. `purge_landing_events` borra eventos de hace 91 días, conserva los de 89 y todas las
    sesiones.
12. **Guardia nueva de repo** `backend/tests/test_every_org_table_has_rls.py`: para cada
    tabla de `Base.metadata` con columna `org_id`, `pg_class.relrowsecurity AND
    relforcerowsecurity` son `true`. Protege las tres tablas que este plan añade.

**Criterio de terminado:** bloques de §3 en verde; mutaciones 5 y 10 verificadas;
`docker build` OK; commit `feat(api): landing events endpoint + schema (051)`. **No se
despliega solo** (sin F2 no hay emisor).

---

### F2 — El tracker en la landing (y la atribución que no se pierde)

**Objetivo verificable:** una visita real desde un teléfono a `www.denverhomestory.com`
deja una fila en `landing_sessions` con `source`, `device`, `country`, secciones vistas
y scroll; enviar el formulario la enlaza con el lead.

**Archivos y cambios:**

- `frontend/lib/track.ts` (nuevo, **puro y testable**; sin DOM salvo por inyección):
  - `newSessionKey(rand = crypto.getRandomValues)` → 32 hex.
  - `sessionKey(storage)` → lee/crea `dhs.sid` en `sessionStorage`; si `storage` lanza
    (in-app browsers con almacenamiento bloqueado) → clave en memoria para esa carga.
  - `persistAttribution(params, referrer, storage)` → `dhs.attr` JSON, **primer toque
    gana** (no sobrescribe si existe); `storedAttribution(storage)`.
  - `trackingAllowed(nav)` → `false` si `nav.globalPrivacyControl === true` (Colorado
    reconoce GPC) — el tracker no emite nada.
  - `class Tracker { constructor(opts: {form?, session, path, lang, screenW, utm, referrer,
    send: (json: string) => boolean}) ; record(t, meta?) ; flush() }`: cola ≤ 25 por envío;
    `section_view` deduplicado por sección; `scroll` solo al cruzar 25/50/75/100 por
    primera vez; envío inmediato para `cta_click|tel_click|form_start|form_submit|form_error`;
    el resto en `flush()` (temporizador de 10 s si hay cola, `visibilitychange→hidden`,
    `pagehide`). Payload = `LandingBatchIn`.
  - `beaconSender(url)` → `navigator.sendBeacon(url, new Blob([json], {type:"text/plain"}))`;
    si devuelve `false` o no existe → `fetch(url, {method:"POST", body: json, keepalive:
    true, headers: {"Content-Type":"text/plain"}})`.
- `frontend/components/landing/LandingTracker.tsx` (nuevo, `"use client"`, montado en
  `Landing()` como hermano de `<main>`, igual que `MobileMenu`): en `useEffect` construye
  el `Tracker` con `FORM_KEY` (`NEXT_PUBLIC_CAPTURE_FORM_KEY`, ya existe), `path`,
  `lang` del contexto i18n, `innerWidth`, atribución (`collectAttribution` + persistida),
  `document.referrer`; emite `page_view`; `IntersectionObserver` (umbral 0,5) sobre
  `#about, #how, #markets, #consult` → `section_view {section}`; listener `scroll`
  pasivo → profundidad; delegación de `click` en `document`: `a[href^="tel:"]` →
  `tel_click {where: el.dataset.track ?? "unknown"}`, `a[href="#consult"]` → `cta_click
  {where}`. Limpieza en el desmontaje.
- `frontend/components/landing/Landing.tsx`: `data-track="nav"|"hero"|"menu"|"footer"`
  en las anclas `tel:` y `#consult` existentes (`:122,125,272,404,412` y las del
  `MobileMenu`). **Sin cambiar textos.**
- `frontend/components/landing/ConsultForm.tsx`: atribución = URL ∪ `storedAttribution`
  (la URL manda si trae algo); `form_start` en el primer `focus` de cualquier campo (una
  vez); `form_submit` al `outcome.ok`, `form_error {reason}` si no; **`session_id`** en
  `submitPublicLead`. Expone el `Tracker` por contexto React ligero
  (`LandingTrackerContext`) o por un singleton en `track.ts` — elegir el singleton
  (`getTracker()`), más simple y testable.
- `frontend/lib/api.ts`: `CapturePayload.session_id?: string`.
- **Ninguna `NEXT_PUBLIC_*` nueva** (el interruptor es `LANDING_EVENTS_ENABLED` en el
  servidor). Evita los 4 sitios de `landingConfigWiring`.

**Tests** (`frontend/lib/__tests__/track.test.ts`, puros; y lectura de fuente en
`landingHero.test.ts`, que ya quita comentarios antes de casar):
1. Payload cumple el contrato (claves exactas; `events` ≤ 25; `session` 32 hex).
2. `scroll` 30→40→60 emite solo 25 y 50; `section_view` repetida no se duplica.
3. Eventos de conversión disparan `send` inmediato; `page_view` no.
4. `sessionKey` estable dentro del mismo `storage`; `storage` que lanza → clave en
   memoria, sin excepción.
5. `persistAttribution` no sobrescribe el primer toque; `storedAttribution` devuelve lo
   guardado.
6. `trackingAllowed({globalPrivacyControl:true})` → `false`, y el `Tracker` con
   `allowed=false` no llama a `send`. (Mutación: ignorar GPC → rojo.)
7. `beaconSender` cae a `fetch` cuando `sendBeacon` falta o devuelve `false`.
8. Fuente: `Landing.tsx` monta `LandingTracker` **fuera** de `[data-pin-host]`;
   `ConsultForm.tsx` envía `session_id`; las cinco anclas `tel:`/`#consult` llevan
   `data-track`. (Mutación: quitar `session_id` del payload → rojo.)

**Verificación real:** stack local (`scratchpad/run_backend.sh` + `next dev` o el
build) + Playwright (`pw-*.js` con `NODE_PATH` del caché de npx) a 390×844 y 1440×900:
recorrer la página, pulsar el `tel:` (interceptar navegación), enviar el formulario con
Turnstile en modo test → `SELECT source, device, in_app, country, max_scroll_pct,
sections_viewed, cta_clicks, tel_clicks, form_started_at, lead_id FROM landing_sessions`
muestra la sesión completa y enlazada. Con `--reduced-motion` y con `sessionStorage`
bloqueado también llega. **Después del deploy A**: visita del dueño desde su teléfono
por cada red (abriendo el enlace de bio o tecleando) → misma consulta en el VPS; un
`country` no nulo prueba que las cabeceras `cf-ip*` atraviesan (si `city` es nula,
falta el clic de Cloudflare — §7.4).

**Cierre del checkpoint A:** bump **0.72.0** en `backend/app/config.py`,
`frontend/lib/version.ts` (constante + entrada EN/ES), `CHANGELOG.md`. Commit
`feat(frontend): landing tracker + release 0.72.0`. Runbook: rebuild backend **y**
frontend, migrar 051, `up -d`. Reversión: HEAD `4997cd3` + rebuild (el downgrade de 051
borra lo recogido). **Parar y pedir autorización.**

---

### F3 [CRÍTICA] — Historial del lead y llamadas de voz completas

**Objetivo verificable:** todo cambio de `Lead.status` deja una fila en `lead_events`
con `from/to` y actor; toda llamada VAPI deja `call_inbound` con duración y motivo de
fin, y `conversations.summary` se escribe.

**Por qué es crítica:** toca `before_flush` (el mismo gancho que estampa `org_id` en
toda la app) y `ingest_voice_call`, que ya perdió una transcripción una vez por un
`PendingRollbackError` (`conversation.py:629-639`). Un fallo aquí pierde llamadas
reales de clientes, y no se ve.

**Paso 0, antes de escribir código:** leer **un `Call` real** de VAPI para fijar los
nombres de campo (la documentación pública no confirma `durationSeconds`). Los ids
están en `conversations.external_thread_id` de las 5 conversaciones `voice`. Comando
(la clave se expande **dentro** del VPS y no se imprime; solo se imprimen los nombres
de campo):
```
ssh ender-vps 'K=$(sed -n "s/^VAPI_API_KEY=//p" ~/Eko-AI-RealEstate/.env); \
  curl -s -H "Authorization: Bearer $K" https://api.vapi.ai/call/<id> \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(sorted(d.keys())); \
    print(sorted((d.get(\"artifact\") or {}).keys())); print(d.get(\"endedReason\"), d.get(\"startedAt\"), d.get(\"endedAt\"))"'
```
Anotar en `PROJECT_STATUS.md` qué campos existen. El fixture del test se escribe **con
esos nombres**.

**Archivos y cambios:**

- Migración `20260904_1100_lead_events.py` — `revision = "052_lead_events"`,
  `down_revision = "051_landing_sessions"`. Tabla `lead_events`: `id BigInteger`,
  `org_id` (FK, idx), `lead_id Integer FK leads CASCADE NOT NULL idx`, `type Text NOT
  NULL`, `at timestamptz NOT NULL`, `actor Text NULL` (email, `"system"`, `"vapi"`),
  `from_status Text NULL`, `to_status Text NULL`, `meta JSONB NULL`, `created_at`.
  Índices `(org_id, at)`, `(lead_id, at)`. RLS + GRANTs como 051.
- `backend/app/models/lead_event.py` + re-export. `LEAD_EVENT_TYPES = frozenset({"created",
  "status_changed", "call_inbound", "call_logged", "appointment_set",
  "appointment_cancelled", "appointment_outcome", "deal_closed"})`.
- `backend/app/services/lead_events.py` (nuevo): `record(db, lead, type, *, actor=None,
  from_status=None, to_status=None, meta=None, at=None) -> LeadEvent` — **`org_id=lead.org_id`
  explícito siempre** (en una sesión bypass `before_flush` no estampa, y el orden de dos
  listeners `before_flush` no está garantizado). Valida `type ∈ LEAD_EVENT_TYPES`.
- `backend/app/db/base.py`: segundo listener `before_flush` `_record_lead_history` junto a
  `_stamp_org_id`: para cada `Lead` en `session.new` → `created`; para cada `Lead` en
  `session.dirty` con `inspect(lead).attrs.status.history.has_changes()` → `status_changed`
  con `from/to` (`.value`), `actor = getattr(lead, "_status_actor", None)`. Los
  `LeadEvent` se añaden con `session.add` dentro del propio `before_flush` (SQLAlchemy
  los incluye en ese flush). `lead.id` puede ser `None` en `session.new` → usar la
  relación (`LeadEvent(lead=lead)`, con `LeadEvent.lead = relationship("Lead")` declarada
  en el modelo) y no el id.
- `backend/app/api/v1/leads.py::patch_lead`: firma gana `request: Request`; antes del
  `setattr`, si `"status" in updates`: `row._status_actor = current_email(request) or
  "office"` (`current_email` ya existe en `api/v1/auth.py:85`).
- `backend/app/services/calls.py:246-262`: tras decidir el estado, `lead._status_actor =
  call.logged_by`; y `record(db, lead, "call_logged", actor=call.logged_by,
  meta={"outcome": outcome.value, "call_log_id": call.id})`.
- `backend/app/services/voice.py::VoiceCallReport` gana `duration_seconds: float | None`,
  `ended_reason: str | None`, `recording_url: str | None`, `cost: float | None`,
  `started_at: datetime | None`. `parse_end_of_call_report` los rellena **con los nombres
  del paso 0** (candidatos, en este orden: `msg.durationSeconds`; si no,
  `call.endedAt - call.startedAt`; `msg.endedReason` o `call.endedReason`;
  `msg.recordingUrl` o `artifact.recordingUrl` o `artifact.recording.*Url`; `msg.cost` o
  `call.cost`). Todo dentro de `try/except Exception` → `None` + `log.warning`; **un campo
  ausente o de tipo raro jamás impide el ingest**.
- `backend/app/services/conversation.py::ingest_voice_call`: tras crear/obtener `conv`,
  `if report.summary and not conv.summary: conv.summary = report.summary[:5000]`; y
  **solo si `not already_ingested`**: `record(db, lead, "call_inbound", actor="vapi",
  meta={"call_id", "duration_seconds", "ended_reason", "recording_url", "cost",
  "conversation_id"})`. La llamada a `record` va **fuera** del `begin_nested` de los turnos
  y después de él.
- Citas: `record(..., "appointment_set", meta={"visit_id", "purpose", "scheduled_at",
  "assigned_email", "via": "voice"|"panel"|"manual"})` en los tres puntos de creación
  (`services/voice.py:512-529`, `api/v1/visits.py:519-533`, `api/v1/visits.py:733-745`) y
  `"appointment_cancelled"` en `visits.py:622`. **Un evento manual del calendario puede no
  tener lead** (`visit.lead_id` nullable, `models/visit.py`): sin lead no se registra nada
  y se sale en silencio — no hay a quién colgárselo.
- `api/v1/leads.py::LeadOut`: nada nuevo aquí (la línea de tiempo la pinta F8 desde
  `GET /api/v1/leads/{id}/events`, endpoint nuevo en esta fase: lista `lead_events` del
  lead ordenada por `at, id`, esquema `LeadEventOut {type, at, actor, from_status,
  to_status, meta}`; **`meta.recording_url` solo se devuelve a `current_role == "admin"`**).

**Tests** (`backend/tests/test_lead_events.py`; fixtures de voz en
`test_voice_webhook*.py` existentes como plantilla):
1. `PATCH /leads/{id} {"status":"qualified"}` → 1 evento `status_changed new→qualified`,
   `actor` = email del token; un PATCH sin `status` → 0 eventos.
2. `log_call(outcome=BOOKED_VISIT)` → `status_changed` + `call_logged` con `outcome`.
3. Lead creado por `capture_lead` → `created`; por `ingest_voice_call` → `created` +
   `call_inbound`.
4. **Sesión bypass** (`org_scope(None)`, patrón `test_no_request_paths.py`): cambiar el
   estado → evento con `org_id == lead.org_id`. (Mutación: quitar el `org_id=` explícito
   → rojo.)
5. Fixture VAPI completo → `call_inbound.meta.duration_seconds` y `ended_reason`;
   `conv.summary` escrito. Fixture **sin** duración ni motivo → ingest OK, `meta` con
   nulos. Fixture con `durationSeconds: "abc"` → ingest OK. (Mutación: quitar el
   `try/except` de los extras → rojo.)
6. Reporte reentregado (`already_ingested`) → **un solo** `call_inbound`.
7. Reservar por voz / panel / manual → `appointment_set` con `via` correcto; cancelar →
   `appointment_cancelled`.
8. `GET /leads/{id}/events` como `member` no trae `recording_url`; como `admin` sí.
9. Aislamiento (`test_every_org_table_has_rls` cubre la tabla; añadir el caso de lectura
   cruzada al test 4).

**Criterio de terminado:** §3 en verde; mutaciones 4 y 5; `docker build`; bump
**0.73.0**; commit `feat(db): lead history + voice call metadata (052)`. Deploy B:
migrar 052. Verificación real tras el deploy: una llamada del dueño al `+1 720 824 9313`
→ `SELECT type, meta->>'duration_seconds', meta->>'ended_reason' FROM lead_events WHERE
type='call_inbound' ORDER BY id DESC LIMIT 1` no nulo; `PATCH` de estado desde el panel →
fila con su email. **Parar y pedir autorización.**

---

### F4 — Resultado de la cita y cierre del negocio

**Objetivo verificable:** desde el panel se marca una visita como realizada / no vino,
y un lead como ganado con tipo de negocio (y perdido con motivo); todo queda en
`lead_events`.

**Archivos y cambios:**

- Migración `20260904_1200_deal_columns.py` — `revision = "053_deal_columns"`,
  `down_revision = "052_lead_events"`. En `leads`: `won_kind Text NULL`, `won_value
  Numeric(12,2) NULL`, `won_at timestamptz NULL`, `lost_reason Text NULL`. Sin tabla
  nueva. Espejo en `models/lead.py`; `WON_KINDS = ("listing_sold", "buyer_purchase",
  "rental", "referral", "other")` como constante (no enum de Postgres: cambiarla no debe
  exigir migración).
- `api/v1/visits.py`: `POST /visits/{id}/outcome` body `VisitOutcomeIn {outcome:
  Literal["completed","no_show"]}`: permitido solo desde `SCHEDULED|CONFIRMED` → 409
  `visit_not_open` si no; escribe `visit.status`; `record(..., "appointment_outcome",
  actor=current_email, meta={"visit_id","outcome","purpose"})`. **Rutas concretas antes
  que paramétricas** (regla pagada en este repo). Nota de compatibilidad verificada:
  `followups.py:496-498` ya trata `NO_SHOW` como muerto y `COMPLETED` como «los post-visita
  sí salen» — no tocar.
- `api/v1/leads.py::LeadPatch` gana `won_kind`, `won_value` (≥ 0), `won_at`, `lost_reason`
  (`_trim_or_clear`). Regla en `patch_lead`: si `updates["status"] == "won"` y no llega
  `won_kind` ni el lead lo tiene → 422 `won_kind_required`; al pasar a `won`, `won_at =
  won_at or now`; `record(..., "deal_closed", meta={"kind","value","won_at"})`. Al pasar a
  `lost` con `lost_reason` → `meta.reason` en el `status_changed` (el listener ya lo crea;
  añadir `lead._status_meta` leído por el listener). `LeadOut` devuelve los cuatro campos;
  **`won_value` se devuelve `None` a `member`** salvo decisión contraria (§7.1).
- Frontend: `components/leads/LeadDetail.tsx`: al elegir `won` en el selector de estado se
  abre `CloseDealDialog` (nuevo, `components/leads/CloseDealDialog.tsx`): tipo
  (select con las 5 opciones), fecha (hoy por defecto), importe opcional (solo `admin`);
  al elegir `lost`, campo de motivo opcional. `components/calendar/VisitsSection.tsx` y
  `CalendarView.tsx`: en visitas pasadas `scheduled|confirmed`, dos botones «Realizada» /
  «No vino» → `visitsApi.outcome(id, outcome)`. `lib/api.ts`: `visitsApi.outcome`,
  `Lead.won_kind|won_value|won_at|lost_reason`, `LeadPatch` idem. i18n EN/ES (2 espacios).
  Mobile-first: los botones caben a 390 px (medir con Playwright).

**Tests:** `test_visits_outcome.py` (transiciones, 409, evento, post-visita intactos);
`test_leads_deal.py` (422 sin `won_kind`; `won` con `won_kind` → columnas + `deal_closed`;
`member` no ve `won_value`; `lost_reason` en `meta`). Frontend: `i18nParity`; lectura de
fuente: `LeadDetail` monta `CloseDealDialog`; `VisitsSection` llama a `visitsApi.outcome`.
Mutación: quitar la regla `won_kind_required` → rojo.

**Criterio de terminado:** §3 en verde; mutación; commit `feat(api): visit outcome + deal
close (053)`. **Sin bump aún** (se agrupa con F5).

---

### F5 — UTM por plataforma en el CTA y enlaces de bio

**Objetivo verificable:** el pie de cada post lleva
`https://www.denverhomestory.com/?utm_source=<youtube|tiktok|instagram>&utm_medium=social&utm_campaign=<CONTENT_UTM_CAMPAIGN>&utm_content=piece-<id>`,
y `source_of` clasifica las visitas que lleguen con él.

**Archivos y cambios:**

- `backend/app/services/buffer_publisher.py`: función pura `with_platform_utm(text: str,
  cta_url: str, platform: PublicationPlatform, piece_id: int, campaign: str) -> str`:
  sustituye la **primera** aparición exacta de `cta_url` en `text` por la URL con query
  (respetando un `?` ya existente); si `cta_url` está vacío o no aparece, devuelve `text`
  sin cambios. Se aplica en `publish_piece` por plataforma, justo antes de
  `build_post_input`. **Después** de aplicarla, `find_violations(final_text, language)` debe
  seguir vacío — se afirma en test (la función solo toca la URL, pero la puerta se
  demuestra, no se supone).
- `config.py` + `.env.example` + compose: `CONTENT_UTM_CAMPAIGN: str = "video"`.
- `docs/setup-landing.md`: sección «Enlaces de bio con UTM» con las tres URLs exactas
  (`utm_medium=bio`, `utm_campaign=profile`) y el procedimiento de verificación (abrir
  desde el teléfono → fila con `source`).

**Tests** (`test_buffer_publisher.py`, con el `recorder` existente): el texto enviado a
YouTube contiene `utm_source=youtube&…&utm_content=piece-<id>`; a TikTok `utm_source=tiktok`;
caption sin URL → sin cambios; URL con `?x=1` → `&utm_source=…`; `find_violations` igual
antes y después. Mutación: no aplicar `with_platform_utm` → rojo.

**Cierre del checkpoint C:** bump **0.74.0**; commit `feat(content): per-platform UTM on
the CTA + release 0.74.0`. Deploy C: migrar 053, rebuild backend y frontend. **Acción del
dueño**: poner los tres enlaces de bio (§7.5). Verificación real: la siguiente publicación
programada lleva la URL con UTM (leerla con `post(input:{id}){text}` en Buffer o en la app);
abrir cada bio desde el teléfono → `SELECT source, utm_medium FROM landing_sessions ORDER
BY id DESC LIMIT 3` = tres redes distintas. **Parar y pedir autorización.**

---

### F6 — Métricas por vídeo: YouTube por API, TikTok/Instagram a mano

**Objetivo verificable:** cada publicación de YouTube con `external_url` tiene una foto
diaria de `views/likes/comments` en `content_metrics`; TikTok e Instagram aceptan el
número tecleado desde la consola.

**Archivos y cambios:**

- Migración `20260904_1300_content_metrics.py` — `revision = "054_content_metrics"`,
  `down_revision = "053_deal_columns"`. Tabla `content_metrics`: `id`, `org_id`,
  `publication_id BigInteger FK content_publications CASCADE NOT NULL idx`, `captured_on
  Date NOT NULL`, `views BigInteger NULL`, `likes BigInteger NULL`, `comments BigInteger
  NULL`, `source Text NOT NULL` (`youtube_api|manual`), `created_at`; `UNIQUE
  (publication_id, captured_on)`. RLS + GRANTs.
- `config.py` (+ `.env.example`, compose): `YOUTUBE_DATA_API_KEY: str = ""`,
  `CONTENT_METRICS_ENABLED: bool = False`, `CONTENT_METRICS_INTERVAL_SECONDS: int = 21600`.
- `backend/app/services/video_metrics.py` (nuevo — **el nombre no contiene `content`**, a
  propósito, para no entrar en el barrido `test_advance_is_the_only_thing_that_writes_a_status`):
  `youtube_video_id(url) -> str | None` (`watch?v=`, `/shorts/<id>`, `youtu.be/<id>`,
  `/embed/<id>`); `async fetch_youtube_stats(ids: list[str], key) -> dict[id, (views,
  likes, comments)]` con `httpx.AsyncClient(timeout=20).get("https://www.googleapis.com/youtube/v3/videos",
  params={"part":"statistics","id":",".join(ids[:50]),"key":key})` (**`.get`**, que no está
  en ningún barrido de cable); `async snapshot_youtube(db)`: publicaciones `PUBLISHED` de
  `youtube` con `external_url` de la org, en lotes de 50, upsert `ON CONFLICT
  (publication_id, captured_on) DO UPDATE` con `captured_on = hoy en la zona de la
  agencia`. Sin clave → un `log.info` por tick y nada más. Errores HTTP → `log.warning`,
  sin excepción.
- `main.py`: `_content_metrics_loop` calcado de `_content_publish_loop` (`sleep` primero,
  `max(3600, interval)`, `CancelledError` re-lanzada), variable global, arranque tras
  `CONTENT_METRICS_ENABLED`, **y la tupla de `_shutdown` (`main.py:1284-1290`)**.
- `api/v1/content.py`: `PUT /content/{piece_id}/publications/{platform}/metrics` body
  `{views: int ≥ 0, likes?: int, comments?: int}` → upsert `source="manual"` para hoy. Ruta
  concreta antes de las paramétricas existentes.
- `api/v1/content.py::PieceOut.publications[*]` gana `latest_metrics: {views, likes,
  comments, captured_on, source} | None`.

**Tests** (`test_video_metrics.py`): las 4 formas de URL; `httpx` parcheado → filas; misma
fecha dos veces → una fila actualizada; clave vacía → cero llamadas HTTP (afirmar sobre el
mock); 403 de cuota → sin excepción; PUT manual → fila `manual`; PUT con `views=-1` → 422;
aislamiento. Mutación: quitar `ON CONFLICT` → rojo.

**Cierre del checkpoint D:** bump **0.75.0**; commit `feat(content): per-video metrics
(054) + release 0.75.0`. Deploy D: migrar 054; el dueño pone `YOUTUBE_DATA_API_KEY` y
`CONTENT_METRICS_ENABLED=true` en el `.env` (§7.2). Verificación real: tras el primer
tick, `SELECT p.platform, m.views, m.captured_on FROM content_metrics m JOIN
content_publications p ON p.id=m.publication_id` con al menos una fila `youtube_api`.
**Parar y pedir autorización.**

---

### F7 — `GET /api/v1/analytics` v2

**Objetivo verificable:** una sola petición con rango de fechas devuelve el embudo
completo, agrupado en la zona horaria de la agencia, con valores que los tests afirman
número a número.

**Archivos y cambios:**

- `backend/app/services/analytics.py` (nuevo): funciones `async def *(db, org_tz, start,
  end)` que devuelven dataclasses/Pydantic. `start/end` son instantes UTC calculados a
  partir de fechas locales (`ZoneInfo(AgentSettings.timezone)`); **todo `GROUP BY` día usa
  `func.timezone(tz, col)`** antes de `func.date`.
- `backend/app/api/v1/analytics.py`: `GET ""` con `range: Literal["7d","30d","90d","all"]
  = "30d"` **o** `from`/`to` (`YYYY-MM-DD`, ≤ 366 días, `from ≤ to` → 422 si no). Router
  sigue bajo `_auth`. Respuesta `AnalyticsOut` v2 (sustituye a la actual; el único
  consumidor es nuestra vista):
  - `range {from, to, timezone}`
  - `traffic {sessions, engaged, avg_scroll_pct, cta_clicks, tel_clicks, form_starts,
    form_submits, by_day [{date, sessions, leads}], by_source [{source, sessions,
    tel_clicks, form_submits, leads}], by_device [{device, sessions}], by_in_app,
    by_country/by_region/by_city [top 10 {name, sessions, leads}], by_lang, sections
    {about, how, markets, consult}}` — `engaged` = `max_scroll_pct ≥ 50` **o** ≥ 2
    secciones.
  - `funnel [{stage, count, pct_of_previous}]` en este orden: `sessions → engaged → cta
    (sesiones con cta_click|tel_click|form_start) → leads (creados en rango, cualquier
    canal) → contacted (≥1 saliente `internal=False`) → called_back (≥1 `call_logs`) →
    appointment_set (≥1 visita) → appointment_held (≥1 visita `completed`) → won`.
  - `leads {total, by_channel (canal de la primera conversación), by_intent, by_status,
    by_source (utm_source o referrer de `meta.attribution`, `direct` si vacío,
    `no_web` si no hay atribución), new_by_day}`
  - `response {first_response_seconds {median, p90, avg}, by_kind {ai, human, fallback},
    unanswered}` — primera respuesta = primer saliente con `internal=False` por
    conversación; `kind`: `sender=human`→human, `llm_provider="fallback"`→fallback, resto
    ai. **Excluye `internal=True`.**
  - `calls {inbound, avg_duration_seconds, by_ended_reason top 5, after_tel_click_30m,
    logged, by_outcome}` — `after_tel_click_30m` = conversaciones `voice` cuyo
    `started_at` cae ≤ 30 min después de algún `tel_click` de la org (asociación, se
    etiqueta así).
  - `appointments {set, completed, no_show, cancelled, by_purpose, median_lead_to_set_hours}`
  - `deals {won, by_kind, total_value | null, median_days_lead_to_won, lost, lost_reasons
    top 5, close_rate = won/(won+lost)}` — `total_value` **solo si `current_role ==
    "admin"`**, si no `null`.
  - `content [{piece_id, hook, published_at, platforms [{platform, external_url,
    views_latest, views_7d_ago}], sessions_48h, leads_48h, leads_utm}]` — últimas 20
    publicaciones; `sessions_48h`/`leads_48h` = asociación temporal, `leads_utm` = leads
    con `utm_content = piece-<id>`.
  - `by_agent [{email, calls_logged, appointments, won}]` (de `call_logs.logged_by`,
    `visits.assigned_email`, `lead_events deal_closed.actor`).
- Índices que faltan para estas consultas se añaden en **una migración
  `055_analytics_indexes`** solo si `EXPLAIN` sobre la base de test con 10 k filas
  sintéticas lo justifica (criterio: > 200 ms por sección). Si no hace falta, se dice.

- 🔴 **Requisito previo que este plan no tenía: una tabla de agregados diarios.**
  `landing_events` se purga a los 90 días y `landing_sessions` **no se purga
  nunca**, porque hoy no puede: cada número del embudo se calcula sumando las
  filas vivas, así que borrar sesiones viejas **reescribiría el denominador de
  todos los informes pasados** — «en marzo convertimos el 4 %» pasaría a decir
  otra cosa el día que marzo se borre. Es la misma razón por la que el modelo ya
  prohíbe sumar eventos para un informe.

  La salida es congelar el pasado: una tabla `analytics_daily` (`org_id`, `day`
  local, y las cifras del embudo de ese día) escrita una vez por día cerrado y
  nunca recalculada. Con ella, un informe lee agregados para los días cerrados y
  filas vivas sólo para el día en curso, y **entonces sí** se pueden retener
  sesiones por antigüedad sin cambiar la historia.

  **Mientras no exista, el tope diario de sesiones de F1 es lo único que acota
  el crecimiento de esa tabla**, y hay que decirlo en voz alta: son dos piezas
  de la misma decisión, no dos tareas sueltas.

**Tests** (`test_analytics_v2.py`, con valores): sembrar bajo org A: 4 sesiones (2
`engaged`, 1 con `tel_click`, 1 con `form_submit` enlazada a un lead), 3 leads (uno con
`utm_source=tiktok`, uno `direct`, uno de voz), mensajes (1 humano, 1 IA, 1 `fallback`, 1
`internal`), 1 `call_log`, 2 visitas (1 `completed`), 1 `won` con `won_kind`, 1 publicación
con métricas; afirmar **cada número**. Org B → todo cero (aislamiento; H7). Un lead
creado a las `23:30 America/Denver` cuenta en **ese** día, no en el siguiente (H9;
mutación: agrupar en UTC → rojo). `internal=True` no cuenta como respuesta (H8; mutación:
quitar el filtro → rojo). `member` recibe `total_value = null`. `from > to` → 422.
`test_analytics.py` viejo se reescribe (forma + valores), no se borra.

**Criterio de terminado:** §3 en verde; las dos mutaciones; commit `feat(api): analytics
v2 — funnel, sources, geo, response, calls, deals, content`. Sin bump (va con F8).

---

### F8 — La página `/analytics`

**Objetivo verificable:** a 390 px y a 1440 px la página muestra las nueve secciones con
los números de F7, permite cambiar el rango, y los estados vacíos explican por qué.

**Archivos y cambios:**

- `frontend/lib/api.ts`: `analyticsApi.get(params: {range?} | {from, to})` construye la
  query; tipos `AnalyticsV2` completos (espejo de `AnalyticsOut`); `contentApi.setMetrics(pieceId,
  platform, body)`.
- `frontend/components/analytics/` (sustituye a `AnalyticsView.tsx`): `AnalyticsView.tsx`
  (estado de rango, fetch, layout), `RangePicker.tsx` (7/30/90/todo + dos `input type=date`),
  `KpiRow.tsx` (sesiones, leads, contactados, citas, ganados, mediana de respuesta),
  `FunnelSteps.tsx` (barras horizontales con % respecto al paso anterior), `Breakdown.tsx`
  (lista etiqueta/valor/secundario reutilizable — sustituye al `Bar` actual, con etiqueta
  traducida vía mapa `source.*`/`device.*`/`channel.*`), `DayChart.tsx` (SVG puro, columnas
  sesiones+leads, etiquetas cada N días según ancho — en 390 px máximo 7 etiquetas),
  `GeoCard.tsx`, `ResponseCard.tsx` (mediana/p90 y reparto IA/humano/respaldo),
  `CallsCard.tsx`, `AppointmentsCard.tsx`, `DealsCard.tsx` (importe solo si llega),
  `ContentTable.tsx` (filas por publicación; columna de vistas editable para TikTok/Instagram
  → `contentApi.setMetrics`; en móvil, tarjetas), `AgentsTable.tsx`. **Sin librería de
  gráficas** (el repo no tiene ninguna y no se estrena una).
- Estados vacíos honestos: «Sin sesiones aún: el tracker se activó el <fecha del deploy A>»,
  «TikTok e Instagram no exponen vistas por API: introdúcelas desde la app», y la
  etiqueta **«asociación en 48 h»**, nunca «atribución», en la tabla de contenido.
- `components/leads/LeadDetail.tsx`: bloque «Línea de tiempo» con `GET /leads/{id}/events`
  (F3), formateado con `relativeTime`/`exactTime` de `lib/format.ts`.
- `components/ui/Nav.tsx`: Analytics pasa de `hidden 2xl:inline-flex` a `hidden
  xl:inline-flex` (H13; en el `OverflowMenu` se ajusta a `xl:hidden`). Medir a 1280 px que
  el desplegable del Inbox sigue entero (la trampa del `overflow-x` ya pagada).
- i18n EN/ES para todas las claves nuevas (2 espacios).

**Tests:** `i18nParity`; `analyticsApi.test.ts` (query string para `range` y para
`from/to`); lectura de fuente: `AnalyticsView` monta las nueve tarjetas y `LeadDetail`
llama a `/events`; `Nav.tsx` ya no tiene `2xl:inline-flex` para analytics.

**Verificación real:** Playwright contra el stack local sembrado (el mismo seed del test
de F7 vía script en scratchpad) a 390×844 y 1440×900: capturas de las nueve secciones,
`scrollWidth === clientWidth` en 390, cambio de rango refresca, edición manual de vistas
persiste. Tras el deploy E, el dueño abre `/analytics` en su teléfono.

**Cierre del checkpoint E:** bump **0.76.0**; commit `feat(frontend): analytics page v2 +
release 0.76.0`. Deploy E: rebuild ambos (sin migración salvo 055). **Parar y pedir
autorización.**

---

### F9 — Cierre documental (sin deploy)

`docs/analytics.md` (nuevo): diccionario de métricas (definición exacta de cada número,
qué es medición y qué es asociación, retención, GPC, qué no se guarda). `PROJECT_STATUS.md`
con lo medido por checkpoint. Memoria: actualizar
`project_eko_realestate_estado_actual.md` y `MEMORY.md`. Commit `docs: analytics v2 —
metric dictionary and status`.

---

## 5. Backlog (no justifican fase)

- **Retención de `landing_sessions`**, que hoy no se puede hacer sin mentir
  sobre el pasado. Depende de la tabla de agregados diarios descrita en F7; sin
  ella, borrar una sesión vieja cambia un informe ya dado por bueno.

- H11: unificar la definición de «cerrado» entre `console.py:40` (incluye `PAUSED`) y la
  analítica; F7 define `close_rate = won/(won+lost)` y lo etiqueta así, pero la consola
  sigue con su propia lista.
- Etiquetas de canal sin traducir (`AnalyticsView.tsx:138`) — desaparece con F8.
- `attribution_later` no se expone ni se agrega (segundos toques).
- Backfill de `external_url` para las 15 publicaciones ya hechas (a mano, desde las apps)
  para que F6 las cubra.
- Reproductor de la grabación de la llamada en `LeadDetail` (F3 guarda la URL para admin).
- Exportar CSV del rango; comparativa periodo anterior por sección.
- Limitadores en proceso (un solo worker): al escalar, a Redis — ya documentado en
  `public.py:50-54`.
- Página de privacidad y enlace en el pie (hoy no existe ninguna; ver §7.6).
- Cuando Buffer exponga métricas por API (anunciado, sin fecha), sustituir la entrada
  manual de TikTok/Instagram.
- Dueño del lead (`assigned_email` solo existe en `visits`): «por agente» hoy se deriva de
  citas y llamadas registradas, no de una asignación del lead.

---

## 6. Riesgos y supuestos

**Riesgos de ejecución**
1. **Techo de atribución.** Enlaces no pulsables en Shorts/TikTok/Instagram e Instagram
   sin referrer → la mayor parte del tráfico de vídeo llegará como `direct`. Por red se
   arregla con los enlaces de bio con UTM (acción del dueño); por vídeo **solo asociación
   temporal**. Si la página lo pinta como certeza, miente. Fuentes: YouTube Help
   («Sharing links with your audiences», enlaces en descripciones de Shorts no
   pulsables); análisis de enlaces de Instagram (referrer eliminado, UTM conservado);
   TikTok acorta pero conserva la query.
2. **Bloqueadores.** Un `/api/v1/public/landing` puede caer en listas de bloqueo si la
   ruta contiene `track|analytics|collect|beacon|events`; por eso se llama `landing`. Si
   un bloqueador lo corta, el efecto es sub-conteo, no rotura.
3. **`before_flush` con dos listeners.** El orden no está garantizado; por eso `org_id`
   va explícito en cada `LeadEvent`. Test 4 de F3 lo vigila.
4. **`ingest_voice_call`.** Cualquier campo nuevo se lee dentro de `try/except`; una
   llamada real nunca se pierde por analítica.
5. **Nombres de campo de VAPI** sin confirmar hasta el paso 0 de F3 (medir un `Call` real
   antes de escribir el fixture).
6. **Cabeceras de geolocalización.** `cf-ipcountry` llega por defecto en todos los planes;
   ciudad/región exigen activar «Add visitor location headers» (Managed Transform; la
   documentación no indica restricción de plan). Sin el clic, `city`/`region` quedan
   nulas y la página lo dice.
7. **Segunda agencia real.** Con `channel_routes` vacía, formulario y tracker resuelven a
   la org 1 porque la demo está excluida. El día que exista otra agencia real, ambos
   deben enviar el `form key` (mismo mecanismo, ya previsto: `fallback_when_unmapped=not
   form`).
8. **Rendimiento.** Las consultas de F7 son agregados sobre tablas pequeñas hoy; los
   índices `(org_id, at)`/`(org_id, first_seen_at)` van en las migraciones; 055 solo si
   `EXPLAIN` lo pide.
9. **`sessionStorage` bloqueado** en algunos navegadores embebidos → una sesión por carga
   de página (sub-conteo de visitantes, no error).
10. **Downgrade de migraciones borra datos recogidos.** La reversión de cada checkpoint es
    `git reset --hard` + rebuild **sin** downgrade salvo orden expresa.

**Supuestos declarados**
- Cookieless, sin identificador persistente entre visitas, sin IP ni UA en crudo, GPC
  honrado, retención de eventos crudos 90 días: con eso **no hace falta banner de
  cookies**; sí conviene un aviso de privacidad (backlog / §7.6). Los umbrales de la
  Colorado Privacy Act (100 k consumidores/año) no se alcanzan.
- El registro de cierres (`won_kind`, `won_value`) es dato del CRM de la agencia. **Nuestra
  facturación no lo lee ni lo leerá** (Colorado prohíbe repartir comisión con quien no
  tiene licencia; la estructura acordada es suscripción / tramo por lead cualificado).
- La analítica sigue bajo `_auth` (cualquier miembro) salvo el importe de los cierres y la
  URL de grabación, que van a `admin`.
- `YouTube Data API v3` con clave de API (datos públicos, sin OAuth): `videos.list` cuesta
  1 unidad por llamada de hasta 50 vídeos; cuota diaria 10 000. Un tick cada 6 h gasta
  ~4 unidades/día.
- No se añade ninguna dependencia nueva ni en backend (`httpx` ya está) ni en frontend
  (gráficas en SVG a mano, como el `Bar` actual).
- Las `NEXT_PUBLIC_*` no cambian; el frontend se reconstruye igualmente en A, C y E por
  los componentes nuevos.

---

## 7. Decisiones del dueño

**Decididas el 4-sep-2026 (antes de aprobar el plan):**

1. ✅ **Cierre del negocio = tipo obligatorio + fecha automática + importe opcional, visible
   solo para `admin`.** F4 y F7 quedan escritas así (`won_value` → `None` para `member`;
   `deals.total_value` → `null` para `member`).
2. ✅ **YouTube Data API: el dueño crea la clave** en Google Cloud (APIs y servicios →
   Credenciales → Clave de API restringida a «YouTube Data API v3») y la teclea en el
   `.env` del VPS como `YOUTUBE_DATA_API_KEY` al llegar el deploy D. El agente no la ve.

**Pendientes (con el valor por defecto que aplica el plan si no se dice lo contrario):**

3. **Vistas de TikTok/Instagram a mano** desde la consola de contenido (una casilla por
   publicación). Recomendación: sí (30 s por vídeo a la semana); si no, esas columnas
   dirán «sin API».
4. **Cloudflare → Rules → Settings → Managed Transforms → «Add visitor location headers»**
   en la zona `denverhomestory.com` (un clic del dueño). Recomendación: sí, para ciudad y
   región; sin él, solo país.
5. **Enlaces de bio con UTM** en YouTube, TikTok e Instagram (los tres textos exactos los
   entrega F5). Es la única atribución **por red** fiable; sin ellos casi todo será
   `direct`.
6. **Aviso de privacidad.** ¿Construir una página `/privacy` breve (qué se mide, GPC,
   retención) y enlazarla en el pie? Recomendación: sí, en una tanda aparte; este plan no
   la incluye.
7. **Analytics para `member`**: ¿ve todo salvo importes (recomendado) o solo admin?

---

## Método de trabajo (vigente, sin cambios)

Investigar antes de tocar; evidencia `fichero:línea`; medir antes y después; «terminado»
solo con §3 en verde y mutaciones verificadas; comentarios solo cuando el porqué no es
obvio; i18n EN **y** ES; nunca imprimir `.env` ni claves (verificar por forma); los tests
jamás llaman a VAPI, Buffer, YouTube ni Cloudflare reales; nunca correos de prueba a
Natalia; sin merge ni PR sin pedirlo; cada deploy con autorización en un mensaje aparte;
auditoría al cerrar cada fase (máx. 2 subagentes, solo código ya escrito, base propia,
prohibido `git checkout/reset/stash/restore/clean`; hallazgo sin `fichero:línea` se
descarta); advisor en las fases [CRÍTICA] (F1, F3) y ante bloqueos, registrado en
`PROJECT_STATUS.md`. Cierre de turno ≤ 10 líneas, resultado primero.

# PLAN — Groq como red de seguridad del LLM (Fase 2 de `fix/llm-safety-net`)

> Escrito el 5-sep-2026 por Fable 5.1 tras recorrer el código real, ejecutar los
> comandos del proyecto y leer la documentación oficial de Groq. **Ejecutor:
> Opus 5**, fase por fase, máx. 3 intentos de corrección por fase, un commit
> convencional por fase, push, **sin merge ni PR sin pedirlo, sin desplegar sin
> autorización en un mensaje aparte**. Advisor en las fases [CRÍTICA] y tras el
> 2º intento fallido; registrar cada consulta en `PROJECT_STATUS.md`.
>
> La **Fase 1** de esta rama (alarma por email + Telegram, anti-parpadeo) está
> **cerrada** en `4ca286f`; su registro vive en `PROJECT_STATUS.md`. La versión
> anterior de este fichero está en ese mismo commit. Este `PLAN.md` queda sin
> commitear: Opus lo commitea como paso 0 de la Fase 2.1.

---

## 1. Objetivo y alcance

**Objetivo.** Que la cadena de LLM tenga una red de seguridad **que no dependa de
una casa**. Hoy es Kimi → MiniMax → Ollama-en-el-ROG, y el ROG es un portátil
doméstico que el 5-sep se colgó y estuvo 7 h fuera de la red. Pasa a ser
**Kimi → MiniMax → Groq → (ROG, si está vivo)**, y `/api/v1/health` deja de
ponerse en rojo porque un portátil esté durmiendo.

**Por qué Groq.** Decisión del dueño (5-sep): capa gratuita, sin tarjeta.
Elegido sobre DeepSeek de pago y sobre NVIDIA NIM.

**Dentro del alcance:**
1. Un cuarto proveedor en `generate_reply`, hablando protocolo OpenAI.
2. La sonda de salud (`check_fallback_provider`) pasa a describir **la red**
   (sana si Groq **o** el ROG pueden responder), sin gastar lo que vigila.
3. Los textos del vigilante y del arranque dejan de mandar al dueño al ROG
   cuando el problema no está ahí.
4. Documentación y bump **0.79.0**.
5. Una llamada real a Groq desde el VPS antes de pedir el deploy.

**Explícitamente fuera:**
- El orden de los dos proveedores de pago no cambia.
- **Ninguna dependencia nueva de Python**: `httpx` ya está; **no** se instala el
  SDK de OpenAI.
- No se toca ningún servicio del ROG (crontab, bittrader, ollama, coqui —
  prohibido). `OLLAMA_ENABLED` se queda como está.
- No se cambia el filtro de Fair Housing ni el prompt de sistema: es el mismo
  para los cuatro proveedores.
- No se toca la Fase 1 (`ops_alert.py`, el anti-parpadeo, el presupuesto).
- Ningún test llama a Groq de verdad.

---

## 2. Diagnóstico

### 2.1 Estado base (HEAD `4ca286f`, rama `fix/llm-safety-net`, árbol limpio)

| Comprobación | Salida real |
|---|---|
| Backend `pytest` desde base propia recreada (`eko_realestate_test_llm`) | **1565 passed, 0 failed, 0 skipped**, 38 warnings, 3 min 59 s, `exit=0` |
| Cobertura backend | **81 %** total (10 666 sentencias). `llm.py` no medido aparte; `llm_monitor.py` 90 %, `ops_alert.py` 97 %, `telegram_notify.py` 98 % |
| `ruff check app tests` | `All checks passed!` |
| Frontend `npx tsc --noEmit` | exit 0 |
| Frontend `npx vitest run` | **17 ficheros, 261 tests, 0 fallos** |
| `docker build -f backend/Dockerfile backend` | OK (construida en el cierre de la Fase 1) |
| Versión | `config.py:16` = `version.ts:1` = `CHANGELOG.md:5` = **0.78.0** |

### 2.2 Lo confirmado en la documentación oficial de Groq (leído, no recordado)

| Dato | Valor verbatim | Fuente |
|---|---|---|
| Base URL compatible OpenAI | `https://api.groq.com/openai/v1` | console.groq.com/docs/openai |
| Chat | `POST https://api.groq.com/openai/v1/chat/completions`; cuerpo mínimo `{"model", "messages"}`; texto en `choices[0].message.content`; uso en `usage.prompt_tokens` / `usage.completion_tokens` | console.groq.com/docs/api-reference |
| Listado de modelos | `GET https://api.groq.com/openai/v1/models` → `{"object":"list","data":[{"id":...}]}` | console.groq.com/docs/api-reference |
| Al superar el límite | **429** con cabecera `retry-after` (segundos) y `x-ratelimit-remaining-requests` / `-tokens` | console.groq.com/docs/rate-limits |
| Modelos de **producción** (no preview) | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b` (131 072 de contexto) | console.groq.com/docs/models |
| Parámetros OpenAI **no** soportados | `logprobs`, `logit_bias`, `top_logprobs`, `messages[].name`, `n≠1`; `temperature=0` se convierte a `1e-8` | console.groq.com/docs/openai |

**Lo que la documentación oficial NO dice**, y cómo lo trata el plan:
- **Los límites exactos de la capa gratuita** solo aparecen en la página de
  límites de la propia cuenta. Fuentes de terceros (no oficiales) citan para
  `llama-3.3-70b-versatile` ~30 req/min, **~1 000 req/día**, 12 K tok/min,
  100 K tok/día. Se trata como **supuesto a confirmar por el dueño** (§7).
- **Si `GET /models` cuenta contra los límites.** No está escrito. El diseño de
  la sonda (§4, Fase 2.2) asume que **sí** podría contar y se protege con una
  caché: peor caso 24 llamadas/día, el 2,4 % de un presupuesto de 1 000.

### 2.3 Hallazgos en el código, con evidencia y clasificación

| # | Hallazgo | Evidencia | Clase |
|---|---|---|---|
| H1 | Los dos proveedores de pago hablan **protocolo Anthropic** vía el SDK; Groq habla **OpenAI**. No hay ruta reutilizable | `llm.py:71-95` (`_provider_configs`), `llm.py:135-143` (`_build_client` con `AsyncAnthropic`) | condiciona el diseño |
| H2 | Ya existe un **segundo protocolo** en el módulo: `_ollama_generate` usa `httpx` contra `/api/chat` | `llm.py:97-133` | patrón a copiar |
| H3 | `_is_transient` no clasifica `httpx.HTTPStatusError`: un 4xx/5xx de Groq no sería «transitorio» | `llm.py:145-151` | la rama de Groq gestiona sus errores **como la de Ollama**: `try/except Exception → continue` (`llm.py:208-224`) |
| H4 | La sonda solo mira Ollama: con Groq vivo y el ROG apagado, `/health` seguiría diciendo `unreachable` — mentira en la dirección tranquilizadora | `llm.py:287-315` (`check_fallback_provider`); `health.py:40` | **bloqueante para el objetivo** |
| H5 | Los mensajes de arranque están atados a Ollama: con Groq caído dirían «run `ollama pull`» | `main.py:1238-1252` | importante |
| H6 | Los textos del vigilante nombran «el eslabón local (Ollama)» y mandan al ROG | `llm_monitor.py:77-95` (`_REMEDY`), `:159`, `:169-171`, `:334-336` | importante |
| H7 | Toda función con `.post` entra en **dos** barridos AST; `_ollama_generate` ya está declarada en ambos | `test_content_gate_is_absolute.py:435-436`, `test_opt_out_is_absolute.py:475-476` | la nueva función **debe declararse en los dos** o la fase cierra en rojo |
| H8 | Cada setting nuevo son **3 ediciones idénticas** o dos guardianes se ponen en rojo | `test_config_example.py` (los valores del `.env.example` no pueden contradecir el código), `test_compose_env.py` | 3 settings × 3 sitios |
| H9 | `Message.llm_provider` es `String(20)` **sin CHECK ni enum** | `models/message.py:95`; migración `20260525_1200_phase1_baseline.py:102` | `"groq"` cabe: **sin migración** |
| H10 | La analítica clasifica por exclusión: `human` / `fallback` / `else "ai"` | `analytics.py:329-334` (`kind_col`) | `"groq"` cae en `ai` **sin tocar nada** |
| H11 | El fixture de los tests de la cadena pinna `OLLAMA_ENABLED=false` para ser hermético, pero **no** conocerá `GROQ_API_KEY`: un desarrollador con clave en el entorno rompería tests que hoy pasan | `test_llm_fallback.py:45-56` (`_force_keys`) | menor, se arregla en la Fase 2.1 |
| H12 | Los tests de la sonda parchean `llm_module.httpx.AsyncClient`. Con dos sondas (Groq y Ollama) sobre el **mismo módulo `httpx`**, un parche pisa al otro | `test_llm_fallback.py:163-175` (`_probe_client`); lección pagada hoy en `test_ops_alert.py::_dual_http` | los dobles deben **enrutar por URL** |
| H13 | El docstring de `llm.py` y la documentación afirman que **todos** los proveedores hablan Anthropic; dejará de ser cierto | `llm.py:1-12`; `CLAUDE.md:60,109`; `README.md:43-44,54`; `docs/install.md:11,13`; `docs/roadmap.md:14` | menor, Fase 2.3 |

---

## 3. Comandos del proyecto (verificados hoy — son la definición de «terminado»)

```bash
# Backend — base con nombre propio de esta rama (NO reusar la de otra sesión;
# la suite no es idempotente y dos corridas sobre una base se contaminan)
docker exec eko-realestate-db psql -U eko -d postgres \
  -c "DROP DATABASE IF EXISTS eko_realestate_test_llm WITH (FORCE)" \
  -c "CREATE DATABASE eko_realestate_test_llm OWNER eko"
cd ~/Eko-AI-RealEstate/backend
PW=$(docker exec eko-realestate-db printenv POSTGRES_PASSWORD)
export DATABASE_URL="postgresql+asyncpg://eko:${PW}@localhost:5434/eko_realestate_test_llm"
export DATABASE_URL_APP="postgresql+asyncpg://eko_app:eko_app_local_pass@localhost:5434/eko_realestate_test_llm"
export WHATSAPP_ENABLED=true PYTHONDONTWRITEBYTECODE=1
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m pytest -q -p no:cacheprovider --cov=app --cov-report=term
./.venv/bin/python -m ruff check app tests --output-format=concise

# Frontend (solo la Fase 2.3 lo toca, por version.ts)
cd ~/Eko-AI-RealEstate/frontend && npx tsc --noEmit && npx vitest run

# Imagen
cd ~/Eko-AI-RealEstate && docker build -f backend/Dockerfile backend
```

Referencia de verde: **1565 backend / 261 frontend**, cobertura **81 %**. Cada
fase cierra con la suite en verde **sin saltados**, lint limpio, la imagen
compilando, cobertura del código nuevo ≥ la del fichero que toca (`coverage` no
traza dentro del greenlet de SQLAlchemy: si un número parece bajo, medir con
`--cov-config` y `concurrency = greenlet` sin cambiar la config del repo), diff
sin secretos, y las mutaciones de la fase verificadas (copiar, mutar, ver el
rojo, restaurar, `md5` idéntico, purgar `__pycache__`).

**Nunca imprimir** `.env` ni claves; verificar por **forma**. La clave de Groq
empieza por `gsk_`.

---

## 4. Fases

Rama **`fix/llm-safety-net`** (la de la Fase 1, ya empujada). Un commit por fase.
Un solo checkpoint de deploy al final, con bump 0.79.0.

### Fase 2.1 [CRÍTICA] — Groq en la cadena

**Objetivo verificable:** con Kimi y MiniMax forzados a fallar, `generate_reply`
devuelve un `LLMResult` sellado `provider="groq"`, sin tocar el ROG.

**Por qué es crítica:** toca `generate_reply`, por donde pasan **todas** las
respuestas a leads, el clasificador, el enriquecimiento, la importación de
ficheros y el escritor de contenido (6 llamantes: `grep -rn "generate_reply(" app`).
Un fallo aquí deja mudo al producto.

**Archivos y cambios:**

- **`backend/app/config.py`** (junto a `OLLAMA_*`, ~línea 59) +
  **`.env.example`** + **`docker-compose.yml`** (bloque `backend:`). Valores
  **idénticos** en los tres (H8):
  ```
  GROQ_API_KEY: str = ""
  GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
  GROQ_MODEL: str = "llama-3.3-70b-versatile"
  ```
  Comentario en `config.py`: capa gratuita, protocolo OpenAI, y que **sin clave
  el eslabón no existe** (igual que Kimi/MiniMax sin clave). Sin timeout propio:
  se reutiliza `LLM_TIMEOUT_SECONDS` (30 s); Groq es rápido y un setting más son
  tres ediciones más sin motivo.

- **`backend/app/services/llm.py`**:
  - `ProviderName = Literal["kimi", "minimax", "groq", "ollama", "fallback"]`.
  - `_provider_configs()` gana la entrada
    `"groq": ProviderConfig(name="groq", base_url=s.GROQ_BASE_URL, api_key=s.GROQ_API_KEY, model=s.GROQ_MODEL)`.
    Su `is_configured` es `bool(api_key)`: el mismo gate que los de pago.
  - **Nueva `async def _openai_chat_generate(cfg, messages, *, system, max_tokens, temperature, json_mode, timeout_s) -> LLMResult`**.
    Nombre genérico a propósito: otro proveedor compatible con OpenAI mañana no
    necesita función nueva. **Copia la forma de `_ollama_generate`
    (`llm.py:97-133`)**, con estas diferencias exactas:
    - URL: `f"{cfg.base_url.rstrip('/')}/chat/completions"`.
    - Cabecera `Authorization: Bearer {cfg.api_key}` (auth estándar OpenAI).
    - Cuerpo: `{"model": cfg.model, "messages": [system como {"role":"system"} si lo hay] + messages, "max_tokens": max_tokens, "temperature": temperature}`.
      **No** enviar `response_format` aunque `json_mode` sea `True`: el prompt
      de sistema ya lleva la instrucción de JSON (`generate_reply` la añade), y
      un `response_format` en un modelo que no lo soporte es un 400 evitable.
      **No** enviar `n`, `logprobs`, `logit_bias`, `messages[].name` (no
      soportados, § 2.2).
    - Respuesta: `text = data["choices"][0]["message"]["content"].strip()`;
      `input_tokens = usage.get("prompt_tokens", 0)`,
      `output_tokens = usage.get("completion_tokens", 0)`. Todo con `.get` y
      tolerante a claves ausentes.
    - `resp.raise_for_status()` **dentro** del `try` de la rama en
      `generate_reply` (H3): un 429/5xx de Groq es una excepción que la rama
      atrapa, loguea y **continúa** al siguiente eslabón, exactamente como la
      de Ollama (`llm.py:208-224`).
    - Devuelve `LLMResult(provider="groq", model=cfg.model, ...)`.
  - `generate_reply`: `order` pasa a ser
    `[PRIMARY, FALLBACK]` + `"groq"` (si `configs["groq"].is_configured`)
    + `"ollama"` (si `OLLAMA_ENABLED`). **Groq antes que el ROG.** La rama de
    Groq se despacha igual que la de Ollama (`if provider_name == "groq":`),
    llamando a `_openai_chat_generate` con `timeout_s=s.LLM_TIMEOUT_SECONDS`.
  - Docstring de cabecera (`llm.py:1-12`): **dos protocolos**, y cuál habla
    cada proveedor; la cadena de cuatro; el ROG como extra opcional, **no
    load-bearing**.

- **Los dos barridos AST (H7)** — declarar
  `"app/services/llm.py::_openai_chat_generate"` en:
  - `tests/test_content_gate_is_absolute.py` → `WIRE_NOT_PUBLISHING`, junto a
    `_ollama_generate` (:435): motivo *«POSTs a prompt to a hosted model; no
    content leaves»*.
  - `tests/test_opt_out_is_absolute.py` → `OUTBOUND_NOT_MESSAGING`, junto a
    `_ollama_generate` (:475): motivo *«POSTs a prompt to a hosted model; no
    lead is addressed»*.

- **`tests/test_llm_fallback.py`**:
  - `_force_keys` (H11) pinna además `GROQ_API_KEY=""`; los tests de Groq
    opta**n** con `monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy")` +
    `get_settings.cache_clear()`, como hace el de Ollama con su flag.
  - Tests nuevos, con el estilo del fichero (parchear `_build_client` para los
    de pago y `_openai_chat_generate` por nombre para Groq):
    1. Pago caído (`httpx.TimeoutException`) + Groq configurado → `provider == "groq"`.
    2. Groq **y** Ollama configurados, pago caído → contesta Groq y el doble de
       `_ollama_generate` **no** es llamado (`assert_not_awaited`).
    3. Groq lanza (`httpx.HTTPStatusError` 429 simulado) + Ollama configurado →
       contesta Ollama (la cadena no se rompe).
    4. Groq sin clave → se salta y el orden queda `[kimi, minimax]` (afirmar que
       `_openai_chat_generate` no se llama).
    5. Los cuatro fallan → `LLMUnavailable`.
    6. **Contrato HTTP** de `_openai_chat_generate` con `httpx.AsyncClient`
       parcheado: URL termina en `/chat/completions`, cabecera `Bearer`, cuerpo
       con `model`, `messages` (sistema primero), `max_tokens`, `temperature`,
       **sin** `response_format`; y que parsea `choices[0].message.content` y
       `usage`.

**Mutaciones** (cada una debe poner al menos un test en rojo):

| Mutación | Rojo esperado |
|---|---|
| no añadir `"groq"` a `order` | test 1 |
| añadir `"groq"` **después** de `"ollama"` | test 2 |
| `_openai_chat_generate` sin `Bearer` | test 6 |
| leer `choices[0]["text"]` en vez de `message.content` | test 6 |

**Criterio de terminado:** los comandos de §3 en verde; las cuatro mutaciones;
`docker build` OK. Commit: `feat(llm): Groq como tercer eslabon, antes del ROG`.
**Sin bump** (va en 2.3).

### Fase 2.2 [CRÍTICA] — La sonda describe la red, no una máquina

**Objetivo verificable:** `check_fallback_provider()` devuelve `ok` con Groq sano
y el ROG apagado; y ningún texto de arranque ni de alarma manda al dueño a
`ollama pull` cuando el fallo es la clave de Groq.

**Por qué es crítica:** es lo que `/health` y la alarma de la Fase 1 leen. Una
sonda que diga `ok` sin haber medido es el `OLLAMA_ENABLED=true` de la v0.54.2
otra vez: una bandera que no afirma nada sobre el mundo. Y una sonda que gaste
la cuota que vigila es la lección v0.54.3 al revés.

**Archivos y cambios:**

- **`backend/app/services/llm.py`**:
  - Constante `_GROQ_PROBE_TTL_SECONDS = 3600.0` junto a `_PROBE_TIMEOUT_SECONDS`,
    con el porqué escrito: la documentación no dice si `GET /models` cuenta
    contra los límites; con caché de una hora el peor caso son 24 llamadas/día
    (2,4 % de 1 000). El vigilante sigue tickeando cada 5 min y reutiliza la
    lectura cacheada. **Coste**: un cambio real en Groq se detecta en ≤ 65 min.
  - Caché a nivel de módulo: `_groq_probe_cache: tuple[float, FallbackStatus] | None`
    (instante monotónico + resultado). Nunca persistida.
  - **Nueva `async def _probe_groq() -> FallbackStatus`**:
    - Sin clave → `"off"`.
    - Caché vigente → devolver lo cacheado.
    - `GET {GROQ_BASE_URL}/models` con `Bearer`, timeout `_PROBE_TIMEOUT_SECONDS`.
    - **200** → `ok` si `GROQ_MODEL` está en `{m["id"] for m in data["data"]}`,
      si no `model-missing` (el chequeo de **dos partes** de la v0.54.2:
      responde **y** tiene el modelo).
    - **429** → **`ok`**: el servicio contestó; estar limitado no es estar
      ausente. Escrito en el código con esa frase.
    - **401/403** → `unreachable` con `log.error` nombrando `GROQ_API_KEY`
      (clave mala o revocada: **no** reintentar en bucle, la caché lo acota).
    - Conexión rota / timeout / 5xx → `unreachable`.
    - Guardar en caché y devolver. Nunca lanza.
  - `_probe_ollama()`: el cuerpo actual de `check_fallback_provider` tal cual,
    renombrado.
  - **`check_fallback_provider()`** pasa a componer:
    ```
    groq = await _probe_groq()
    ollama = await _probe_ollama()
    if "ok" in (groq, ollama): return "ok"
    if groq != "off": return groq        # hay un Groq configurado y falla: eso es lo que hay que arreglar
    return ollama                        # si no, lo que diga el ROG (hoy)
    ```
    Con Groq sin configurar se comporta **exactamente como hoy** (la Fase 1 no
    cambia de comportamiento en un despliegue sin clave).
  - Docstring de `FallbackStatus`: las cuatro palabras describen ahora **la
    red**, no una máquina.

- **`backend/app/main.py:1238-1252`** (H5): los dos `logger.error` de arranque
  dejan de nombrar solo Ollama. Texto: *«la red de seguridad del LLM no
  responde: ni Groq (`GROQ_BASE_URL`, `GROQ_API_KEY`) ni Ollama
  (`OLLAMA_BASE_URL`)»* y *«…responde pero ninguno tiene su modelo configurado
  (`GROQ_MODEL` / `OLLAMA_MODEL`)»*. Ambos ajustes mencionan las dos variables.

- **`backend/app/services/llm_monitor.py`** (H6): `_REMEDY["unreachable"]` y
  `["model-missing"]` nombran **ambos** proveedores y sus variables, sin mandar
  al ROG por defecto; `:159` («El tercer eslabon (Ollama local)») →
  «La red de seguridad (Groq / Ollama)»; `:169-171` y `:334-336` → «sin la red
  de seguridad». **Nada más del módulo se toca** (Fase 1 cerrada).

- **`tests/test_llm_fallback.py`** — tests de sonda. **H12**: un único doble de
  `httpx.AsyncClient` que **enrute por URL** (`"groq.com" in url` → respuesta
  de Groq, si no → respuesta de Ollama), como `_dual_http` en
  `test_ops_alert.py`. Cada test resetea `_groq_probe_cache = None`
  (`monkeypatch.setattr(llm_module, "_groq_probe_cache", None)`).
    1. Groq `200` con el modelo, Ollama **rota** → `ok`. *(El caso que hoy miente.)*
    2. Groq `200` **sin** el modelo, Ollama off → `model-missing`.
    3. Groq **429**, Ollama off → `ok`.
    4. Groq `401`, Ollama off → `unreachable`, y el log nombra `GROQ_API_KEY`.
    5. Groq conexión rota, Ollama `ok` → `ok` (la red la sostiene el ROG).
    6. Groq sin clave, Ollama sin habilitar → `off` (comportamiento de hoy).
    7. **Caché**: dos llamadas seguidas → **una** petición a `groq.com`
       (`assert` sobre el número de `get` con esa URL); tras avanzar el reloj
       monotónico parcheado más de `_GROQ_PROBE_TTL_SECONDS` → dos.
    8. Los tests existentes de la sonda (`:188-250`) siguen verdes **sin
       cambios**: prueban el camino con Groq sin clave.

**Mutaciones:**

| Mutación | Rojo esperado |
|---|---|
| que la sonda ignore Groq (devolver solo `_probe_ollama()`) | test 1 |
| no comprobar que el modelo está en `data[].id` | test 2 |
| tratar el 429 como `unreachable` | test 3 |
| quitar la caché | test 7 |

**Criterio de terminado:** §3 en verde; las cuatro mutaciones; `docker build`.
Commit: `feat(llm): la sonda de salud mide la red, no el ROG`. Sin bump.

### Fase 2.3 — Documentación y versión 0.79.0

**Objetivo verificable:** ningún fichero del repo afirma que «todos los
proveedores hablan Anthropic» ni que la cadena termina en el ROG; la versión es
una sola.

**Archivos y cambios (H13):**
- `CLAUDE.md:60`: la regla sigue siendo **nunca OAuth de Anthropic para el
  producto**; añadir que la red de seguridad es **Groq (gratis, protocolo
  OpenAI)** y el ROG un extra opcional. `CLAUDE.md:109`: los dos protocolos.
- `README.md:43-44,54`, `docs/install.md:11,13` (añadir `api.groq.com` a las
  salidas HTTPS necesarias), `docs/roadmap.md:14`, `docs/setup-discovery.md:47`.
- **Bump 0.79.0** en `backend/app/config.py:16`, `frontend/lib/version.ts:1`
  (+ una entrada EN/ES en `CHANGELOG` de `version.ts`, escrita con `json.dumps`
  — el `repr().replace` ya corrompió un apóstrofo dos veces en este repo) y
  cabecera de `CHANGELOG.md`. `test_version_is_one_number.py` exige que los tres
  coincidan.

**Criterio de terminado:** §3 en verde (backend **y** frontend, por
`version.ts`); `grep -rn "anthropic-messages" README.md CLAUDE.md docs/` no
devuelve afirmaciones falsas. Commit:
`docs(llm): Groq como red de seguridad + release 0.79.0`.

### Fase 2.4 — Verificación real y pre-deploy (sin desplegar)

**Objetivo verificable:** una respuesta real de Groq desde el VPS y la sonda
real diciendo `ok`, con la salida mostrada.

**Precondición (acción del dueño, §7):** `GROQ_API_KEY` en el `.env` del VPS.
Verificar por forma: `grep -cE "^GROQ_API_KEY=gsk_[A-Za-z0-9]{20,}$" .env` → `1`.

**Pasos, todos con la clave expandida dentro del VPS, nunca impresa:**
1. `GET /models` real → `HTTP 200` y `llama-3.3-70b-versatile` en la lista.
2. **Una** llamada real a `/chat/completions` con un mensaje corto → imprimir
   solo `model` y los primeros 80 caracteres de `choices[0].message.content`.
   Es lo que separa «los tests pasan» de «el proveedor contesta lo que creemos»
   — la lección de Kling.
3. `docker compose run --rm -T backend python -c "..."` que llame a
   `check_fallback_provider()` con la imagen nueva → `ok`.

**Checklist pre-deploy (dejar escrito en `PROJECT_STATUS.md` y parar):**
- Backup `.env` → `.env.bak.YYYYMMDD_v0790`.
- `git bundle` desde `4ca286f..fix/llm-safety-net` → `scp` → `git fetch` +
  `merge --ff-only` en el VPS.
- `docker compose build backend frontend` (frontend por `version.ts`).
- **Sin migración** (no hay esquema nuevo).
- `up -d backend frontend` → `/api/v1/health` = `0.79.0` y `llm_fallback: ok`.
- **Rollback**: `git reset --hard 4ca286f` + rebuild; el `.env` no se toca
  (la clave nueva es inofensiva sin código que la lea).
- Variables de entorno nuevas: solo `GROQ_API_KEY` (las otras dos llegan por
  defecto del compose).
- **Tras el deploy**: comprobar `/health` con el ROG dormido → sigue `ok`;
  forzar un tick del vigilante → sin aviso, y `monitor_state.llm_fallback.state`
  = `ok`.

---

## 5. Backlog (no justifica fase)

- **`_is_transient` no conoce `httpx.HTTPStatusError`** (H3). Se rodea en la
  rama; generalizarlo tocaría la clasificación de los de pago, fuera de alcance.
- **`_MAX_CHARS` de Telegram cuenta caracteres, Telegram unidades UTF-16.**
  Inalcanzable con los cuerpos actuales (Fase 1).
- **Con email sin configurar y Telegram sí**, `_send_email` escribe un ERROR por
  aviso. Acotado a 3/día por el presupuesto (Fase 1).
- **`retry-after` de Groq no se lee**: el eslabón se dispara rarísimamente y
  la cadena ya cae al siguiente; leerlo sería optimizar un caso que hoy no
  existe.
- **`json_mode` sin `response_format`**: si algún día el clasificador devuelve
  JSON malformado desde Groq, activar `response_format={"type":"json_object"}`
  **solo** para modelos que lo soporten. Hoy el prompt basta y Pydantic valida
  aguas abajo (`classifier.py`).
- **`docs/architecture.md:14-40`** describe una arquitectura on-prem con Ollama
  al centro que ya no es la del producto. Reescribirla es otra tanda.

---

## 6. Riesgos y supuestos

**Riesgos de ejecución**
1. **Lo gratis cambia de condiciones o retira el modelo sin avisar** — así se
   rompió Kling. Mitigación: la sonda comprueba que `GROQ_MODEL` sigue en la
   lista (Fase 2.2) y la alarma de la Fase 1 avisa por dos canales el día que
   deje de estar.
2. **Un 429 en el peor momento.** El eslabón se dispara rarísimamente; y si
   pasa, la cadena cae al ROG o a la línea de espera — **nunca peor que hoy**.
3. **La sonda gasta cuota.** Acotado por la caché (24/día). Si el dueño
   confirma un presupuesto diario holgado (§7), bajar `_GROQ_PROBE_TTL_SECONDS`
   es un cambio de una constante.
4. **Calidad de la respuesta inmobiliaria.** Mismo prompt de sistema que los
   demás. `llama-3.3-70b-versatile` es multilingüe (Meta lista el español entre
   sus idiomas) y es modelo de **producción**, no preview.
5. **Los dobles pisándose** (H12): dos sondas sobre el mismo módulo `httpx`.
   Resuelto en el plan con un doble que enruta por URL; si Opus ve un test de
   sonda pasar «por la razón equivocada», es esto.
6. **Los guardianes**: dos barridos AST y dos de settings. Están enumerados
   (H7, H8); descubrirlos en rojo cuesta un intento.

**Supuestos**
- La auth de Groq es `Authorization: Bearer <clave>` (estándar OpenAI; la
  página de compatibilidad muestra `api_key` en el SDK, que es lo mismo). Se
  confirma en la Fase 2.4 con la llamada real.
- `GET /models` **podría** contar contra los límites (no documentado) → caché.
- Los límites de la capa gratuita de terceros (~1 000 req/día) son
  **orientativos**; los reales están en la cuenta del dueño.
- La clave de Groq empieza por `gsk_` (forma observada en su consola; si no
  fuera así, ajustar la verificación por forma, no la clave).
- Un solo worker de uvicorn, una réplica (precondición ya escrita en
  `CLAUDE.md`): la caché de la sonda vive en el proceso y con N workers cada uno
  sondearía por su cuenta — N × 24/día, aún acotado.

---

## 7. Decisiones pendientes del dueño

1. **Crear la clave de Groq** en `console.groq.com` y ponerla en el `.env` del
   VPS como `GROQ_API_KEY`. Mismo procedimiento seguro que la de YouTube:
   `nano .env` dentro del VPS, copia previa, verificar por forma. **Bloquea la
   Fase 2.4**, no las anteriores.
2. **Leer los límites reales de la capa gratuita** en la página de límites de
   su cuenta y decir el número de **peticiones/día**. Si es ≥ 1 000, la caché
   de una hora está sobrada; si fuese mucho menor, hay que subir el TTL.
3. **Modelo.** El plan fija `llama-3.3-70b-versatile` (producción, 131 K,
   multilingüe). Alternativa de producción: `openai/gpt-oss-120b`. Confirmar o
   cambiar **antes** de la Fase 2.1 (es el valor por defecto en tres ficheros).
4. **Autorización de deploy**, en un mensaje aparte, cuando la Fase 2.4 deje el
   checklist escrito.

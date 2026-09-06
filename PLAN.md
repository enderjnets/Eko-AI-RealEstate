# PLAN.md — `/calculator`: la calculadora renta→compra de Denver Home Story

> **Para el ejecutor (Opus 5):** este fichero se copia a `~/eko-calculator/PLAN.md`
> en la Fase 0 y se commitea; es el plan vivo de la rama `feat/calculator`, como
> `PLAN.md` lo fue de `fix/llm-safety-net`. Lo que no esté escrito aquí, no
> existe. Máximo 3 intentos de corrección por fase; ante un bloqueo o en una
> fase **[CRÍTICA]**, consulta al advisor antes de improvisar.

---

## 1. Objetivo y alcance

**Objetivo.** Una página pública `www.denverhomestory.com/calculator` donde un
visitante que viene de un Short escribe **tres cosas** —lo que paga de renta,
cuánto tiene ahorrado y su rango de crédito— y recibe, sin dejar nada a cambio,
(a) **hasta qué precio de casa** podría comprar con ese mismo dinero al mes y
(b) **qué pasa a cinco años si compra en vez de alquilar**, con los supuestos a
la vista y editables. Debajo, el formulario de captura que ya existe, con
`landing_variant="calculator"`, y el cálculo viaja con el lead para que Natalia
lo vea en el aviso, en el Inbox y en la ficha.

**Decisiones del dueño, ya tomadas (5-sep-2026):**
1. Resultado **gratis**, sin muro; el correo se pide después.
2. **Tres entradas**: renta, ahorro, crédito. Lo demás, supuestos visibles.
3. **Inglés y español desde la v1.**
4. El lead **entra con contexto de calculadora**. ⚠️ Esta decisión se tomó sobre
   una premisa que la investigación desmiente: **hoy no existe ninguna respuesta
   automática para un lead web** (ver hallazgo B-1). Lo que sí se puede cumplir
   en la v1 es que el contexto llegue a Natalia por los tres caminos que existen.
   La respuesta automática al lead es la **decisión pendiente 7.1**.

**Modelo de referencia.** El PDF *Buy vs Rent* de Jeff Loveland (MBS Highway),
`~/Downloads/Buy vs Rent (7) (1).pdf`, ingenierizado a la inversa y verificado:
sus seis términos suman exactamente su total ($488.538 = 434.407 + 91.770 +
37.742 − 14.004 − 12.000 − 49.376), su cuota ($4.670 para $720.000 al 6,75%/360)
y su proyección ($1.234.407) se reproducen a mano. **Sus números son los
fixtures dorados de la Fase 1.** Cuatro cambios deliberados respecto a él:

| Jeff (prestamista) | Nosotros (brokerage) | Por qué |
|---|---|---|
| Parte del **precio** | Partimos de la **renta** y despejamos el precio | Es la promesa del Short y lo que nos diferencia |
| APR 6,888%, NMLS, «commitment to lend» | **Sin APR**, tasa ilustrativa con fuente y fecha | Publicar APR es publicidad de crédito (Reg Z); Natalia y Robbie no prestan dinero |
| Beneficio fiscal +$37.742 | **Fuera** | Depende de tramo, estado civil y si detalla; 8% del número y el más fácil de errar |
| Apreciación 4,94% impresa como hecho | **Deslizador**, valor por defecto conservador, fuente a la vista | Ese 4,94% genera $434.407 de $488.538 — el 89% del «gain» es un supuesto. Y Denver está en **−1,8% interanual** (Case-Shiller, may-2026) |

**Fuera de alcance (explícito):**
- Listados de casas reales (IDX/MLS) en la página o por correo. El CTA **no lo
  promete** (ver 6-Riesgos).
- Respuesta automática al lead por correo/SMS — decisión 7.1; si se aprueba, es
  la Fase 10, no la v1.
- Desglose de `/analytics` por `landing_variant` (hallazgo I-3, backlog).
- Sugerencias de barrio, ZIP o zona (Fair Housing: la página es aritmética pura).
- Refactor del pie de página compartido entre `/fall` y `/calculator` (backlog).
- Arreglar `requirements.txt` para que la receta de tests corra en limpio
  (hallazgo I-1, backlog: toca dependencias).
- Despliegue a producción sin autorización del dueño (decisión 7.7).

---

## 2. Diagnóstico

### 2.1 Estado base (medido en `~/eko-calculator` @ `6f6ee2d`, 5-sep-2026)

Entorno propio, aislado de la sesión que trabaja en `~/Eko-AI-RealEstate`:
worktree `~/eko-calculator` (rama `feat/calculator` desde `6f6ee2d`), venv
propio (`python3.11`), `node_modules` propio, base
`eko_realestate_test_calculator` en el Postgres compartido (5434).

| Comprobación | Resultado |
|---|---|
| `alembic upgrade head` | ✅ hasta `054_content_metrics`; `alembic heads` = 1 cabeza |
| `pytest -q -p no:cacheprovider --cov=app` | ✅ **1659 passed, 0 failed**, 39 warnings, **239 s**; cobertura **81 %** (10.785 líneas, 2.001 sin cubrir) |
| `ruff check app tests --output-format=concise` | ✅ `All checks passed!` |
| `pytest worker/tests` (paso aparte de CI) | ⚠️ `collected 0 items` en este checkout |
| `npx tsc --noEmit` | ✅ limpio |
| `npx vitest run` | ✅ **17 ficheros, 268/268** en 0,8 s |
| `npx next lint` | ✅ 0 avisos |
| `npx next build` | ✅ `/fall`, `/contact`, `/` como **○ (Static)** |
| Prerender `<main>` / «Checking session» | `fall` 1/0 · `contact` 1/0 · `index` 1/0 ✅ |
| **Re-medido en Fase 0 @ `8ee1f31`** | backend **1659/1659**, cobertura **82 %** (1.979 sin cubrir), ruff ✅ · tsc ✅ · vitest **268/268** · lint ✅ · build ✅ · prerender 1/0 ×3 ✅ |

**Referencia de verde anterior** (PLAN.md de la rama anterior): 1565 backend /
261 frontend, cobertura 81%. El frontend ya está en 268 (+7 de `/fall`).

### 2.1.b Backend — cobertura de lo que se va a tocar

De la salida real de `--cov` (fichero de salida completo:
`…/tasks/b8h121lv8.output`): `landing_analytics.py` 97 %, `lead_events.py`
100 %, `llm.py` 94 %, y **`lead_notify.py` 53 %** — el aviso por correo es la
pieza **menos probada** de las que la Fase 3b modifica; el test nuevo del cuerpo
del correo no es opcional. Referencia de verde de la rama anterior: 1565; hoy
1659 (+94 de `/fall` y la red de seguridad de Groq).

### 2.2 Hallazgos con evidencia

**BLOQUEANTES** (impiden cumplir el objetivo tal como está escrito):

- **B-1 — No existe respuesta automática para un lead web.**
  `backend/app/api/v1/public.py:431-447`: tras `capture_lead` el endpoint solo
  llama a `send_new_lead_notice(...)` (correo a la agencia). `handle_inbound_message`
  —el único camino que llega al LLM— lo invocan `webhooks/sms.py:98`,
  `webhooks/whatsapp.py:153`, `webhooks/email.py:130` y `leads.py:402` (envío
  manual); **ninguno es el formulario**. `grep -rn "handle_inbound_message(" backend/app`
  lo confirma. Consecuencia: la decisión 4 («entra en la cadena con contexto») no
  tiene cadena en la que entrar. Lo que sí hay: el aviso a Natalia
  (`services/lead_notify.py:41`), el mensaje en el Inbox (`capture.py:343-350`) y
  la ficha del lead (`LeadDetail.tsx`). **La v1 lleva el contexto por esos tres.**
- **B-2 — El cálculo no tiene por dónde viajar al servidor.**
  `PublicLeadIn` (`public.py:279-313`) tiene campos fijos; `CapturePayload`
  (`frontend/lib/api.ts:1297-1310`) también; `FormSubmission`
  (`capture.py:109-120`) también. Y `ATTRIBUTION_KEYS` (`capture.py:67-84`) es
  una whitelist con `assert MAX_ATTRIBUTION_KEYS == len(...)` cuyo comentario
  dice que meter ahí otra cosa es «usar la columna como cuaderno». Hace falta
  un campo propio de punta a punta (Fase 3).

**IMPORTANTES:**

- **I-1 — La receta de tests documentada no corre desde una instalación limpia.**
  `backend/requirements.txt:46-48` solo lleva `pytest` y `pytest-asyncio`;
  `pytest-cov` y `ruff` no están. Con el venv nuevo: `pytest: error: unrecognized
  arguments: --cov=app` y `No module named ruff`. CI los instala a mano
  (`.github/workflows/*.yml:67: pip install ruff pytest pytest-asyncio`) y
  **CI tampoco mide cobertura**. El venv del árbol principal los tenía porque
  alguien los instaló sin anotarlo. *Backlog: `requirements-dev.txt`.*
- **I-2 — `CLAUDE.md:177` miente:** «No `conftest.py` central». Existe
  `backend/tests/conftest.py` (44 líneas, 2 fixtures autouse, y **pone
  `GROQ_API_KEY=""` incondicionalmente**). Quien siga el CLAUDE.md escribe
  fixtures que ya existen. *Backlog: corregir la línea.*
- **I-3 — `/analytics` no distingue páginas.** `services/landing_analytics.py`
  no agrupa por `landing_variant` ni por `landing_path` (grep: 0 coincidencias
  de `variant`). `/fall` y `/calculator` serán una sola línea en el embudo; solo
  se separan en la atribución del lead. *Backlog.*
- **I-4 — Playwright webkit no está instalado en este Mac.**
  `~/Library/Caches/ms-playwright/` tiene `chromium-1234` y
  `chromium_headless_shell-1234`, **no webkit**. La norma de memoria («sin
  iPhone, Playwright webkit») no se puede seguir sin `npx playwright install
  webkit` (~100 MB). La Fase 7 usa chromium con emulación de iPhone y deja
  webkit como opcional.

**MENORES:**

- **M-1 — `RESEND_FROM` nombra a la plataforma:** `backend/app/config.py:130`
  → `"Eko AI Realtors <noreply@realtors.ekoaiautomation.com>"`. Hoy solo llega a
  Natalia. El día que un correo automático salga hacia un **lead** de Denver
  Home Story, esa es una fuga de identidad idéntica a la que
  `publicMetadata.test.ts` prohíbe en la web. Precondición de la Fase 10.
- **M-2 — `LandingTracker.SECTIONS` está fijo** a las cuatro secciones de la
  landing (`LandingTracker.tsx:42`). En otra página el observador no encuentra
  los ids y **no mide secciones sin avisar**. Fase 5.
- **M-3 — `${PIPESTATUS[0]}` no existe en zsh.** Las recetas con `| tail` de
  `PLAN.md`/`docs/` pierden el código de salida; hoy me devolvió `rc=` vacío. En
  zsh es `${pipestatus[1]}`; mejor no encadenar cuando importa el rc.
- **M-4 — Sin lead real todavía:** `select count(*) from leads` = 0 en
  producción y el aviso va a `booking_contact_email` = **Natalia**. Ninguna
  prueba de extremo a extremo se hace contra producción (decisión 7.8).
- **M-5 (histórico, cerrado por la otra sesión en `6f6ee2d`):** `/fall` estaba
  en `hosts.ts:PUBLIC_PATHS` y no en la Set de `AuthGuard`; prerenderizaba
  «Checking session…» sin `<main>`. Ahora `AuthGuard.tsx:33 isUngated()` **deriva**
  de `isPublicPath`, y `hostRouting.test.ts:254` recorre `PUBLIC_PATHS`. Para
  `/calculator` **basta con una lista**.

### 2.3 Lo que ya existe y se reutiliza (no reescribir)

| Pieza | Dónde | Qué da |
|---|---|---|
| Formulario de captura con prop `variant` | `frontend/components/landing/ConsultForm.tsx:347` | Endpoint, honeypot, Turnstile y **una sola cadena de consentimiento TCPA**. Prohibido copiarlo (docstring `:3-15`) |
| Tracker con prop `variant` | `frontend/components/landing/LandingTracker.tsx:44` | `page_view`, `form_*`, scroll, secciones |
| Lista pública única | `frontend/lib/hosts.ts:89` + `AuthGuard.tsx:33` | Añadir `"/calculator"` en **un** sitio |
| Patrón de metadata para página cliente | `frontend/app/contact/layout.tsx` | `robots:{index:true}`, sin «eko», `appleWebApp`, canonical |
| Patrón de pie legal | `frontend/app/fall/page.tsx:190-203` | `LANDING.address` · «Licensed in Colorado» · «Equal Housing Opportunity» solo si hay `brokerage` |
| Tokens de marca | `frontend/tailwind.config.ts` (`ln-*`) | Sin CSS nuevo |
| i18n + paridad | `frontend/lib/i18n.tsx` (EN `:18-889`, ES `:891-1730`) + `i18nParity.test.ts` | Toda cadena en EN **y** ES, sangría de 2 espacios |
| Selector de idioma | `frontend/components/ui/LanguageSwitcher.tsx` (usado en `Landing.tsx:136` y `/contact`) | Un hispanohablante **elige** ES; no hay `navigator.language` |
| Filtro Fair Housing | `backend/app/services/fair_housing.py:157 find_violations(text, language)` | Se corre sobre la copia EN y ES |
| Migración de columna en `leads` | `backend/migrations/versions/20260904_1500_deal_columns.py:40-54` | Plantilla `op.add_column` / `drop_column` |
| Aviso a la agencia | `backend/app/services/lead_notify.py:79-116` (`_line()`) | Añadir líneas al correo |
| Ficha del lead | `frontend/components/leads/LeadDetail.tsx:226-248` | Patrón de bloque que desaparece si no hay datos |
| Serialización del lead | `backend/app/api/v1/leads.py:160-251` (`LeadOut`, `_attribution_of`) | Dónde exponer la instantánea |

---

## 3. Comandos del proyecto (verificados en este worktree)

Todos desde `~/eko-calculator`. **Antes de cualquier comando de backend,
exporta el entorno de ESTA base** — nunca `eko_realestate_test` ni
`eko_realestate`, que son de otras sesiones. **Nunca exportes `APP_DB_PASSWORD`**
(el rol `eko_app` es del clúster; `alembic` le cambiaría la contraseña a todas
las bases). **Nunca `docker compose up/down/restart`** (los `container_name` son
fijos y la otra sesión usa `eko-realestate-db`).

```bash
# ── entorno backend (cada shell nuevo) ──────────────────────────────────
cd ~/eko-calculator/backend
PW=$(docker exec eko-realestate-db printenv POSTGRES_PASSWORD)
export DATABASE_URL="postgresql+asyncpg://eko:${PW}@localhost:5434/eko_realestate_test_calculator"
export DATABASE_URL_APP="postgresql+asyncpg://eko_app:eko_app_local_pass@localhost:5434/eko_realestate_test_calculator"
export WHATSAPP_ENABLED=true PYTHONDONTWRITEBYTECODE=1

# ── backend ─────────────────────────────────────────────────────────────
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m alembic heads                      # debe listar UNA cabeza
./.venv/bin/python -m pytest -q -p no:cacheprovider --cov=app --cov-report=term
./.venv/bin/python -m ruff check app tests --output-format=concise

# ── frontend ────────────────────────────────────────────────────────────
cd ~/eko-calculator/frontend
npx tsc --noEmit
npx vitest run
npx next lint
npx next build
# prerender: ninguna página pública debe salir como spinner
for p in calculator fall contact index; do f=".next/server/app/$p.html"; \
  printf "%-10s <main>=%s Checking=%s\n" "$p" "$(grep -c '<main' "$f")" "$(grep -c 'Checking session' "$f")"; done

# ── servidor local para la verificación visual (puerto propio) ───────────
npx next start -p 3010
```

Notas: `pytest-cov` y `ruff` ya están instalados **en este venv** (no en
`requirements.txt`, hallazgo I-1). No encadenes `| tail` a un comando cuyo `rc`
necesites (M-3). Si una migración nueva rompe la base, **recrea solo esta**:
`docker exec eko-realestate-db psql -U eko -d postgres -c "DROP DATABASE IF EXISTS eko_realestate_test_calculator WITH (FORCE)" -c "CREATE DATABASE eko_realestate_test_calculator OWNER eko"`.

**Definición de «terminado» de cada fase = sus comandos en verde + commit.**
Commits: convencionales con ámbito (`feat(landing): …`, `feat(db): …`,
`feat(api): …`, `test(…)`), en español como el resto de la rama, terminados con
la atribución de sesión vigente. **No tocar `CHANGELOG.md`, `PROJECT_STATUS.md`
ni `frontend/lib/version.ts` hasta la Fase 8** (son los tres ficheros de
conflicto con la otra rama).

---

## 4. Fases

Orden: primero lo que no depende de nada (la aritmética), después el esquema y
la API, después la página, al final versión y despliegue. Cada fase cabe en
implementar → validar → commit.

### Fase 0 — Aislamiento y estado base

**Objetivo:** el entorno existe, está aislado y reproduce los números de 2.1.

- Verificar: `git -C ~/eko-calculator log --oneline -1` = `6f6ee2d`;
  `git worktree list` muestra `~/eko-calculator [feat/calculator]`; existen
  `backend/.venv` y `frontend/node_modules`.
- Copiar este plan a `~/eko-calculator/PLAN.md` (sustituye al de la rama
  anterior; es la convención del repo) y commitear: `docs(plan): el plan de /calculator`.
- Correr los comandos de §3 y anotar en `PLAN.md` §2.1 los números obtenidos.
  Si difieren de los míos, **anótalo, no lo arregles**: es un hallazgo.
- Avisar a la sesión par (`Eko Ai Realtors`) por `SendMessage` de que la
  ejecución empieza: worktree, base de tests, versión 0.81.0 reservada,
  migración 055 confirmada.

**Terminado:** los cuatro bloques de §3 en verde; `PLAN.md` commiteado.

---

### Fase 1 — La aritmética en TypeScript, contra el PDF

**Objetivo:** `frontend/lib/calculator.ts` reproduce los números de Jeff y
despeja el precio desde la renta; sin React, sin DOM.

**Archivos:** `frontend/lib/calculator.ts` (nuevo),
`frontend/lib/__tests__/calculator.test.ts` (nuevo),
`backend/tests/fixtures/calculator_golden.json` (nuevo — **compartido con la
Fase 2**; vitest lo lee con `readFileSync`, como hace `landing.test.ts`).

**Contrato (`calculator.ts`):**

```ts
export type Credit = "excellent" | "good" | "fair";
export interface Inputs { rent: number; savings: number; credit: Credit }
export interface Assumptions {
  rate: number;              // anual, 0.0671
  termMonths: number;        // 360
  taxRate: number;           // 0.0052 del valor/año
  insuranceRate: number;     // 0.0070 del valor/año
  maintenanceRate: number;   // 0.010 del valor/año — SOLO en la comparación
  hoaMonthly: number;        // 0
  closingRate: number;       // 0.015 del precio
  sellingRate: number;       // 0.04 del valor futuro
  minDown: number;           // 0.03
  pmi: Record<Credit, number>;        // anual sobre el préstamo, solo si LTV > 0.80
  rateSpread: Record<Credit, number>; // se suma a `rate`
  appreciation: number;      // 0.02/año
  rentGrowth: number;        // 0.02/año
  years: number;             // 5
  priceFloor: number;        // 150_000
}
export const DEFAULTS: Assumptions;   // cada valor con comentario: fuente + fecha
export const SOURCES: Record<keyof Assumptions, { label: string; url: string; asOf: string }>;

export function monthlyPI(loan: number, annualRate: number, termMonths: number): number;
export function balanceAfter(loan: number, annualRate: number, termMonths: number, monthsPaid: number): number;
export function futureValue(price: number, annualRate: number, years: number): number;

export interface Monthly { pi: number; tax: number; insurance: number; pmi: number; hoa: number; total: number }
export function monthlyFor(price: number, inputs: Inputs, a: Assumptions): Monthly & { loan: number; down: number; closing: number };

export type CappedBy = "rent" | "savings" | "floor";
export interface PriceResult { price: number; loan: number; down: number; closing: number; monthly: Monthly; cappedBy: CappedBy }
export function solvePrice(inputs: Inputs, a: Assumptions): PriceResult;

export interface YearRow { year: number; buyMonthly: number; rentMonthly: number }
export interface Comparison {
  years: number; appreciation: number; amortization: number; cashflowDiff: number;
  closing: number; selling: number; net: number; buyTotal: number; rentTotal: number;
  rows: YearRow[];               // años 1..years
  crossoverYear: number | null;  // primer horizonte 1..10 con net > 0
}
export function compare(inputs: Inputs, a: Assumptions, price: number): Comparison;
```

**Reglas del cálculo (escríbelas tal cual):**
- `monthlyPI`: `r = annualRate/12`; si `r === 0` → `loan/termMonths`; si
  `loan <= 0` → `0`; si no → `loan·r/(1−(1+r)^−n)`.
- `balanceAfter`: `loan·(1+r)^k − M·((1+r)^k − 1)/r` con `M = monthlyPI`; con
  `r === 0` → `loan − M·k`; nunca negativo.
- `monthlyFor(V)`: `closing = a.closingRate·V`; `down = clamp(savings − closing, 0, V)`;
  `loan = V − down`; `ltv = V > 0 ? loan/V : 0`; `rate = a.rate + a.rateSpread[credit]`;
  `pi = monthlyPI(loan, rate, term)`; `tax = V·taxRate/12`; `insurance = V·insuranceRate/12`;
  `pmi = ltv > 0.80 ? loan·a.pmi[credit]/12 : 0`; `hoa = a.hoaMonthly`;
  `total = pi + tax + insurance + pmi + hoa`. **Sin mantenimiento aquí**: un
  prestamista no lo cuenta para cualificar, y meterlo daría un número que no se
  parece al que le dará su banco.
- `solvePrice`: bisección de `V` en `[0, UPPER]` con `UPPER = 5_000_000` hasta
  `|monthlyFor(V).total − rent| < 0.5` o 80 iteraciones → `vRent`.
  **Antes de iterar**: si `monthlyFor(UPPER).total < rent`, no hay solución
  dentro del rango → `vRent = UPPER` (documentado como tope, y la página lo
  enseña como «$5,000,000+»). `total(V)` es monótona creciente (cada término es
  no decreciente en V; el tope de `down` hace `loan` no decreciente). Suelo de entrada:
  `vSavings = savings / (a.minDown + a.closingRate)` (la entrada mínima y el
  cierre salen del mismo ahorro). `price = min(vRent, vSavings)`;
  `cappedBy = price === vRent ? "rent" : "savings"`; si `price < a.priceFloor`
  → `cappedBy = "floor"` (el precio se devuelve igual, la página decide qué
  enseñar). Redondeo **solo en la vista** (a $1.000); el resultado lleva el valor
  crudo.
- `compare`: para `y = 1..a.years`, `value_y = price·(1+appreciation)^(y−1)`;
  compra mensual del año y = `pi + value_y·(taxRate+insuranceRate+maintenanceRate)/12 + pmi_y + hoa`,
  donde `pmi_y` se cobra mientras `balanceAfter(loan, rate, term, 12·(y−1))/price > 0.80`;
  alquiler mensual del año y = `rent·(1+rentGrowth)^(y−1)` (sin seguro de
  inquilino: conservador **contra** comprar). `buyTotal = Σ 12·compra_y`;
  `rentTotal = Σ 12·alquiler_y`; `cashflowDiff = rentTotal − buyTotal`;
  `closing = closingRate·price`; `valueN = futureValue(price, appreciation, years)`;
  `selling = sellingRate·valueN`; `appreciation = valueN − price`;
  `amortization = loan − balanceAfter(loan, rate, term, 12·years)`;
  `net = appreciation + amortization + cashflowDiff − closing − selling`.
  `crossoverYear`: menor `h ∈ 1..10` con `net(h) > 0`, si no `null`.

**Valores por defecto y sus fuentes (van en `DEFAULTS` + `SOURCES`, no en
comentarios sueltos):**

| Supuesto | Valor | Fuente (fecha) |
|---|---|---|
| `rate` | **0.0671** | Freddie Mac PMMS vía FRED `MORTGAGE30US`, dato del **2026-09-03** (https://fred.stlouisfed.org/series/MORTGAGE30US) |
| `taxRate` | **0.0052** | Tasa efectiva residencial en Denver 0,48–0,55% del valor de mercado (https://www.virtuance.com/blog/denver-property-tax-rates/ · https://propertytaxrates.org/blog/colorado-property-tax-guide-2026), sep-2026 |
| `insuranceRate` | **0.0070** | Prima media en Colorado $3.200–3.800/año sobre ~$450k (https://www.theinsuranceloft.com/how-much-is-homeowners-insurance-in-colorado-2026-costs · https://www.moneygeek.com/insurance/homeowners/average-cost-home-insurance-colorado/); Denver cotiza por debajo. Etiqueta: *estimate* |
| `maintenanceRate` | **0.010** | Regla de pulgar del 1%; etiquetada como tal. Cruce: la hoja de Jeff agrupa imp.+seg.+mant. en 1,887%/año, y 0,52+0,70+0,67 ≈ lo mismo |
| `hoaMonthly` | **0** | Editable en la página |
| `closingRate` | **0.015** | Hoja de Jeff: $12.000 sobre $800.000 |
| `sellingRate` | **0.04** | Hoja de Jeff (decisión 7.5 si el dueño prefiere 5–6%) |
| `minDown` | **0.03** | Convencional 97% LTV; FHA 3,5% (https://themortgagereports.com/21489/how-to-buy-a-home-conventional-loan-mortgage-rates-guidelines) |
| `pmi` | excellent **0.0045** · good **0.0080** · fair **0.0130** | Rangos 2026 por crédito con 5% de entrada (https://www.altgage.com/blog/how-much-is-pmi · https://www.fairway.com/articles/pmi-on-a-conventional-loan-your-questions-answered). Etiqueta: *illustrative* |
| `rateSpread` | excellent **0** · good **+0.0025** · fair **+0.0075** | ⚠️ **Sin fuente** — decisión 7.4. Etiqueta obligatoria: *illustrative* |
| `appreciation` | **0.02** | Decisión 7.2. Contexto: Case-Shiller Denver **−1,8% interanual** (may-2026, https://fred.stlouisfed.org/series/DNXRSA); Jeff usa 4,94% |
| `rentGrowth` | **0.02** | Decisión 7.3. Contexto: rentas en Denver **−1,5% a −3%** interanual en 2026 (https://www.zillow.com/rental-manager/market-trends/denver-co/ · https://www.zumper.com/rent-research/denver-co); Jeff usa 2,734% |
| `years` | **5** | Jeff usa 9; 5 es el horizonte real de un primer comprador y el caso más duro |
| `priceFloor` | **150_000** | Constante de UX, no de mercado (decisión 7.6) |

**Tests (`calculator.test.ts`) — los valores esperados se escriben a mano en el
fixture, nunca se generan con el propio código:**

`calculator_golden.json`:
```json
{
  "jeff": {
    "price": 800000, "loan": 720000, "rate": 0.0675, "term": 360, "years": 9,
    "appreciation_displayed": 0.0494, "closing": 12000, "selling_rate": 0.04,
    "expect": { "pi": 4670, "balance_after_108": 628230, "value_after_9": 1234407,
                "appreciation_gain": 434407, "amortization_gain": 91770, "selling_cost": 49376 }
  },
  "hand": {
    "pi_zero_rate": { "loan": 120000, "rate": 0, "term": 360, "expect": 333.33 },
    "balance_at_end_is_zero": { "loan": 100000, "rate": 0.06, "term": 360 },
    "balance_at_start_is_loan": { "loan": 100000, "rate": 0.06, "term": 360 },
    "rent_total_flat": { "rent": 1000, "growth": 0, "years": 5, "expect": 60000 },
    "future_value_two_years": { "price": 100000, "rate": 0.10, "years": 2, "expect": 121000 }
  }
}
```
Casos:
1. `monthlyPI(720000, .0675, 360)` dentro de **±1** de 4670.
2. `balanceAfter(…,108)` dentro de **±100** de 628.230 (Jeff redondea la tasa).
3. `futureValue(800000, .0494, 9)` dentro de **±400** de 1.234.407 (la tasa
   impresa «4,94%» es 4,9376% redondeada: `(1234407/800000)^(1/9)`).
4. La cascada de Jeff: `appreciation_gain` ±400, `amortization_gain` ±100,
   `selling_cost` ±20.
5. Los cinco casos «hand» con tolerancia ±0,01 (o exacta donde sea entero).
6. `solvePrice({rent:3000, savings:60000, credit:"excellent"}, DEFAULTS)`:
   `cappedBy === "rent"` y `monthlyFor(price).total` dentro de ±1 de 3000.
7. Monotonía: `solvePrice(rent 4000).price > solvePrice(rent 3000).price`;
   `credit:"fair"` da precio **menor** que `"excellent"` a igual renta y ahorro.
8. `savings: 0` → `cappedBy === "floor"`. `savings: 10_000_000` → `down === price`,
   `loan === 0`, `monthly.pi === 0`, `monthly.pmi === 0`.
9. `compare` con `{...DEFAULTS, appreciation: 0, rentGrowth: 0, maintenanceRate: 0, sellingRate: 0, closingRate: 0, years: 1}`,
   entradas `{rent: 3000, savings: 200_000, credit: "excellent"}` (ahorro ≥ 20 %
   para que no haya PMI que caiga a mitad de horizonte) y
   `price = solvePrice(...).price` → `rows[0].buyMonthly − rows[0].rentMonthly`
   dentro de **±1 de 0** (el precio se despejó justo para eso) **y**
   `cashflowDiff` dentro de ±12 de 0 **y** `net` dentro de ±12 de `amortization`.
10. `crossoverYear` es `null` con `appreciation: −0.05`. Con `DEFAULTS` y
    `{rent:3000, savings:60000, credit:"excellent"}`, **anota el horizonte que
    sale** y fíjalo como aserción de regresión (`toBe(<n>)` o `toBeNull()`); no
    lo fuerces a ≤ 5 — es información de producto (§6).
11. Tope superior: `solvePrice({rent: 50_000, savings: 0, credit:"excellent"}, {...DEFAULTS, minDown: 0, closingRate: 0})`
    → `price === 5_000_000` y `cappedBy === "rent"` (la bisección devuelve el
    tope, no un valor a medio converger).

**Verificación de que el test ve** (obligatoria, se anota en el commit):
cambiar `−` por `+` en la fórmula de `net` → deben ponerse rojos los casos 4/9;
restaurar y confirmar verde.

**Terminado:** `npx vitest run` verde con ≥ 13 casos nuevos; `tsc` limpio; la
mutación se vio en rojo. Al cerrar, anota en el fixture `"cross": [...]` tres
tuplas `{rent, savings, credit, price}` **calculadas por este código** — son
**anclas de paridad** para la Fase 2 (que Python dé lo mismo), **no pruebas de
corrección**: lo correcto lo prueban los casos 1-5 con valores a mano. Commit `feat(landing): la aritmetica de /calculator, contra la hoja de Jeff`.

---

### Fase 2 — La misma aritmética en Python, con los mismos fixtures

**Objetivo:** `backend/app/services/calculator.py` da los mismos números que la
Fase 1 leyendo **el mismo** `calculator_golden.json`, para que las dos
implementaciones no puedan separarse en silencio.

**Archivos:** `backend/app/services/calculator.py` (nuevo),
`backend/tests/test_calculator.py` (nuevo).

**Contrato:** mismas funciones en snake_case (`monthly_pi`, `balance_after`,
`future_value`, `monthly_for`, `solve_price`, `compare`), `DEFAULTS` como
`dict` con los **mismos valores** que TS, y:

```python
def build_snapshot(inputs: dict, overrides: dict | None, *, lang: str | None) -> dict:
    """Recalcula en el servidor y devuelve lo que se guarda con el lead."""
    # → {"version": 1, "computed_at": iso-utc, "lang": "en"|"es"|None,
    #    "inputs": {"rent":..,"savings":..,"credit":..},
    #    "assumptions": {…DEFAULTS con overrides aplicados…},
    #    "result": {"price": int, "capped_by": str, "loan": int, "down": int,
    #               "monthly": {"pi","tax","insurance","pmi","hoa","total"} (int),
    #               "net_5y": int, "crossover_year": int|None}}
def summary_line(snapshot: dict) -> str:
    """Una línea para el Inbox y el aviso, en inglés:
    'Used the rent-vs-buy calculator: rent $2,100/mo, savings $15,000, good credit → up to ~$310,000 (5-yr net vs renting: +$18,600).'"""
```

`overrides` admite solo `appreciation`, `rent_growth`, `rate`, `hoa_monthly`
(lo que la página deja mover); cualquier otra clave se ignora.

**Tests:** los mismos 10 casos de la Fase 1 leyendo el fixture (**el test debe
fallar si el fichero no existe o está vacío**: `assert golden["jeff"]`), más
`build_snapshot` con inputs válidos → claves exactas de arriba, enteros, y
`summary_line` contiene el precio con separador de miles. **Paridad cruzada**:
un test que lee `golden["cross"]` (las tres tuplas que la Fase 1 anotó) y exige
`solve_price(...)["price"]` dentro de ±1. Son anclas de **paridad** TS↔Python,
no de corrección — si un día cambia el modelo, cambian las dos implementaciones
y el fixture a la vez.

**Terminado:** `pytest tests/test_calculator.py` verde; `ruff` limpio. Commit
`feat(api): la aritmetica de /calculator en el servidor, con los fixtures de la web`.

---

### Fase 3a — Migración 055: la columna `leads.calculator_snapshot` **[CRÍTICA]**

*Por qué crítica: es DDL sobre `leads`, la tabla por la que entra todo lead en
producción, y el orden de despliegue con la otra rama exige que sea inocua para
código que no la conoce.*

**Objetivo:** existe una columna JSONB **nullable, sin default**, y el API la
expone.

**Archivos:**
- `backend/migrations/versions/<YYYYMMDD_HHMM>_calculator_snapshot.py` (generar
  con `alembic revision -m "calculator_snapshot"` para que el nombre siga la
  plantilla `alembic.ini:6`; luego **editar a mano**):
  `revision = "055_calculator_snapshot"` (23 caracteres ≤ 30,
  `test_migration_ids.py:20`), `down_revision = "054_content_metrics"`.
  `upgrade`: `op.add_column("leads", sa.Column("calculator_snapshot", postgresql.JSONB(), nullable=True))`.
  `downgrade`: `op.drop_column`. Sin RLS nueva (la política de `leads` cubre la
  columna); sin `GRANT` nuevo (los permisos son por tabla). Docstring en el
  estilo del repo: qué es, por qué nullable (un `INSERT` que no la mencione
  sigue siendo válido: petición explícita de la otra sesión para poder revertir
  su código con esta migración aplicada).
- `backend/app/models/lead.py`: junto a `meta` (`:138`),
  `calculator_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)`
  (importar `JSONB` de `sqlalchemy.dialects.postgresql`, como `models/landing.py`).
- `backend/app/api/v1/leads.py`: `LeadOut.calculator: dict | None = None`
  (junto a `attribution:` `:204`); en el mapeo (`:251`)
  `out.calculator = row.calculator_snapshot`.
- `frontend/lib/api.ts:64`: `calculator?: CalculatorSnapshot | null` + el tipo.
- `frontend/components/leads/LeadDetail.tsx`: tras el bloque de atribución
  (`:226-248`), un bloque «Calculator» con el mismo patrón (desaparece si es
  `null`): renta, ahorro, crédito, precio, cuota total, neto a 5 años,
  `capped_by`. Claves i18n `lead.calculator.*` en EN y ES.

**Tests:** `alembic upgrade head` + `alembic heads` = 1; `alembic downgrade -1`
+ `upgrade head` vuelven limpios; `test_migration_ids.py` verde; dos casos
nuevos en **`backend/tests/test_lead_attribution_is_readable.py`** (el fichero
que ya prueba `LeadOut`/`_attribution_of`, con su mismo patrón): un lead con
`calculator_snapshot={"result":{"price":310000}}` leído por
`GET /api/v1/leads/{id}` → `calculator.result.price == 310000`; y un lead sin
instantánea → `calculator is None`. `vitest` + `tsc` verdes.

**Terminado:** suite backend completa verde (no solo el fichero nuevo:
`test_text_limits`, `test_tenant_isolation` y los barridos AST inventarían
`leads`). Commit `feat(db): 055 calculator_snapshot, la columna que guarda lo que el visitante calculo`.
**Avisar a la sesión par** de que la 055 existe.

---

### Fase 3b — El cálculo viaja con el lead y llega a Natalia

**Objetivo:** un POST a `/api/v1/public/leads` con `calculator` recalcula en el
servidor, guarda la instantánea, la pone en el mensaje del Inbox y en el aviso
por correo.

**Archivos y cambios:**
- `backend/app/api/v1/public.py`: junto a `PublicLeadIn` (`:279`):
  ```python
  class CalculatorIn(BaseModel, extra="forbid"):
      rent: float = Field(gt=0, le=50_000)
      savings: float = Field(ge=0, le=5_000_000)
      credit: Literal["excellent", "good", "fair"]
      appreciation: float | None = Field(default=None, ge=-0.10, le=0.15)
      rent_growth: float | None = Field(default=None, ge=-0.10, le=0.15)
      rate: float | None = Field(default=None, ge=0.0, le=0.20)
      hoa_monthly: float | None = Field(default=None, ge=0, le=5_000)
      lang: Literal["en", "es"] | None = None
  ```
  `PublicLeadIn.calculator: CalculatorIn | None = None`. En `capture()` (`:361`)
  pasar `calculator=body.calculator.model_dump() if body.calculator else None`
  a `FormSubmission`.
- `backend/app/services/capture.py`: `FormSubmission.calculator: dict | None = None`
  (`:109-120`). En `capture_lead` (`:261`): si `sub.calculator`,
  `snapshot = build_snapshot(inputs, overrides, lang=…)`;
  `lead.calculator_snapshot = snapshot` (**la última gana**: quien recalcula y
  reenvía actualiza). `_summary(message, name)` (`:222`) pasa a
  `_summary(message, name, snapshot)`: si no hay mensaje y sí instantánea →
  `summary_line(snapshot)`; si hay mensaje **y** instantánea → mensaje + `" — " + summary_line(...)`.
  Es lo que el clasificador y Natalia leen.
- `backend/app/services/lead_notify.py` (`:79-116`): tras `Came from`, añadir
  `_line("Calculator", summary_line(lead.calculator_snapshot))` cuando exista.
- `frontend/lib/api.ts`: `CapturePayload.calculator?: CalculatorPayload` (mismas
  claves que `CalculatorIn`, snake_case).
- `frontend/components/landing/ConsultForm.tsx`: prop nuevo
  `calculator?: CalculatorPayload` en `ConsultForm` y `ConsultFormInner`; se
  incluye tal cual en `submitPublicLead({...})` (`:137-149`). **Nada más cambia
  en el formulario**: ni la copia, ni el consentimiento, ni el endpoint.

**Casos borde que cubren los tests** (`tests/test_public_capture.py`, patrón
`_post` + `_seed` del propio fichero):
1. POST con `calculator` válido → 202; el lead tiene `calculator_snapshot` con
   `result.price` entero y `inputs` iguales a lo enviado; el mensaje del Inbox
   contiene `"rent-vs-buy calculator"`.
2. POST **sin** `calculator` → 202 y `calculator_snapshot IS NULL` (nada cambia
   para `/` y `/fall`).
3. `calculator` con `rent: 0` → 422 (pydantic), **no se escribe lead** (misma
   promesa que «a bad batch writes nothing»).
4. `calculator` con clave extra (`{"foo": 1}`) → 422 (`extra="forbid"`).
5. `calculator` con `rate: 0.50` → 422.
6. El cliente manda `savings: 10_000_000` (dentro del tope) → 202 y
   `capped_by == "rent"` (el servidor recalculó; no se fía del navegador).
7. Un segundo POST del mismo correo con otra renta → la instantánea es la
   **nueva** (última gana) y el mensaje **no** se deduplica (contenido distinto).
8. `test_new_lead_notice.py`: el cuerpo del correo contiene `Calculator:` cuando
   hay instantánea y no lo contiene cuando no la hay.

Los barridos AST (`test_opt_out_is_absolute.py:252-290`) no se disparan: no se
añade ninguna función que envíe.

**Terminado:** suite backend completa verde; `ruff`; `tsc` + `vitest`. Commit
`feat(api): el calculo viaja con el lead y llega al Inbox y al aviso`.

---

### Fase 4 — El evento `calculator_result`

**Objetivo:** el embudo distingue «vio la página» de «llegó a ver su número».

**Archivos:**
- `backend/app/models/landing.py:35` `LANDING_EVENT_TYPES` += `"calculator_result"`.
- `frontend/lib/track.ts:32` `EventName` += `"calculator_result"`; `IMMEDIATE`
  (`:45`) += `"calculator_result"` (quien ve el número puede irse en el acto).
- `fold_events` (`landing_analytics.py:243`) **no cambia**: el evento se guarda
  como fila cruda en `landing_events` (`new_events`, `:317`) y se consulta desde
  ahí; no hay columna de sesión para él (backlog I-3).
- **Sin migración**: `landing_events.type` es `Text` (`models/landing.py:144`,
  migración 051 `:158`), no un enum de Postgres; la validación es solo la del
  `field_validator` de `LandingEventIn` (`public.py:493-498`). Verificado.

**Meta del evento** (≤ 5 claves, valores `int` o `str ≤ 120`, `public.py:502-527`):
`{ price_k: Math.round(price/1000), capped: cappedBy, credit }`.
**Cuándo:** una vez por carga de página, en el primer resultado válido con
`cappedBy !== "floor"`. Nunca en cada pulsación.

**Tests:** `tests/test_public_landing_events.py`: un batch con
`{"t":"calculator_result","meta":{"price_k":310,"capped":"rent","credit":"good"}}`
→ 204 y una fila en `landing_events` con `type='calculator_result'` y ese meta;
un tipo inventado sigue dando 422 (ya existe, no lo dupliques). Frontend: `tsc`.

**Terminado:** verde. Commit `feat(api): calculator_result, el paso del embudo entre ver y capturar`.

---

### Fase 5 — `LandingTracker` acepta sus secciones

**Objetivo:** el tracker mide secciones en cualquier página pública, no solo en `/`.

**Archivos:**
- `frontend/components/landing/LandingTracker.tsx`: prop
  `sections?: readonly string[]` con default `SECTIONS` (`:42`); el bucle `:105`
  itera el prop. `/fall` y `/` no cambian (usan el default).
- `backend/app/models/landing.py:50` `LANDING_SECTIONS` += `"inputs", "result", "compare"`
  (`fold_events` `:255` descarta lo que no esté en la tupla).

**Tests:** el que ya pruebe `fold_events` con `section_view` (en
`tests/test_landing_analytics.py`) gana un caso con `"result"` aceptada y
`"garbage"` descartada. Si existe un test que fije la longitud de
`LANDING_SECTIONS`, actualízalo con el motivo.

**Terminado:** verde. Commit `feat(landing): LandingTracker acepta sus secciones; las de /calculator en el modelo`.

---

### Fase 6a — La página `/calculator` (sin captura todavía)

**Objetivo:** `www.denverhomestory.com/calculator` existe, se sirve en el
dominio de marca, es indexable, calcula en vivo en EN y ES, y prerenderiza con
`<main>`.

**Archivos:**
- `frontend/lib/hosts.ts:89`: `PUBLIC_PATHS = ["/", "/contact", "/fall", "/calculator"]`.
  *(Una sola lista: `AuthGuard` deriva de ella.)*
- `frontend/app/calculator/layout.tsx` — copia el patrón de
  `app/contact/layout.tsx` **entero** (metadata + viewport). `TITLE = "What could your rent buy in Denver?"`,
  `DESCRIPTION = "Type what you pay in rent, what you have saved and your credit range. See the price you could buy at and what five years of owning versus renting looks like — with every assumption in the open."`,
  `openGraph.type: "website"`, `twitter.card: "summary_large_image"`,
  `robots: { index: true, follow: true }`, `appleWebApp` con `homeScreenName`,
  `alternates.canonical: "/calculator"` bajo `BRAND_URL`. **Ninguna cadena con
  «eko».**
- `frontend/app/calculator/page.tsx` — `"use client"`. Estructura, en este
  orden y con estos `id` (los mide la Fase 5):
  1. `<main className="min-h-screen bg-ln-canvas text-ln-body">` +
     `<LandingTracker variant="calculator" sections={["inputs","result","compare","consult"]} />`
     como hermano de `<main>` (igual que `/fall:215`).
  2. Cabecera: enlace de marca a `/` (patrón `/fall:217-224`), `<LanguageSwitcher />`,
     `<h1>` `t("calculator.title")`, párrafo `t("calculator.intro")`.
  3. `<section id="inputs">`: renta mensual (`<input type="text" inputMode="decimal">`
     con prefijo `$`, `aria-label`), ahorro (ídem), crédito como **tres chips
     de `min-h-[44px]`** (patrón de los chips de `ConsultForm:232-250`), con
     `aria-pressed`. Estado en `useState`; cálculo con `useMemo` sobre
     `solvePrice`/`compare` (Fase 1), **debounce 150 ms** sobre los inputs
     numéricos. Sin botón «Calcular»: el número aparece al escribir.
  4. `<section id="result">`: `t("calculator.result.heading")` («You could buy
     up to» / «Podrías comprar hasta»), el precio redondeado a $1.000
     **en un elemento con `data-testid="calc-price"`** (lo busca la Fase 7) con
     `Intl.NumberFormat(locale, {style:"currency",currency:"USD",maximumFractionDigits:0})`
     (`locale` viene de `useI18n()`), y la línea de tope según `cappedBy`:
     `"rent"` → «at the same monthly cost as your rent»; `"savings"` → «your
     savings set this ceiling: with a 3% down payment and closing costs, this
     is the most they cover»; `"floor"` → **no se enseña precio**, se enseña
     `t("calculator.result.floor")` («At these numbers the estimate falls below
     what Denver homes sell for. Natalia can still help you plan for it.»).
     Debajo, el desglose mensual (P&I, taxes, insurance, PMI si > 0, HOA si > 0,
     total) y `t("calculator.disclaimer")`.
  5. `<section id="compare">`: `t("calculator.compare.heading")` («Five years:
     buying vs. renting»), el `net` grande con signo y color (verde si > 0,
     neutro si ≤ 0 — **nunca ocultar un neto negativo**), la cascada de cinco
     líneas (appreciation, amortization, cash-flow difference, closing costs,
     cost to sell), la tabla de años 1/3/5 (compra mensual vs alquiler mensual),
     `crossoverYear` como frase («Owning pulls ahead in year N» / «At these
     assumptions renting stays cheaper for 10+ years»), y **dos deslizadores**:
     apreciación (0–5%, paso 0,25) y crecimiento del alquiler (0–5%, paso 0,25),
     ambos `<input type="range">` con etiqueta y valor visible.
     Un `<details>` «Assumptions» con: tasa (editable, `inputMode="decimal"`),
     HOA mensual (editable), y en solo lectura impuesto, seguro, mantenimiento,
     cierre, venta, PMI del tramo, entrada mínima — **cada uno con su fuente y
     fecha** desde `SOURCES` (enlace `rel="noopener"`), y la palabra
     *estimate*/*estimado* en cada cifra.
  6. `<section id="consult" className="relative scroll-mt-10 overflow-hidden bg-ln-dark">`
     (misma clase que `Landing.tsx:628`): `t("calculator.cta.heading")` +
     `t("calculator.cta.body")` + **por ahora un placeholder** (`<div id="consult-form" />`);
     el formulario entra en la Fase 6b.
  7. `<footer>`: **copiar** el bloque de `/fall:190-203` (`footerWho`, `legal`).
     No extraer componente (tocaría `/fall`; backlog).
- `frontend/lib/i18n.tsx`: todas las claves `calculator.*` en **EN (`:18-889`)
  y ES (`:891-1730`)**, sangría de 2 espacios, en el mismo orden en ambos. Copia
  ES real, no traducción automática literal («renta» en Denver es *rent*;
  «enganche»/«entrada» → usar **«enganche (down payment)»** la primera vez y
  «enganche» después). La copia del CTA promete **solo lo que existe** (§6):
  EN «Want Natalia to send you options in this range? Leave your email and
  she&rsquo;ll reach out.» / ES «¿Quieres que Natalia te mande opciones en este
  rango? Deja tu correo y ella te escribe.» — nada de «we&rsquo;ll email you the
  breakdown». ESLint `react/no-unescaped-entities`: apóstrofos como `&rsquo;`.
  **Ninguna cadena pública contiene «eko».**
- Registrar el evento de la Fase 4: en un `useEffect` sobre el resultado,
  `getTracker()?.record("calculator_result", {...})` una sola vez (ref booleana).

**Tests:**
- `frontend/lib/__tests__/hostRouting.test.ts`: `/calculator` en el bucle de
  `:73` y en `isPublicPath` (`:181-187`): `/calculator` true, `/calculators`
  false. La guarda de `AuthGuard` (`:254`) lo cubre sola.
- `frontend/lib/__tests__/publicMetadata.test.ts`: tres casos como los de
  `/contact` (`:34-51`) importando `../../app/calculator/layout`: declara
  `title`/`description`/`openGraph.title`/`appleWebApp`; nada con `/eko/i`;
  `robots` `{index:true}`.
- `i18nParity.test.ts` pasa solo (mismas claves EN/ES).
- `backend/tests/test_calculator_copy.py` (nuevo): lee
  `frontend/lib/i18n.tsx`, extrae con regex todas las cadenas cuya clave empieza
  por `"calculator."` y `"lead.calculator."` **en las dos secciones**, exige
  `len(found) >= 30` (un regex que no casa nada no puede dar verde), y para cada
  una `find_violations(text, language) == []` con `language` = `"en"` para las
  de la sección EN y `"es"` para la ES, y `not re.search(r"eko", text, re.I)`.
- Prerender: `next build` → `.next/server/app/calculator.html` con `<main>` = 1
  y «Checking session» = 0.

**Terminado:** los cuatro bloques de §3 verdes + prerender. Commit
`feat(landing): /calculator, la pagina que promete el Short — calcula en vivo, EN y ES`.

---

### Fase 6b — La captura con el cálculo dentro

**Objetivo:** el formulario de `/calculator` envía el cálculo con el lead, y de
punta a punta en local aparece en el Inbox, la ficha y el correo simulado.

**Archivos:** `frontend/app/calculator/page.tsx` — sustituir el placeholder por
`<ConsultForm variant="calculator" calculator={payload} />`, donde `payload` es
`{ rent, savings, credit, appreciation, rent_growth, rate, hoa_monthly, lang }`
(solo las claves que el visitante movió respecto a `DEFAULTS`; las demás
`undefined`), y `lang` = el idioma activo.

**Verificación de extremo a extremo, en local, con salida real (no contra
producción — M-4):**
0. **La base de test recién migrada tiene `booking_contact_email` VACÍO** para
   la org 1 (verificado: `select org_id, booking_contact_email from agent_settings`
   → `1|`). Con eso, `_send_and_record` se va por `lead_notify.py:79-88`
   («nobody was told») y la línea `Calculator:` **nunca aparece** — no es un
   fallo de la Fase 3b. Antes del POST, **en esta base y solo en esta**:
   `docker exec eko-realestate-db psql -U eko -d eko_realestate_test_calculator -c "update agent_settings set booking_contact_email='agency-local@example.com' where org_id=1"`.
1. Backend local con `EMAIL_SIMULATED=true` (default) apuntando a **esta** base
   (mismo `export` de §3): `./.venv/bin/python -m uvicorn app.main:app --port 8021`
   (puerto propio; el compartido 8011 no se toca).
2. **Exportar, luego construir, luego arrancar** — `rewrites()` se hornea en el
   build (`next.config.js:35-43` lee `INTERNAL_API_URL`, default
   `http://backend:8000`): `export INTERNAL_API_URL=http://localhost:8021 && npx next build && npx next start -p 3010`.
   **No edites `next.config.js`.**
3. Con Playwright (script de la Fase 7, misma instalación en el scratchpad)
   rellenar renta 2100, ahorro 15000, crédito «good», correo
   `calc-test@example.com`, enviar.
4. Comprobar en la base: `select calculator_snapshot->'result'->>'price', calculator_snapshot->'inputs' from leads where email='calc-test@example.com'`
   → precio entero y las entradas enviadas. En el log del backend: la línea del
   correo simulado con `Calculator:`. En `/leads/{id}` del panel local
   (`AUTH_ENABLED` apagado en local): el bloque «Calculator».
5. Pegar las tres salidas en el commit.

**Terminado:** lo anterior + suite completa verde. Commit
`feat(landing): el formulario de /calculator manda el calculo con el lead`.

---

### Fase 7 — Móvil de verdad, medido

**Objetivo:** en un viewport de iPhone la cifra y el CTA están **visibles**, no
solo presentes; no hay scroll horizontal; el toque llega a los chips.

**Instalación (una vez, fuera del repo).** `playwright` **no está** en
`frontend/node_modules` (verificado: `npx playwright` ofrecía instalarlo) y el
`chromium-1234` de la caché puede no casar con la versión que se instale. En el
scratchpad:
```bash
cd /private/tmp/claude-501/-Users-enderj/a300d3c2-82cc-4fa4-b600-af2973ddbc79/scratchpad
mkdir -p pw && cd pw && npm init -y >/dev/null && npm i playwright@1.63.0 --no-audit --no-fund
npx playwright install chromium          # descarga el binario que casa con 1.63.0
```
Playwright **chromium** con `devices["iPhone 13"]` (viewport 390×844, UA Safari;
webkit no está — I-4; si el ejecutor prefiere el motor de Safari,
`npx playwright install webkit` son ~100 MB más y requiere permiso explícito
del dueño). Script en `scratchpad/pw/calc-mobile.mjs`, contra
`npx next start -p 3010`:

```js
import { chromium, devices } from "playwright";
const sizes = [
  { name: "iphone13", ...devices["iPhone 13"] },
  { name: "desktop", viewport: { width: 1280, height: 800 } },
];
for (const s of sizes) {
  const { name, ...opts } = s;            // `name` no es opción de newContext
  const browser = await chromium.launch();
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.goto("http://localhost:3010/calculator", { waitUntil: "networkidle" });
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  const iw = await page.evaluate(() => window.innerWidth);
  if (sw > iw) throw new Error(`${s.name}: horizontal overflow ${sw}>${iw}`);
  await page.getByLabel(/rent/i).fill("2100");
  await page.getByLabel(/saved|savings|ahorr/i).fill("15000");
  await page.getByRole("button", { name: /good|bueno/i }).click();
  const price = page.getByTestId("calc-price");
  await price.waitFor();
  await price.scrollIntoViewIfNeeded();
  const box = await price.boundingBox();
  const vh = s.viewport.height;
  if (!box || box.y < 0 || box.y + box.height > vh) throw new Error(`${s.name}: price not fully in viewport ${JSON.stringify(box)}`);
  const email = page.getByLabel(/email|correo/i);
  await email.scrollIntoViewIfNeeded();
  const eb = await email.boundingBox();
  if (!eb || eb.y < 0 || eb.y + eb.height > vh) throw new Error(`${s.name}: email field not in viewport`);
  await page.screenshot({ path: `calc-${s.name}.png`, fullPage: true });
  console.log(`${s.name}: ok price=${await price.innerText()}`);
  await browser.close();
}
```
La página debe llevar `data-testid="calc-price"` en la cifra grande. Las dos
capturas se adjuntan al dueño (`SendUserFile`).

**Terminado:** el script imprime `ok` en los dos tamaños; las capturas
adjuntadas. Sin commit de código (si hubo que arreglar layout, el commit es el
arreglo: `fix(landing): …`).

---

### Fase 8 — Versión 0.81.0 y el estado

**Objetivo:** los tres ficheros de versión coinciden y el estado dice la verdad.

- `backend/app/config.py:16` `APP_VERSION = "0.81.0"`.
- `frontend/lib/version.ts:1` `CURRENT_VERSION = "0.81.0"` + una entrada
  `VersionEntry` al principio de `CHANGELOG` (EN/ES, formato `:17-30`).
- `CHANGELOG.md`: sección `## [0.81.0] — <fecha>` **encima** de la 0.80.0, con
  el mismo tono; incluye: la página, el modelo y sus cuatro diferencias con la
  hoja de referencia, la 055, el evento, el prop de secciones, y **lo que no
  hace** (sin respuesta automática al lead: B-1).
- `PROJECT_STATUS.md`: nueva sección al principio «`/calculator` (rama
  `feat/calculator`, v0.81.0) — construido y verificado en local, NO desplegado»
  con los números medidos y las decisiones pendientes de §7.
- `test_version_is_one_number.py` verde.

**Terminado:** suite completa verde. Commit
`docs(status): v0.81.0 construida y verificada en local; /calculator lista para desplegar`.
Push de la rama: `git push -u origin feat/calculator`.

---

### Fase 9 — Despliegue **[CRÍTICA]** — *solo con autorización del dueño (7.7)*

*Por qué crítica: producción es un VPS con otros dos clientes vivos
(`zorros-*`, `blackvolt-*`), la migración 055 se aplica sobre la base real, y
la otra rama (`/fall`) tiene que ir antes.*

**Precondiciones (todas verificables, ninguna asumida):**
1. Autorización explícita del dueño en esta conversación.
2. `/fall` (0.80.0) ya desplegada, o el dueño decide desplegar las dos juntas
   (entonces `feat/calculator` **contiene** `6f6ee2d` y sirve para ambas —
   verificar con `git merge-base --is-ancestor 6f6ee2d feat/calculator`).
3. Coordinado por `SendMessage` con la sesión par **antes** de tocar el VPS.
4. Copia de la base de producción antes de `alembic upgrade`
   (`PROJECT_STATUS.md` documenta el patrón `~/eko-realtors-backups-vps/`).

**Procedimiento:** el que documenta `PROJECT_STATUS.md` para la última versión
(`--ff-only` desde el commit desplegado, verificar ancestría antes) y
`docs/setup-demo.md:25-26` (`docker compose up -d` + `docker compose exec backend alembic upgrade head`).
`PUBLIC_PATHS` viaja en el bundle del middleware y los `NEXT_PUBLIC_*` se
hornean: **hace falta `next build` en el VPS con su `.env`**.

**Terminado (todo medido en producción, con salida pegada):**
`curl -s https://www.denverhomestory.com/calculator | grep -c '<main'` = 1 y
`grep -c 'Checking session'` = 0; `/api/v1/health` reporta `0.81.0`;
`alembic current` = `055_calculator_snapshot`; `robots`/`og:title` correctos en
el HTML servido; **ningún lead de prueba enviado** (M-4). Commit
`docs(status): v0.81.0 desplegada y verificada en produccion`.

---

### Fase 10 (opcional, decisión 7.1) — Correo automático al lead con su estimación **[CRÍTICA]**

*Solo si el dueño la aprueba. Por qué crítica: es el primer correo automático
que sale hacia una persona real desde esta marca.*

Esbozo, a detallar cuando se apruebe: tras `send_new_lead_notice`, si el lead
tiene correo y `may_send_automated(lead, "email", db)` (`capture.py:525`) →
`send_email(...)` con un cuerpo **determinista y bilingüe** (sin LLM) que
repite su estimación y dice que Natalia le escribe, con línea de baja
(CAN-SPAM). Precondiciones: **`RESEND_FROM` debe ser la marca, no la
plataforma** (M-1); la función nueva **debe** consultar `opted_out_at` o
`may_send_automated` o el barrido `test_opt_out_is_absolute` la pondrá en rojo;
`EMAIL_SIMULATED` en tests. Versión 0.82.0.

---

## 5. Backlog (no justifican fase propia)

| # | Qué | Evidencia | Impacto / esfuerzo |
|---|---|---|---|
| I-1 | `requirements-dev.txt` con `pytest-cov`, `ruff`; que CI los use | `requirements.txt:46-48`, `.github/workflows/*.yml:67` | Alto / bajo — toca deps, fuera de esta rama |
| I-2 | Corregir `CLAUDE.md:177` (sí hay `conftest.py`) y `:158` (atribución de sesión) | `backend/tests/conftest.py` | Medio / trivial |
| I-3 | `/analytics` por página (`landing_variant` / `landing_path`) | `landing_analytics.py` sin `variant` | Alto / medio — cuando haya dos páginas con tráfico |
| M-2 | Pie de página público como componente (`/fall`, `/calculator`, `/`) | `fall/page.tsx:190-203` duplicado | Bajo / bajo — después de fusionar `/fall` |
| M-3 | Recetas con `| tail` pierden el `rc` en zsh | `PLAN.md:107-122`, `docs/plan-analitica-embudo.md:148-166` | Bajo / trivial |
| — | Columna de sesión para `calculator_result` en `landing_sessions` | `fold_events` | Bajo hasta que I-3 exista |
| — | Test que cruce `DEFAULTS` TS ↔ Python valor a valor (hoy solo por resultados) | Fase 2 | Medio / bajo |

## 6. Riesgos y supuestos

**Riesgos de ejecución:**
- **La rama base no está fusionada.** `feat/calculator` desciende de `6f6ee2d`
  (`feat/fall-guide`), sin desplegar y sin autorización de despliegue aún. Si
  esa rama se cae o se rehace, la nuestra hay que rebasarla. Mitigación: nada
  nuestro toca los 9 ficheros de `/fall` salvo `hosts.ts` (una línea) y los dos
  tests guarda.
- **Base de datos compartida.** Un `DROP DATABASE` de la otra sesión sobre
  *nuestra* base es el incidente del 4-sep; mitigación: nombre propio y avisado.
- **Dos implementaciones del modelo.** TS y Python pueden separarse; mitigación:
  fixture único y test cruzado (Fases 1-2). Si uno cambia, el otro se pone rojo.
- **Con los valores por defecto conservadores, el neto a 5 años puede salir
  negativo o pequeño para muchas entradas.** Es correcto y se enseña (el
  deslizador lo hace visible); pero es información de producto que el dueño
  debe ver antes de publicar en redes (decisión 7.2/7.3).
- **El CTA promete solo lo que existe.** No hay listados ni PDF ni correo con
  el desglose. Si el dueño quiere prometer más, primero se construye.
- **Google indexa solo el inglés**: una URL, cambio de idioma en cliente
  (`LanguageSwitcher`), sin `hreflang`. Aceptado en v1.
- **`RESEND_FROM` nombra a la plataforma** — solo importa si la Fase 10 existe.

**Supuestos hechos al planificar:**
- El visitante puede asumir un coste mensual de vivienda **igual** a su renta
  actual (factor 1,0). No se pregunta ingreso ni deudas: **no es una
  precalificación y la página lo dice.**
- Impuesto: un solo valor metropolitano (0,52%); no se pide ZIP (Fair Housing).
- Seguro 0,70%: derivado de medias estatales sobre ~$450k; Denver cotiza por
  debajo, así que es conservador contra comprar.
- PMI se cobra mientras `balance/precio > 80%` (cancelación estándar).
- Sin seguro de inquilino en el alquiler (conservador contra comprar).
- `rateSpread` por crédito **sin fuente** (7.4).
- La otra sesión no crea migración (confirmado por ella; `git diff --name-only dacde8a..6f6ee2d | grep -c alembic` = 0).
- El nombre del fichero de migración lo pone `alembic revision` (UTC); el
  `revision` id se edita a mano — así se hizo en las 54 anteriores.
- Playwright chromium con emulación de iPhone sustituye a webkit (I-4).

## 7. Decisiones pendientes para el dueño

| # | Decisión | Recomendación | Si no dices nada, Opus asume |
|---|---|---|---|
| 7.1 | **Respuesta automática al lead** (B-1: hoy no existe para leads web). ¿v1 sin ella —el contexto llega a Natalia por aviso, Inbox y ficha— y la Fase 10 como 0.82.0 aparte? ¿O se construye ya? | **v1 sin ella.** Es el primer correo automático a personas reales desde esta marca y arrastra M-1 (`RESEND_FROM`) y CAN-SPAM; merece su propia versión | v1 sin ella; Fase 10 no se ejecuta |
| 7.2 | **Apreciación por defecto** del deslizador | **2,0%/año** (Denver −1,8% interanual hoy; largo plazo más alto; Jeff 4,94%) | 2,0% |
| 7.3 | **Crecimiento del alquiler** por defecto | **2,0%/año** (Denver −1,5…−3% hoy; Jeff 2,734%) | 2,0% |
| 7.4 | **Diferencial de tasa por crédito** (sin fuente): 0 / +0,25 / +0,75 puntos, o que el crédito solo mueva el PMI | Mantener el diferencial, etiquetado *illustrative* y editable en «Assumptions» | 0 / +0,25 / +0,75 |
| 7.5 | **Coste de venta**: 4% (hoja de Jeff) o 5–6% | 4% con fuente; el deslizador no lo expone | 4% |
| 7.6 | **Suelo de precio** bajo el que no se enseña cifra | $150.000 | $150.000 |
| 7.7 | **Despliegue**: ¿autorizas la Fase 9 y en qué orden respecto a `/fall`? | Después de `/fall`, en un día distinto, coordinado con la otra sesión | No se despliega |
| 7.8 | **Prueba del formulario contra producción** (el aviso va al correo real de Natalia) | **No.** Solo en local. Si quieres una prueba real, cambia antes `booking_contact_email` desde Settings | No se prueba en producción |

---

### Estado base backend (salida real, 5-sep-2026 15:41)

```
TOTAL                                10785   2001    81%
================ 1659 passed, 39 warnings in 239.02s (0:03:59) =================
=== RUFF ===
All checks passed!
=== WORKER TESTS (CI los corre aparte) ===
collected 0 items
```

---

## Aclaraciones del autor durante la ejecución (5-sep-2026)

Registradas en la consulta de arranque al advisor (autor del plan). No cambian
el diseño; cierran huecos que el texto de las fases dejaba abiertos.

- **A-1 · Base.** `feat/calculator` se movió por fast-forward de `6f6ee2d` a
  `8ee1f31` (un solo commit de docs de `feat/fall-guide`: «v0.80.0 desplegada»).
  El código es idéntico; el estado base de §2.1 sigue valiendo y se re-midió.
- **A-2 · Fase 1, `solvePrice`.** El caso 11 usa `minDown: 0, closingRate: 0`, y
  la regla `vSavings = savings / (minDown + closingRate)` da `0/0`. Regla
  completa, **en TS y en Python**:
  `vSavings = (minDown + closingRate) > 0 ? savings / (minDown + closingRate) : Infinity`.
- **A-3 · Fases 1-2, override de `rate`.** Un `rate` que llegue por `overrides`
  **reemplaza** `a.rate`; `rateSpread[credit]` se suma **después**, igual en las
  dos implementaciones (si no, las anclas de paridad se ponen rojas).
- **A-4 · Cobertura del frontend.** No hay herramienta de cobertura en
  `frontend/` y añadir `@vitest/coverage-v8` es un cambio de dependencias que
  este plan excluye. Se reporta como **no verificable** en cada fase; la del
  backend se mide contra el 81 % de la base.
- **A-5 · `PROJECT_STATUS.md` en cada fase** (regla del dueño sobre la del plan):
  una sección nueva arriba de la de `/fall`. `CHANGELOG.md` y `version.ts`
  esperan a la Fase 8 porque `test_version_is_one_number` acopla los tres
  ficheros: un `0.81.0` temprano pone la suite en rojo.
- **A-6 · Rama.** Una sola rama `feat/calculator`, un commit por fase, push
  tras cada fase. Once ramas dentro de un worktree romperían la reserva de
  versión y migración acordada con la sesión par.
- **A-7 · Producción cambió mientras se planificaba.** `/fall` (0.80.0) **ya
  está desplegada** (`/api/v1/health` = 0.80.0, `/fall` = 200): la precondición
  2 de la Fase 9 se cumple; la autorización (7.7) sigue pendiente. Y la sesión
  par dejó abierto que **el aviso de lead nuevo no llega por Resend** (200 sin
  entrega): de los tres canales de contexto de la v1, el correo hoy no entrega
  en producción; el Inbox y la ficha sí. No se toca desde esta rama.
- **A-8 · Fase 1, `solvePrice` cuando la bisección no converge** (hallazgo del
  auditor independiente de la fase). El coste mensual da un salto donde empieza
  el PMI (LTV 80 %); una renta dentro del salto no tiene precio con
  `|total − rent| < 0.5`, el bucle agota las 80 iteraciones y `mid` cae en el
  lado caro (medido: renta $3.200, ahorro $100.000, crédito «fair» → total
  **$3.467,51** con `cappedBy="rent"`). Regla completa, **en TS y en Python**:
  si el bucle no converge, `vRent = lo` (el mayor precio con `total ≤ rent`).
  Además, las suposiciones editables se normalizan a la entrada de
  `monthlyFor`/`solvePrice`/`compare`: `rate`, `appreciation`, `rentGrowth`
  no finitos → valor de `DEFAULTS`; `hoaMonthly` negativo o no finito → 0;
  `years` = `clamp(floor(years) finito ? … : 5, 1, 40)`. Para entradas bien
  formadas nada cambia; las anclas de paridad se conservan al céntimo.
- **A-9 · Fase 3b, caso 6.** El texto decía «`savings: 10_000_000` (dentro del
  tope)», pero `CalculatorIn` fija `savings ≤ 5_000_000`: 10 M es un 422, no
  un 202. El caso se ejecuta con el ahorro **en el tope (5 000 000)** → 202,
  `capped_by="rent"`, `loan=0`. Los 10 M quedan cubiertos por el parametrizado
  de 422 (`savings` fuera de rango). Errata del plan, no cambio de diseño.
- **A-10 · Fase 3b, casos 3-5 — corrección de contrato (hallazgo del auditor,
  confirmado por el autor).** El plan mandaba **422 sin lead** ante un
  `calculator` fuera de rango o con clave desconocida, «misma promesa que un
  batch malo». La analogía era falsa: un batch perdido es una fila de
  analítica; un 422 en `/public/leads` es **una persona** que ve «something
  went wrong». `CalculatorIn` y sus rangos se mantienen íntegros, pero se
  validan **dentro** de la ruta: si falla, se registra un aviso, el cálculo
  se descarta y **el lead se captura sin snapshot** (`NULL` SQL). Los tests
  de los casos 3-5 pasan a esperar 202 + fila + `IS NULL` + aviso en el log.
  **Es un cambio de contrato respecto al plan y el dueño puede vetarlo**:
  volver al 422 es un solo hunk en `capture()` (quitar el `try`). La Fase 6b
  además solo adjunta `calculator` cuando las entradas de la página son
  válidas — dos defensas contra perder un lead.
- **7.9 (decisión registrada, reversible) · Snapshot en un lead fusionado por
  correo.** Un POST con el correo de un lead existente (`by_address`, donde el
  consentimiento se rechaza) **sí** sobrescribe `calculator_snapshot` («la
  última gana», ya decidido en el plan). Un snapshot no es un permiso: es lo
  que la persona con esa dirección miró; SMS primero y calculadora después es
  el caso legítimo. Si el dueño prefiere protegerlo: `if is_new or not
  by_address` en la asignación.
- **A-11 · Base y versión.** La sesión par desplegó **v0.82.0** (`69214c6`)
  durante la ejecución: `feat/calculator` se rebasó sobre ese commit tras la
  Fase 4 (sin conflictos; la línea `Calculator` del aviso verificada dentro del
  cuerpo que ahora sale por correo y Telegram). La Fase 8 usa **0.83.0**, no
  0.81.0: una versión menor que la de producción haría retroceder `/health`.
  Acordado con la sesión par. La Fase 9 hereda además su regla: si un día la
  calculadora manda algo **al lead** (Fase 10), avisar a la par antes, porque
  entra en `SEND_EXEMPT`/opt-out y en las tablas de los barridos AST.
- **A-12 · Hallazgo I-3, redacción.** `landing_sessions` guarda `landing_path`
  (solo al crear la sesión) pero **no** `landing_variant` (viaja en `utm` y el
  INSERT no lo toma; no hay columna). El único discriminador de página es
  `landing_path`; `landing_events` no lleva `path`, así que un `section_view:
  consult` no se atribuye a página desde los eventos, y una navegación en la
  misma pestaña de `/` a `/calculator` conserva la sesión y mezcla secciones.
  Todo ello queda bajo I-3 (backlog), junto con: «engaged» global podría
  inflarse si `inputs` y `result` caben en el primer viewport; `/analytics`
  itera un literal de 4 secciones y las tres nuevas se almacenan sin mostrarse;
  faltarán sus etiquetas i18n cuando se muestren. Nada de esto se toca en v1.
- **A-13 · Fase 6b, paso 0, restaurar al terminar.** El `update agent_settings
  set booking_contact_email=…` de la prueba de extremo a extremo deja en la
  base de test un estado que cuatro tests (`test_shared_resources.py:682` y
  compañía) dan por sentado como vacío: con un correo configurado, la reserva
  sigue hasta Cal.com con una clave falsa y devuelve 401. Tras la prueba,
  `update agent_settings set booking_contact_email=NULL where org_id=1`. Lo
  aprendí en la suite de la Fase 8 (4 rojos); restaurado, 89/89 en esos
  ficheros y suite completa relanzada.


---

## PLAN (2) — El aviso que Natalia sí recibe: dominio propio, enlace al panel, y Clara también avisa

> Escrito el 6-sep-2026. **Ejecutor: Opus 5.** Se **añade** al plan de
> `/calculator` de arriba; no lo sustituye. Aquel es de la sesión par y sus
> secciones 1-7 se quedan intactas.
>
> Método: una fase cada vez, máx. 3 intentos de corrección por fase, un commit
> convencional por fase, push, **sin merge ni PR sin pedirlo, sin desplegar sin
> autorización en un mensaje aparte**. Advisor antes de la fase [CRÍTICA] y tras
> el 2º intento fallido; registrar cada consulta en `PROJECT_STATUS.md`.
>
> Reglas de convivencia con la sesión par (`DenverHomeStory Calculator`), las
> dos aprendidas hoy a golpes: **el número de versión se pide, no se toma**
> (ella acaba de sacar 0.88.0; la siguiente se le pregunta antes de escribirla), y
> **se ramifica desde lo que corre el VPS**, comprobado con `/health` y
> `git rev-parse` en el VPS, no desde `main` de memoria. Base de tests propia:
> `eko_realestate_test_notice`, nunca la de ella.

---

## Contexto — qué pidió el dueño y qué había debajo

El dueño pidió tres cosas, en sus palabras: que los correos usen el dominio
`denverhomestory.com`; que **cuando alguien llene el formulario o hable con
Clara por teléfono** (la asistente de Vapi) Natalia reciba un correo; y que ese
correo, además de toda la información, lleve **un enlace que abra el mensaje en
su sesión de Eko AI Realtors**, para que toda la comunicación quede
centralizada en el panel. Ese era el plan original del producto.

Lo que hay hoy, medido en el código y en producción, no en la memoria:

| Pieza | Estado real | Dónde |
|---|---|---|
| Aviso por formulario | ✅ existe: correo + Telegram en paralelo, fila interna en el hilo del lead | `services/lead_notify.py`, disparado en `api/v1/public.py:496` |
| Aviso por llamada (Clara / Vapi) | ❌ **no existe**. El fin de llamada guarda transcripción y resumen y **nadie es avisado** | `webhooks/voice.py:228` → `conversation.py:ingest_voice_call`; `send_new_lead_notice` tiene un solo llamante |
| Remitente | `Eko AI Realtors <noreply@realtors.ekoaiautomation.com>` — el de la plataforma, no el de la marca | `RESEND_FROM`; por org se sobreescribe con `channel_routes.sender_override` (`channel_identity.py:222`) |
| Dominio `denverhomestory.com` en Resend | ❌ no existe: `dig` no devuelve SPF, DKIM, MX ni DMARC. DNS en Cloudflare (`arely`/`damian.ns.cloudflare.com`) | medido 6-sep |
| Enlace al panel en el aviso | ❌ no hay. El backend **no sabe la URL del panel** (solo el frontend, `NEXT_PUBLIC_PANEL_URL`) | `config.py` sin `PANEL_URL` |
| Enlace profundo sin sesión | ❌ se pierde: `AuthGuard` manda a `/login` sin recordar el destino y los tres logins hacen `router.replace("/leads")` | `components/ui/AuthGuard.tsx:66`, `app/login/page.tsx`, `auth.py:367` (callback de Google → `/leads`) |
| Host del panel en producción | `https://inmo-demo.ekoaiautomation.com` (el 308 que da `www.denverhomestory.com/leads`) | medido 6-sep |
| Destinatario del aviso | `AgentSettings.booking_contact_email`, un solo correo, se edita en Ajustes (`SettingsForm.tsx`) | `lead_notify.py:139` |

**Y los avisos que «se comía un filtro de Gmail»: dos hipótesis caídas y un
hueco honesto.** Lo medido entre las dos sesiones el 6-sep:
- Los dos avisos de prueba del 5-sep 21:36 (`PRUEBA Preflight`) y 6-sep 02:53
  (`PRUEBA Dos Caminos`) fueron **al dueño**, `enderjnets@gmail.com`, y Resend
  los da por `delivered` (medido por la sesión par desde el VPS; verificar en
  la Fase 0 si el clasificador lo permite, no bloquea). **No fueron a Natalia**
  — mi hipótesis, descartada.
- Un filtro de Gmail que «borra» manda a la **Papelera**, y la papelera **sí**
  se ve: la misma búsqueda devuelve un `alertas@` del 5-sep con `TRASH`. Los dos
  avisos **no están en ninguna etiqueta**, ni papelera ni spam — la hipótesis
  del filtro que borra, descartada.
- No es bloqueo por remitente: la sonda del 6-sep 16:05 salió del **mismo**
  `noreply@` y llegó con `INBOX`.
- Lo único con forma de filtro por asunto es **un** mensaje: el del 28-ago,
  archivado sin `INBOX` y **sin leer**.

**Lo que hace desaparecer un correo entregado sin dejar rastro en la papelera
es una acción humana o un cliente IMAP que expurga**, no un filtro: el buzón
tiene etiquetas `Apple Mail To Do`, `Deleted Messages` (0 mensajes: por ahí
pasan y se borran), `[Imap]/Drafts`, `[Imap]/Outbox` y `Junk (Ender J Gmail)`
— hay o hubo un Apple Mail conectado. Con «Borrar para siempre al expurgar» en
Ajustes → Reenvío y POP/IMAP de Gmail, un correo de prueba que el dueño borra
desde el iPhone o el Mac **desaparece del todo**. Los dos que faltan se llamaban
`PRUEBA …`, y **el dueño confirmó el 6-sep que los borró él**. Cerrado: **no
hay avería en Gmail ni en el producto**; hubo dos correos de prueba borrados a
mano y uno archivado desde la notificación. El plan no busca ningún filtro;
deja una sonda de confirmación con el asunto real (Fase 2.2) y nada más.

---

## Decisiones ya tomadas con el dueño (6-sep)

- **Dirección:** `Denver Home Story <hello@denverhomestory.com>`. Elegida entre
  `hello@`, `hola@`, `info@` y `team@` tras contrastar fuentes primarias
  (Resend, Postmark, Mailjet, Brevo, 101domain). `noreply@` descartado por las
  cuatro; nombre de persona (`natalia@`) descartado por Postmark.
- **Dominio raíz, envía y recibe.** Las respuestas a ese correo entran al
  Inbox del panel atribuidas al lead. Consecuencia aceptada: el MX de
  `denverhomestory.com` apunta a Resend y **no podrá existir un buzón normal
  (Gmail/Workspace) en `@denverhomestory.com` fuera del producto**. Hoy no hay
  ninguno. Si mañana hay newsletter o marketing, va a un subdominio propio.
- **Nombre del remitente:** la marca, no una persona (Postmark). Para correos
  que ve el cliente cabe «Natalia from Denver Home Story <hello@…>»; el aviso
  interno a Natalia va como «Denver Home Story».

---

## Alcance

**Dentro:** dominio propio verificado en Resend con recepción; identidad de
envío de la org DHS; el backend conoce la URL del panel; el aviso lleva enlace
al lead; Clara avisa al terminar una llamada; un enlace profundo sobrevive al
login (contraseña, cuenta y Google); tests y mutaciones; medir de verdad dónde
fueron los avisos de septiembre.

**Fuera, dicho en voz alta:** no se cambia el transporte por Telegram ni su
destinatario; no se añade segundo destinatario ni copia al dueño
(`booking_contact_email` sigue siendo uno — si se quiere, es otra fase); no se
toca `OPS_ALERT_FROM` (alertas de operación al dueño, otro asunto); no se toca
`/fall` ni `/calculator`; no se toca el ROG; **ningún test llama a Resend,
Vapi, Telegram ni Groq de verdad**; **jamás un correo de prueba a
`natalia.kanonerova@engelvoelkers.com`**.

---

## Lo medido, que condiciona el diseño

| Hecho | Evidencia | Consecuencia |
|---|---|---|
| El remitente por org es `sender_override` de su ruta de canal `email`, si no, el global | `channel_identity.py:196-222`; `send_email` usa `identity.sender_override or identity.destination` (`email.py`) | El cambio de dominio es **configuración**, no código: una ruta `email` para la org DHS. Y afecta a **todos** los correos salientes de la org (invitaciones de visita, respuestas a leads), no solo al aviso |
| Resend rechaza envíos desde un dominio no verificado | doc Resend | **Orden obligatorio:** dominio verificado → *después* la ruta. Al revés se rompen todos los correos de DHS a la vez |
| Las rutas se crean por API de plataforma (superusuario) | `platform.py:476 POST /routes`, `:610 PATCH /routes/{id}/identity`; `RouteCreateIn` acepta `sender_override` | Sin SQL a mano. `credential_ref` en null = usa la clave global de Resend, que es lo que queremos |
| El correo entrante se atribuye a la org por el `to` contra `channel_routes.destination` | `tenant_resolver.py:resolve_org_by_destination`; `webhooks/email.py:169-174` | `destination = hello@denverhomestory.com` en esa misma ruta es lo que hace que una respuesta caiga en el Inbox de DHS |
| El fin de llamada ya hace commit y devuelve `{status, lead_id, …}` (y `"duplicate"` en reentregas) | `conversation.py:ingest_voice_call`, paso 5 | El aviso se dispara **después** del commit, en el webhook, y **nunca** en `status == "duplicate"` (Vapi reentrega) |
| El aviso escribe la fila interna solo si hay `message_id` | `lead_notify.py:243 if inbound is None: return` | Para llamadas hay que pasar la conversación de voz, no un mensaje: la fila interna va al hilo `voice` |
| Cada setting nuevo son **3 ediciones idénticas** | `test_config_example.py` + `test_compose_env.py` | `PANEL_URL` × (`config.py`, `.env.example`, bloque `backend:` de `docker-compose.yml`) |
| El callback de Google es un **POST cross-site** desde `accounts.google.com` | `auth.py:336`, `ux_mode=redirect` | Una cookie propia con `SameSite=Lax` no llega ahí. El destino se guarda en `sessionStorage` (sobrevive a la ida y vuelta a Google en la misma pestaña) y se consume al aterrizar |
| Un `next` sin validar es un open redirect | — | Solo rutas relativas al mismo origen: `^/(?!/)`; nunca `/login`; nunca esquemas |
| El panel vive en `inmo-demo.ekoaiautomation.com` | 308 medido | `PANEL_URL` en el `.env` del VPS = ese host, no el de la marca |
| Mi sesión no pudo leer el VPS (clasificador) | dos comandos bloqueados 6-sep | Las lecturas de la Fase 0 las hace Opus con permiso explícito del dueño, o el dueño con `!`. **No se rodea el bloqueo** |

---

## Fases

Rama nueva **`feat/aviso-natalia-dominio-propio`** desde el commit que corra el
VPS (hoy `0760aa1`, v0.88.0; `origin/main` = `bdcf91b`, sus correcciones de
estado — ramificar desde `origin/main` **solo tras comprobar** que contiene el
HEAD del VPS, y releer `git rev-parse origin/main` en ese momento: hoy se movió
tres veces en una tarde). Versión: **0.89.0, concedida por la sesión par el 6-sep** («no tengo
nada bumpeado ni en marcha»). Si al ramificar ha pasado más de un día, volver a
preguntar.

### Fase 0 — Medir antes de tocar (bloqueante, sin código)

Todo esto se lee; nada se escribe. Cada dato va a `PROJECT_STATUS.md`.

1. **¿A quién fueron los avisos de septiembre?** Ya medido por la sesión par:
   `to = ['enderjnets@gmail.com']`, `delivered`, los dos. Si el clasificador lo
   permite, confirmar con la clave leída a variable y **nunca impresa**
   (verificar por forma: prefijo `re_`, longitud):
   `GET https://api.resend.com/emails/96edcb61-f2ef-4177-806f-3756e503f20a`.
   Si no lo permite, se anota «según la sesión par» y se sigue.
1b. **¿Los borró el dueño?** Preguntado el 6-sep con los asuntos y horas exactas
   (`PRUEBA Preflight`, 5-sep 21:36; `PRUEBA Dos Caminos`, 6-sep 02:53):
   **«Sí, los borré yo.»** No hay nada más que mirar en Gmail.
2. **`booking_contact_email` hoy en producción**, con `psql` de solo lectura
   contra `eko-realestate-db` (contenedor nuestro; los `eko-*` sin
   `realestate` no se tocan): `select org_id, booking_contact_email, updated_at
   from agent_settings`. Si el rol `eko` no ve filas (RLS forzada, como en
   `leads`), repetir con el rol de `DATABASE_URL_BYPASS`; «0 filas visibles»
   no es «vacío».
3. **Interpretación** (el dato del 1b ya llegó): no hay avería de entrega. Dos
   correos de prueba borrados a mano en un cliente que expurga; el 28-ago
   archivado sin leer es el mismo gesto desde la notificación. Lo único que
   queda por leer aquí es el punto 2: si `booking_contact_email` ≠ correo de
   Natalia, es un hueco de configuración que el dueño corrige en Ajustes antes
   de la Fase 4; anotarlo.
4. **Forma de los secretos del VPS** (longitud/prefijo, nunca valor):
   `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `VAPI_*`; y valores de
   `EMAIL_SIMULATED` y `VOICE_SIMULATED` (deben ser `false` para que la Fase 4
   pueda probar nada real).
5. **Rutas de canal de la org DHS hoy**: `GET /api/v1/platform/routes` con sesión
   de superusuario (`PLATFORM_ADMIN_EMAILS`), o `select id, org_id, channel,
   destination, sender_override, credential_ref from channel_routes`. Saber si
   ya hay una ruta `email` (entonces es `PATCH …/identity`, no `POST`).
6. **¿La clave de Resend puede crear dominios?** `GET /domains` con ella: 200 →
   sirve; 401/403 → el dominio lo crea el dueño en el panel de Resend y Opus
   solo verifica. **¿Hay webhook de recepción?** `GET /webhooks`: anotar si
   alguno lleva `email.received` y a qué URL apunta.
7. **VPS HEAD** (`git rev-parse --short HEAD` en `~/Eko-AI-RealEstate`) y
   `/api/v1/health`. Comprobar `git merge-base --is-ancestor <HEAD_VPS>
   origin/main`. Pedir el número de versión a la sesión par.

### Fase 1 — Dominio propio en Resend (dueño + Opus, sin código)

1. `POST /domains` con `{"name": "denverhomestory.com", "region": "us-east-1",
   "capabilities": {"sending": "enabled", "receiving": "enabled"}}` (o el dueño
   en el panel, según la Fase 0.6). **Los registros DNS son los que devuelve la
   respuesta**, no los del `docs/setup-email.md`: SPF (TXT raíz), DKIM (TXT
   `resend._domainkey`), MX + TXT de `send.` (Return-Path) y el MX de recepción
   en la raíz (`inbound-smtp.us-east-1.amazonaws.com`, prioridad 9 según doc).
2. El dueño añade cada registro en Cloudflare → DNS → Records, **Proxy status =
   DNS only (nube gris)**, como manda `docs/setup-email.md:50-52`. Además
   `_dmarc` TXT `v=DMARC1; p=none;` (sin `rua` de momento: los informes
   agregados entrarían por el propio webhook de recepción como correo). Se
   escribe en `docs/setup-email.md` una sección «Dominio de marca:
   denverhomestory.com» con los registros exactos que quedaron.
3. `POST /domains/{id}/verify` hasta `status: verified` en `GET /domains/{id}`,
   y `dig` de cada registro desde el Mac como segunda fuente.
4. Recepción: si la Fase 0.6 no encontró webhook con `email.received`, crearlo
   apuntando a `<host del backend>/api/v1/webhooks/email` con el secreto que ya
   verifica `webhooks/email.py` (`RESEND_WEBHOOK_SECRET`). Si ya existe, nada.

**Criterio de terminado:** dominio `verified` con recepción `enabled`;
`dig` confirma SPF, DKIM, MX de `send.`, MX raíz y DMARC; anotado en
`PROJECT_STATUS.md` con fecha.

### Fase 2 — La identidad de la org (configuración, sin código)

**Solo con la Fase 1 en `verified`.** Si no, esto rompe todos los correos de DHS.

1. Ruta `email` para la org DHS: `POST /api/v1/platform/routes` con `{org_id,
   channel: "email", destination: "hello@denverhomestory.com", label: "Denver
   Home Story — correo de marca", sender_override: "Denver Home Story
   <hello@denverhomestory.com>"}` — o `PATCH /routes/{id}/identity` si ya
   existía. `credential_ref` en null a propósito: usa la clave global.
2. **Sondas salientes al dueño** (`enderjnets@gmail.com`), desde el VPS y bajo
   `org_scope` de DHS, con `send_email` del producto — **un antes y un después
   sobre la misma pregunta** (propuesta de la sesión par, y es correcta: si se
   cambia el remitente mientras hay un hueco sin explicar, no se podrá
   distinguir «el dominio nuevo no está caliente» de «lo que ya pasaba»):
   - **Antes** de crear la ruta: sonda con el remitente **viejo** y el asunto
     real `New lead from the website — SONDA A (ignorar)`.
   - **Después** de crear la ruta: la misma sonda con el remitente **nuevo**,
     `SONDA B`.
   Verificar cada una en Gmail con «Mostrar original»: `From`, `dkim=pass`
   (la B con `d=denverhomestory.com`), `spf=pass`, y etiqueta `INBOX`. Si la A
   no cae en `INBOX`, el problema no es del dominio y **se para** hasta
   entenderlo; si la A sí y la B no, es el dominio nuevo.
3. **Sonda entrante**: el dueño responde a esa sonda desde Gmail. Verificar en
   el log del backend que `webhooks/email.py` la recibió, la atribuyó a la org
   DHS por `destination`, y que aparece en el Inbox del panel. Borrar el lead
   de sonda después.

**Criterio de terminado:** las dos sondas verificadas con salida real pegada en
`PROJECT_STATUS.md`. **Ningún test automático aquí**: es configuración viva.

### Fase 3 [CRÍTICA] — El aviso con enlace, Clara avisa, y el enlace sobrevive al login

**Objetivo verificable:** un lead por formulario **y** una llamada terminada a
Clara producen cada uno **un** correo a `booking_contact_email` con toda la
información de hoy más una línea `Open in Eko AI Realtors: <PANEL_URL>/leads/<id>`;
abrir ese enlace sin sesión lleva al login y, tras cualquiera de los tres
logins, aterriza en `/leads/<id>`, no en `/leads`.

**Por qué es crítica:** toca el webhook de voz (por donde entra cada llamada de
producción), `generate_reply` no, pero sí `lead_notify`, que corre dentro del
POST del formulario — el único punto de conversión — y el guardián de sesión
de todo el panel.

**Archivos y cambios — backend:**

- **`app/config.py` + `.env.example` + `docker-compose.yml` (bloque
  `backend:`)**, valores idénticos en los tres: `PANEL_URL: str = ""`. En
  `.env.example`, documentado junto a `NEXT_PUBLIC_PANEL_URL` con la frase
  «el mismo host; el backend lo necesita para poner enlaces en los correos».
  En compose: `PANEL_URL: ${PANEL_URL:-}`. Vacío = sin enlace, no
  `https:///leads/N`.
- **`app/services/lead_notify.py`**:
  - `send_new_lead_notice` gana un origen: formulario (hoy) o **llamada**. La
    firma que menos rompe: parámetros de palabra clave nuevos
    (`origin="form"|"call"`, `conversation_id=None`, `call=None` con caller,
    duración, resumen). Los seis tests actuales siguen llamando igual.
  - Línea de enlace, al final del cuerpo, **solo si `PANEL_URL` no está vacío**:
    `Open in Eko AI Realtors: {PANEL_URL.rstrip('/')}/leads/{lead.id}`.
  - Cuerpo de llamada: `Clara answered a call.` + `Caller`, `Name`, `Duration`
    (mm:ss), `Summary` (el `conv.summary`), `The transcript and the recording
    are in the panel.` + enlace. Asunto distinguible del de formulario:
    `New call answered by Clara — {who}`.
  - Fila interna: para llamadas se escribe en la conversación `voice` recibida
    (`conversation_id`), con `internal=True` como hoy. La rama
    `if inbound is None: return` pasa a «sin conversación conocida, sin fila».
  - Docstring del módulo: dos orígenes, un destinatario, un enlace.
- **`app/api/v1/webhooks/voice.py`**, tras `result = await
  ingest_voice_call(report, db)` (que ya hizo commit): disparar el aviso **si**
  `result.get("status") != "duplicate"` **y** la llamada tiene al menos un turno
  o un resumen. Si `ingest_voice_call` no devuelve `conversation_id`, `stored`
  y `summary`, se añaden al dict de retorno (es nuestro). Envuelto como en
  `public.py:495`: el aviso nunca cuesta la ingesta ni el 200 a Vapi.
- **Barridos AST** (`test_content_gate_is_absolute.py`,
  `test_opt_out_is_absolute.py`): no se añade ninguna función con `.post`. Si
  al implementar apareciera una, se declara en los dos con su motivo.

**Archivos y cambios — frontend:**

- **`lib/nextPath.ts`** (nuevo, pequeño): `isSafeNext(s)` = empieza por `/`,
  no por `//`, no es `/login` ni `/register`, sin espacios ni esquemas;
  `rememberNext(s)` / `takeNext()` sobre `sessionStorage["eko.next"]`, ambos
  en `try/catch` (el storage puede lanzar).
- **`components/ui/AuthGuard.tsx`**: sin sesión →
  `router.replace('/login?next=' + encodeURIComponent(pathname + search))`
  (`useSearchParams` para `search`). Con sesión y `takeNext()` no vacío →
  `router.replace(next)` una sola vez. Esto cubre el aterrizaje del callback de
  Google, que llega a `/leads` por el 303 del backend.
- **`app/login/page.tsx`**: al montar, si hay `?next=` seguro → `rememberNext`.
  Los tres `router.replace("/leads")` pasan a `router.replace(takeNext() ??
  "/leads")`.
- **`lib/hosts.ts`**: nada. `/login` sigue fuera de `PUBLIC_PATHS`.

**Tests** (nunca un transporte real):

Backend, en `tests/test_new_lead_notice.py` (mismo patrón: ASGI real,
`send_email` y `send_operator_telegram` parcheados):
1. Con `PANEL_URL="https://panel.test"` el cuerpo contiene
   `https://panel.test/leads/{id}` **exacto**.
2. Con `PANEL_URL=""` el cuerpo **no** contiene `/leads/`.
3. Un fin de llamada (`tests/test_voice_webhook_e2e.py`, patrón existente) con
   turnos y resumen → `send_new_lead_notice` (parcheado con `AsyncMock`)
   llamado **una** vez, con el `lead_id` de la llamada, y el cuerpo real
   (segundo test sin parchear el aviso, solo el correo) lleva `Clara`,
   la duración y el enlace.
4. La **reentrega** del mismo informe → **cero** llamadas nuevas.
5. Informe sin turnos y sin resumen → no avisa.
6. El aviso de formulario sigue exactamente igual salvo la línea del enlace
   (los seis tests existentes en verde sin cambios).

Frontend (`lib/__tests__/nextPath.test.ts`):
7. `isSafeNext`: acepta `/leads/12`, `/leads/12?tab=timeline`; rechaza
   `https://evil.example`, `//evil.example`, `/login`, `javascript:alert(1)`,
   `""`, `/leads/12 x`.
8. `rememberNext` + `takeNext` devuelven una vez y vacían; con `sessionStorage`
   que lanza, no rompen.

**Mutaciones a verificar** (copiar, mutar, ver el rojo, restaurar, `md5`):

| Mutación | Debe poner en rojo |
|---|---|
| quitar la línea del enlace | test 1 |
| poner el enlace aunque `PANEL_URL` esté vacío | test 2 |
| avisar también cuando `status == "duplicate"` | test 4 |
| avisar de una llamada vacía | test 5 |
| `isSafeNext` acepta `//evil.example` | test 7 |
| `takeNext` no vacía el storage | test 8 |

**Criterio de terminado:** suite backend completa en verde **sin saltados**
desde `eko_realestate_test_notice`; `ruff check app tests` limpio; frontend
`vitest` + `tsc` + `next build` en verde; `docker build -f backend/Dockerfile
backend` OK; diff sin secretos; las seis mutaciones verificadas. Bump (el
número pedido) en `config.py` + `frontend/lib/version.ts` + `CHANGELOG.md`, en
el **mismo** commit que el código. Commit
`feat(notice): el aviso enlaza al panel, Clara avisa al colgar, y el enlace sobrevive al login`.

### Fase 4 — Verificación real y despliegue

**Antes de pedir autorización:** `.env` del VPS gana
`PANEL_URL=https://inmo-demo.ekoaiautomation.com` **añadida con `>>` tras
copia** (`.env.bak.YYYYMMDD_v<versión>`), jamás con `cat >` — el 30-ago un
instalador vació claves así.

**Deploy (autorización en un mensaje aparte):** bundle desde el HEAD del VPS →
`scp` → `git fetch && git merge --ff-only` → `docker compose build backend
frontend` → `up -d` → `/api/v1/health` = la versión nueva. **Sin migración**
(no hay esquema nuevo; `alembic current` sigue en 055). Reversión: `git reset
--hard <HEAD anterior>` + rebuild; la ruta de canal de la Fase 2 no depende del
código y se queda.

**Después del deploy, lo que los tests no pueden probar**, todo con el
destinatario **temporalmente** en el dueño y **restaurado al final** (precedente
en `PROJECT_STATUS.md:3472`; nunca Natalia):
1. Ajustes → `booking_contact_email` = `enderjnets@gmail.com`. Anotar el valor
   anterior **antes** de cambiarlo.
2. Formulario real en `/fall` → correo en Gmail: `From` de marca, `INBOX`,
   línea `Open in Eko AI Realtors: https://inmo-demo…/leads/<id>`.
3. Abrir ese enlace **en una ventana sin sesión** → `/login?next=/leads/<id>` →
   entrar con Google (el flujo de redirección, el que más se rompe) → aterriza
   en `/leads/<id>` con el hilo del lead. Repetir con contraseña.
4. **La cadena en las dos vías, desde un lead de formulario** (lo que en junio
   se probó fue correo↔correo desde el principio; esto no): desde el hilo de
   ese lead en el panel, contestar con el `Composer` → el correo llega al
   cliente de prueba (una dirección `enderjnets+cliente@gmail.com`) como
   `Denver Home Story <hello@denverhomestory.com>` con `In-Reply-To` y
   `References` (Mostrar original) → el cliente pulsa Responder → la respuesta
   aparece **en el mismo hilo del panel**, atribuida a DHS, y Gmail la muestra
   como una sola conversación. Si la primera respuesta a un lead de formulario
   no sale por correo o abre un hilo suelto, es un hallazgo, no un detalle.
5. **Llamada real a Clara** (la hace el dueño desde su móvil, un minuto, decir
   nombre y que busca casa) → al colgar, correo `New call answered by Clara —
   …` con duración, resumen y enlace; el enlace abre el hilo `voice` con la
   transcripción.
6. **Gmail: nada que probar aquí.** La sonda A de la Fase 2.2 ya lleva el asunto
   real y cayó (o no) en `INBOX`; eso es todo lo que hay que anotar. Si por lo
   que sea la A no cayó en `INBOX`, la Fase 2 ya paró y aquí no se llega.
7. Restaurar `booking_contact_email` al valor anotado; borrar los leads de
   prueba (`select count(*)` antes y después); comprobar que Telegram también
   sonó en cada caso.
8. **Lo que solo Natalia puede confirmar:** que el primer aviso real le llega y
   que el enlace le abre el panel con su cuenta. Su buzón es de
   `engelvoelkers.com`; desde aquí solo se mide que el transporte lo aceptó.
9. `PROJECT_STATUS.md`: checklist con salida real; `main` + tag + release en
   el mismo movimiento, y avisar a la sesión par con el hash final.

---

## Riesgos y supuestos

1. **La clave de Resend del VPS podría ser de solo envío** → no crea dominios.
   Mitigación: Fase 0.6 lo mide; el dueño crea el dominio en el panel y Opus
   verifica. Nada de pedir otra clave por el chat.
2. **Poner la ruta antes de verificar el dominio** rompe **todos** los correos
   de DHS, no solo el aviso. Es un orden escrito (Fase 1 → Fase 2), no un test.
3. **MX en la raíz**: cualquier correo a `*@denverhomestory.com` entra al
   producto; una dirección que no coincida con ninguna ruta cae al fallback de
   tenant único (`tenant_resolver`). Aceptado por el dueño; anotado.
4. **`VOICE_SIMULATED=true` en producción** haría imposible la prueba de la
   llamada. Se lee en la Fase 0.4 antes de prometer nada.
5. **Vapi reentrega informes**: sin la guarda de `duplicate` Natalia recibiría
   el mismo aviso varias veces. Test 4 y su mutación.
6. **`sessionStorage` puede no existir** (navegación privada estricta, vista
   previa). Todo va en `try/catch`; el peor caso es aterrizar en `/leads`, que es
   lo de hoy.
7. **El aviso corre dentro del POST del formulario**: la línea del enlace no
   añade transporte ni tiempo; el presupuesto de 8 s de las dos vías no se toca.
8. **Los avisos de septiembre pudieron ir a Natalia.** Si la Fase 0 lo confirma,
   se le dice al dueño en la primera línea, no en una nota al pie.
9. **`POST /routes` podría rechazar una ruta `email` sin refs** por
   `_refuse_a_route_that_cannot_verify` (`platform.py`). Una ruta sin
   `credential_ref` ni `inbound_secret_ref` **tiene** que ser válida: cada campo
   cae al global por su cuenta (`channel_identity.py:204-222`). Si la API la
   rechaza, se lee esa función antes de tocar nada; no se mete la fila por SQL
   para esquivar la validación.

---

## Verificación (resumen ejecutable)

1. Fase 0 entera anotada con salida real; interpretación escrita **antes** del
   dato.
2. Dominio `verified` + recepción; `dig` de cinco registros + DMARC.
3. Sonda saliente (`dkim=pass`, `d=denverhomestory.com`, `INBOX`) y sonda
   entrante atribuida a la org, ambas al dueño.
4. Suite completa en verde sin saltados, `ruff`, `tsc`, `vitest`, `next build`,
   `docker build`; seis mutaciones en rojo; `md5` restaurado.
5. Tras el deploy: `/health` = versión nueva; formulario → correo con enlace →
   enlace sin sesión → Google → `/leads/<id>`; llamada a Clara → correo;
   sonda del asunto; destinatario restaurado; leads de prueba borrados.
6. `origin/main` == HEAD del VPS; tag y release; sesión par avisada.

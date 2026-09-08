# PLAN.md — Apellido obligatorio en los formularios públicos, y el host del panel deja de servir las páginas de la marca

> **Para el ejecutor (Opus 5):** este fichero se copia a `~/eko-calculator/PLAN.md`
> en la Fase 0 y se commitea — es el plan vivo de la rama, como lo fue el de
> `/calculator`. (En este Mac el sistema de ficheros no distingue mayúsculas:
> `Plan.md`, `plan.md` y `PLAN.md` son **el mismo fichero**, y git lo trackea
> como `PLAN.md`. Escribir «Plan.md» sobrescribe el plan de `/calculator`, que
> es lo previsto: un plan vivo por rama.) Lo que no esté escrito aquí, no
> existe. Máximo **3 intentos** de corrección por fase; ante un bloqueo, o
> antes de la fase **[CRÍTICA]**, consulta al advisor antes de improvisar. Cada
> número que reportes sale de una salida pegada, no de memoria. Un verde que no
> se ha puesto rojo con una mutación no cuenta como verde.

---

## 1. Contexto

Dos observaciones del dueño el 7-sep-2026, **las dos medidas** antes de escribir esto.

### 1.1 «¿Por qué la calculadora aparece en `inmo-demo.ekoaiautomation.com`?»

**Sí está en el dominio de la marca.** Medido el 7-sep:

```
https://www.denverhomestory.com/calculator        200
https://denverhomestory.com/calculator            301 → https://www.denverhomestory.com/calculator
https://inmo-demo.ekoaiautomation.com/calculator  200   ← la copia
```

Los dos hosts sirven **el mismo HTML byte a byte** (28.511 bytes) y el
`canonical` de **ambos** apunta a `https://www.denverhomestory.com/calculator`.

La causa está en `frontend/middleware.ts`: tiene dos reglas y le falta la tercera.

| host | ruta | hoy |
|---|---|---|
| marca | interna (`/leads`, `/about`) | 308 → panel ✅ |
| panel | `/` | 307 → `/leads` ✅ |
| panel | pública (`/fall`, `/contact`, `/calculator`) | **se sirve** ← el hueco |

No es un descuido: `PROJECT_STATUS.md:106` lo registra como comprobado en la
0.85.0 y `app/page.tsx:44` documenta el riesgo y lo cubre con el `canonical`.
Pero el `canonical` es una **sugerencia** para Google, no una orden, y el
`robots.txt` que sirve Cloudflare en los dos hosts dice `User-agent: * /
Allow: /` (el mismo pisotón que ya está en memoria). No hay `sitemap.xml` en
ninguno (404). Enlaces internos a esas rutas **sí** hay — `frontend/lib/guides.ts:49`,
los que la v0.91.0 puso en la home — pero `GUIDES` se renderiza **solo** en
`Landing.tsx` (`:660`, `:792`), y la home no se sirve en el host del panel (el
307 a `/leads` va antes), así que ningún `next/link` prefetchea un 308 a otro
origen. Ninguna pantalla del panel enlaza a una ruta pública (medido:
`git grep "lib/guides\|GUIDES" -- frontend/app frontend/components` → solo
`Landing.tsx`). **No sé desde qué enlace llegó el dueño a `inmo-demo`.**
Busqué la copia en el índice de Google y no encontré evidencia, pero el
`site:` de esa herramienta no es Google: **no puedo afirmar que no esté indexada.**

### 1.2 «El formulario de `/fall` no pide el apellido, como sí lo pedimos en la principal»

**La principal tampoco lo pide.** `/`, `/fall` y `/calculator` usan el **mismo**
`ConsultForm`, con un único campo de nombre:

```
frontend/components/landing/ConsultForm.tsx:207   label={t("landing.form.name")}
frontend/lib/i18n.tsx:903    "landing.form.name": "First name"
frontend/lib/i18n.tsx:1844   "landing.form.name": "Nombre"
```

`/contact` tiene su propio formulario (`app/contact/page.tsx:148`, campo
`name` con `autoComplete="name"`), también con un solo campo. En el servidor no
existe apellido: `PublicLeadIn.name` es un campo, y la tabla `leads` tiene una
sola columna `name` (`String(160)`, nullable). El único `lastName` del repo es
del botón de Apple Sign-In.

Así que no es un arreglo: es **añadir un campo que nunca existió**, en las
cuatro páginas públicas a la vez.

**Decisión del dueño (7-sep, con el coste de conversión sobre la mesa):
nombre y apellido OBLIGATORIOS.**

---

## 2. Decisiones tomadas (no reabrir)

1. **El apellido se guarda en la columna `name` que ya existe**, uniendo
   `"nombre apellido"` en el cliente. Sin migración. Razón medida: `name` ya
   recibe nombres completos por los otros canales — `conversation.py:595` la
   rellena con `report.from_name`, que en WhatsApp es el nombre de perfil
   entero — y todo lo que la consume la trata como etiqueta de persona
   (`lead_notify.py:357` `who`, `visits.py:512` `lead.name or "Cliente"`,
   `inbox.py:64`). Una columna nueva obligaría a migración 056 sobre la tabla
   por la que entra todo lead en producción, más `LeadOut`, más la ficha, más
   la lista — a cambio de nada que hoy se use.
2. **Obligatorio en el navegador, no en el servidor.** El mismo endpoint
   `/api/v1/public/leads` atiende a otros formularios y a otro tenant (`form`
   en `channel_routes`); exigir `name` en `PublicLeadIn` rompería a terceros.
   El `required` va en el marcado, y un envío sin nombre (bot, JS apagado)
   **sigue capturándose** — la captura es el punto, el campo es cortesía.
3. **Redirección 308** del host del panel a la marca, en el middleware, no una
   Redirect Rule de Cloudflare: la regla tiene que vivir donde un test la vea.
4. **Descartado: no hacer nada y confiar en el `canonical`.** Es lo que hay
   hoy y es defendible, pero deja dos direcciones vivas para la misma página
   con `Allow: /` para todo rastreador. Cerrarlo cuesta cuatro líneas con test.
5. **Versión: 0.92.0 — a confirmar con la sesión par en la Fase 0 antes de
   escribirla en ningún fichero.** El número se pide, no se asume.
6. **Unión en una función pura** (`frontend/lib/leadName.ts`), no en los
   componentes: es lo único testeable en este repo (§3, «sin DOM»).

**Fuera de alcance:** columna `last_name`; tocar el consentimiento TCPA, el
honeypot, Turnstile o el endpoint del formulario; hacer obligatorio el email
en `/contact` (hoy no lo es; backlog); retirar el nombre `inmo-demo`;
`/analytics` por página.

---

## 3. Entorno y hechos medidos (7-sep-2026)

**Dónde se trabaja:** worktree propio `~/eko-calculator` (venv propio,
`node_modules` propio, base `eko_realestate_test_calculator` en el Postgres
compartido `:5434`, puertos 8021/3010). Su HEAD `bdcf91b` (0.88.0) **es
ancestro de `origin/main`** `ab6b442` (0.91.0); `middleware.ts`, `hosts.ts` y
`app/calculator/` son idénticos entre los dos. Se rama desde `origin/main`.

**Salto `bdcf91b → ab6b442`, medido:** `git diff --stat` sobre
`frontend/package-lock.json frontend/package.json backend/requirements.txt
backend/migrations` → **vacío**. Ni dependencias ni migraciones nuevas: el
venv, el `node_modules` y la base de este worktree valen tal cual. (Si el
`fetch` de la Fase 0 trae commits nuevos, repetir ese `diff` contra el HEAD
que salga; si deja de estar vacío, reinstalar/migrar **en lo mío** antes de
medir el verde de referencia.)

**Producción (VPS `ender-vps`, `~/Eko-AI-RealEstate`):** rama
`feat/maquina-de-video-dhs`, HEAD **`2588c2c`** (= tag `v0.91.0`);
`/api/v1/health` → `0.91.0`, `production`, `captcha: on`. `origin/main` =
`ab6b442` = `2588c2c` + un commit de `PROJECT_STATUS.md`. `.env` del VPS:
`NEXT_PUBLIC_BRAND_URL=https://www.denverhomestory.com`,
`NEXT_PUBLIC_PANEL_URL=https://inmo-demo.ekoaiautomation.com` — el middleware
**ya** está configurado; solo le falta la regla.

**Sin DOM en vitest, a propósito.** `frontend/vitest.config.ts`: «deliberately
NOT adding jsdom or @testing-library… the repo has decided against them more
than once». No hay test que renderice un componente; los que tocan
`ConsultForm.tsx` lo leen **como texto** (`track.test.ts:347`,
`landingConfigWiring.test.ts`). Ninguno de los dos afirma ids de campos:
`landingConfigWiring` mira variables `NEXT_PUBLIC_*`; `track.test` mira
`session_id: sessionId`, `form_submit`, `form_error`, `onFocusCapture` — no se
tocan.

**Límites y props, leídos del código:**
- `MAX_NAME = 160` en **`backend/app/services/capture.py:49`** (no en `public.py`).
  Dos inputs con `maxLength={79}` → unión máxima 79+1+79 = **159 ≤ 160**.
- `LandingField` (`ConsultForm.tsx:319-349`) acepta `required` y
  `autoComplete`, **no `maxLength`** → hay que añadir el prop.
- `Field` de `/contact` (`page.tsx:246-275`) **no acepta ni `required` ni
  `maxLength`** → hay que añadir los dos.
- Estado del formulario: `ConsultForm.tsx:55`
  `useState({ name: "", phone: "", email: "", website: "" })`; payload `:148`
  `name: f.name.trim() || undefined`. En `/contact`: `:38` y `:91`.

**Playwright:** instalado en el scratchpad
(`…/scratchpad/pw/node_modules/playwright` + chromium). Guiones que rellenan
el formulario y **se rompen con el `required` nuevo**: `pw/calc-e2e.mjs:21`
(`first name` + email, sin apellido). `pw/calc-mobile.mjs` no envía, solo mide.

**Referencia de verde, medida en `origin/main` el 7-sep-2026** (no la del
histórico, que decía 301): **vitest 357/357** en 21 ficheros, `tsc` limpio,
`next lint` 0/0, `next build` OK, prerender `<main>`=1 y «Checking session»=0 en
`calculator`, `fall`, `contact`, `index`. Backend: **1779 passed**, 39 avisos,
264,96 s; `ruff check app tests` → «All checks passed!».

**Formatos de versión:** `frontend/lib/version.ts` — `CURRENT_VERSION` +
`VersionEntry { version, date, title:{en,es}, changes:[{en,es}] }` al
**principio** del array; `CHANGELOG.md` — `## [0.92.0] — AAAA-MM-DD` con
`### Added` / `### Changed` encima de la 0.91.0; `backend/app/config.py:16`
`APP_VERSION`. `test_version_is_one_number.py` cruza `version.ts` con
`CHANGELOG.md` (y el backend); sin entrada en el CHANGELOG, rojo.

**Comandos (todos desde `~/eko-calculator`; entorno de backend en cada shell nuevo):**
```bash
cd ~/eko-calculator/backend
PW=$(docker exec eko-realestate-db printenv POSTGRES_PASSWORD)
export DATABASE_URL="postgresql+asyncpg://eko:${PW}@localhost:5434/eko_realestate_test_calculator"
export DATABASE_URL_APP="postgresql+asyncpg://eko_app:eko_app_local_pass@localhost:5434/eko_realestate_test_calculator"
export WHATSAPP_ENABLED=true PYTHONDONTWRITEBYTECODE=1
./.venv/bin/python -m pytest -q -p no:cacheprovider
./.venv/bin/python -m ruff check app tests --output-format=concise

cd ~/eko-calculator/frontend
npx tsc --noEmit && npx vitest run && npx next lint && npx next build
for p in calculator fall contact index; do f=".next/server/app/$p.html"; \
  printf "%-10s <main>=%s Checking=%s\n" "$p" "$(grep -c '<main' "$f")" "$(grep -c 'Checking session' "$f")"; done
npx next start -p 3010
```
No encadenes `| tail` a un comando cuyo `rc` necesites (zsh no tiene
`PIPESTATUS`). **Prohibido:** `eko_realestate_test`, `eko_realestate`,
exportar `APP_DB_PASSWORD`, `docker compose up/down/restart` en local,
`git stash` a secas, `git checkout -- .`, probar el formulario contra
producción (el aviso va al correo real de Natalia), pedir a la sesión par que
ejecute algo que aquí esté bloqueado.

---

## 4. Fases

### Fase 0 — Rama, plan y coordinación

**Una rama por fase, encadenadas** (lo manda el goal del dueño: `feat/<fase>`,
un commit por fase, push a remoto). Cada una nace del HEAD de la anterior:
`feat/f0-plan` ← `origin/main`; `feat/f1-host-panel` ← `feat/f0-plan`;
`feat/f2-apellido` ← `feat/f1-host-panel`; `feat/f3-movil` (solo si hay arreglo
de layout); `feat/f4-version` ← la última. El bundle de la Fase 5 se hace contra
**la última rama**, no contra un nombre único.

```bash
cd ~/eko-calculator && git fetch origin && git status --porcelain   # árbol limpio antes de moverse
git checkout -b feat/f0-plan origin/main
git diff bdcf91b HEAD --stat -- frontend/package-lock.json frontend/package.json backend/requirements.txt backend/migrations   # esperado: vacío (§3)
```
- Copiar este fichero a `PLAN.md` y commitear:
  `docs(plan): apellido obligatorio y el host del panel deja de servir las publicas`.
- Correr los cuatro bloques de §3 **antes de tocar nada** y anotar aquí los
  números (referencia de verde real de `origin/main`). Si algo sale rojo en
  limpio, **anotarlo, no arreglarlo**: es un hallazgo, y no es de esta rama.
- `SendMessage` a **Eko Ai Realtors**: rama nueva desde `ab6b442`; ficheros que
  toco (`middleware.ts`, `hosts.ts` solo si hace falta, `ConsultForm.tsx`,
  `app/contact/page.tsx`, `i18n.tsx`, `lib/leadName.ts` nuevo,
  `hostRouting.test.ts` + los tres de versión en la Fase 4); **pedir el
  0.92.0**, y avisar de que serán **cinco ramas, no una**.
  `CHANGELOG.md` y `version.ts` no se tocan hasta tener respuesta;
  `PROJECT_STATUS.md` **sí** se escribe al cerrar cada fase (lo pide el goal del
  dueño, posterior a este plan): sección nueva arriba, corta, sin reescribir la
  fila `:106`.

**Terminado:** rama creada, `PLAN.md` commiteado, referencia de verde anotada,
mensaje enviado.

---

### Fase 1 — El host del panel manda las páginas públicas a la marca

**`frontend/middleware.ts`** — importar `BRAND_URL` junto a lo que ya importa
de `@/lib/hosts`, y añadir la tercera regla **después** de la de `/`:

```ts
// The other half of the split. Without this the panel hostname serves every
// public page too — same HTML, second address — and the canonical tag is the
// only thing asking Google to pick the brand one, against a robots.txt
// Cloudflare rewrites to `Allow: /`. `/` is excluded explicitly (and handled
// above) so the panel's front door keeps going to the work.
if (host === PANEL_HOST && pathname !== "/" && isPublicPath(pathname)) {
  return NextResponse.redirect(`${BRAND_URL}${pathname}${search}`, 308);
}
```

**`/contact` entra en la regla, y eso revierte una decisión escrita.** El
comentario de arriba (`:61-63` en `origin/main`) decía: «Only `/` moves:
`/contact` stays reachable there so an operator following a link from an email
is not bounced across hostnames». Hay que **reescribirlo**, no dejarlo
mintiendo. Lo que se midió antes de decidir:
`grep -rn "/contact" backend/app/services backend/app/api` → **vacío**; el
único enlace que el sistema envía por correo es `PANEL_URL/leads/<id>`
(`lead_notify.py:29`), y ninguna pantalla del panel enlaza a `/contact`. El
flujo que la excepción protegía **no lo emite ningún código**; y un enlace
guardado a mano acaba, vía 308, en la misma página del dominio correcto.
Decisión del dueño (7-sep), tomada con ese dato delante y con la alternativa
—excluir `/contact`— sobre la mesa.
308 por coherencia con la regla hermana y porque a Google hay que decirle que
la dirección buena es una. El navegador lo cachea: **ver una pública en el
host del panel deja de ser posible** sin vaciar caché. Es el objetivo; queda
escrito.

**`frontend/lib/__tests__/hostRouting.test.ts`** — casos nuevos, con el mismo
`load(BRAND, PANEL)` y `req(...)` del fichero:
- `/fall`, `/contact`, `/calculator` en `realtors.ekoaiautomation.com` →
  `location === BRAND + ruta`, `status === 308`. **`/contact` con su propio
  `it(...)` y el porqué en el cuerpo**: hoy no existe ninguna aserción sobre
  `/contact` en el host del panel, y por eso el cambio de comportamiento habría
  pasado en verde. El test es lo que hace la decisión visible al siguiente.
- `/fall?utm_source=instagram` → la query sobrevive en la `location`.
- `/contact/thanks` (subruta pública) → también redirige.
- `/about` en el host del panel **sigue devolviendo `null`** — el test «keeps
  the platform's sales page reachable on the panel's own hostname» ya lo fija;
  no duplicarlo, confirmar que sigue verde.
- `/` en el host del panel sigue dando `PANEL/leads` con 307 (test existente).
- Sin configurar (`load("", "")`) nada redirige (primer test del fichero).

**Mutación obligatoria:** cambiar `BRAND_URL` por `PANEL_URL` en la regla nueva
→ los casos nuevos en rojo; restaurar; verde. Anotar en el commit.

**Terminado:** `tsc`, `vitest`, `lint`, `build` verdes; la mutación vista en
rojo. **Cobertura:** el repo no tiene instrumentación de cobertura para el
frontend (vitest sin `--coverage`, nunca instalada); no es medible y no se
declara. Sustituto declarado: cada rama nueva del middleware la ejecuta un test
y la mutación la puso en rojo. Commit
`feat(landing): el host del panel manda las paginas publicas al dominio de la marca`.

---

### Fase 2 — Nombre y apellido, obligatorios, en los cuatro formularios

**`frontend/lib/leadName.ts`** (nuevo):
```ts
/** "Ana" + "Pérez" → "Ana Pérez"; blanks dropped; "" when both are empty. */
export function fullName(first: string, last: string): string {
  return [first, last].map((s) => s.trim()).filter(Boolean).join(" ");
}
```

**`frontend/components/landing/ConsultForm.tsx`** (`/`, `/fall`, `/calculator`):
- `LandingField` gana el prop `maxLength?: number` (pasarlo al `<input>`).
- Estado `:55` → `{ name: "", lastName: "", phone: "", email: "", website: "" }`.
- Rejilla: la de dos columnas que hoy comparten nombre y teléfono pasa a ser
  **nombre | apellido**; el teléfono baja a una fila propia a ancho completo,
  encima del email. En móvil todo se apila igual que hoy.
  - `ln-name`: `required`, `maxLength={79}`, `autoComplete="given-name"` (ya).
  - `ln-lastname` (nuevo): `label={t("landing.form.lastname")}`, `required`,
    `maxLength={79}`, `autoComplete="family-name"`.
- Payload `:148` → `name: fullName(f.name, f.lastName) || undefined`.
- **Nada más cambia**: ni consentimiento, ni honeypot, ni Turnstile, ni
  endpoint, ni `session_id`, ni los `record(...)` del tracker (el docstring
  `:3-15` prohíbe copiar el formulario; `track.test.ts` vigila el resto).

**`frontend/app/contact/page.tsx`** — su formulario propio:
- `Field` gana `required?: boolean` y `maxLength?: number`.
- Estado `:38` + campo `lastName`; el `Field` de nombre pasa a
  `autoComplete="given-name"`, `required`, `maxLength={79}`; `Field` nuevo
  `id="lastName"`, `label={t("contact.lastname")}`, `autoComplete="family-name"`,
  `required`, `maxLength={79}`. Payload `:91` → `fullName(...) || undefined`.

**`frontend/lib/i18n.tsx`** — en **EN y ES**, sangría de 2 espacios, mismo
orden en las dos secciones, justo debajo de la clave de nombre correspondiente:
`"landing.form.lastname": "Last name"` / `"Apellido"`, y
`"contact.lastname": "Last name"` / `"Apellido"`. `i18nParity.test.ts` exige
las mismas claves en los dos idiomas. Ninguna cadena con «eko».

**Tests (sin DOM — §3):**
- `frontend/lib/__tests__/leadName.test.ts`: `fullName("Ana","Pérez") === "Ana Pérez"`;
  `fullName("Ana","") === "Ana"`; `fullName("  Ana ","  Pérez ") === "Ana Pérez"`;
  `fullName("","") === ""`; `fullName("", "Pérez") === "Pérez"`.
- En `hostRouting.test.ts` **no**: en un fichero nuevo
  `frontend/lib/__tests__/publicFormFields.test.ts`, leyendo el fuente como
  texto (patrón `read(...)` de `track.test.ts`): `ConsultForm.tsx` contiene
  `id="ln-lastname"`, `autoComplete="family-name"`, y los dos campos de nombre
  llevan `required` y `maxLength={79}`; `app/contact/page.tsx` ídem con
  `id="lastName"`; y los dos importan `fullName` de `@/lib/leadName` (si un
  día alguien vuelve a `f.name.trim()`, rojo).
- **Mutación:** quitar el `.trim()` de `fullName` → `leadName.test` en rojo;
  quitar `required` de `ln-lastname` → `publicFormFields.test` en rojo.
  Restaurar; verde.

**Actualizar el guion de extremo a extremo:** `scratchpad/pw/calc-e2e.mjs:21`
añade `await page.getByLabel(/last name/i).fill("Probe");` — si no, el
`required` nuevo lo deja bloqueado en el navegador y el fallo parecería del
formulario.

**Terminado:** `tsc`, `vitest`, `lint`, `build` + prerender verdes (§3); las
dos mutaciones vistas en rojo. Commit
`feat(landing): nombre y apellido, obligatorios, en los cuatro formularios publicos`.

---

### Fase 3 — Móvil medido, capturas al dueño

El dueño mira estas páginas en el móvil y la norma del proyecto es
mobile-first. Con `npx next start -p 3010` y el Playwright del scratchpad
(chromium con `devices["iPhone 13"]`, 390×844 — webkit no está instalado):

- Guion nuevo `scratchpad/pw/forms-mobile.mjs`, sobre el patrón de
  `calc-mobile.mjs`: para `/`, `/fall`, `/calculator`, `/contact` —
  `scrollWidth <= innerWidth`; los dos campos de nombre y el email con
  `boundingBox().height >= 44` y enteros dentro del viewport tras
  `scrollIntoViewIfNeeded`; captura a 390 px de la zona del formulario.
- Enviar el formulario **vacío** en `/calculator` y comprobar que el navegador
  lo detiene (`page.evaluate(() => document.querySelector("form").checkValidity())`
  → `false`) y que **no** salió ningún `POST /api/v1/public/leads`
  (`page.on("request")`). Rellenar los tres obligatorios → `checkValidity()`
  `true`. Es la prueba de que el `required` existe en el marcado real, no en
  el fuente.
- **Las cuatro capturas → `SendUserFile` al dueño**: el reparto de la rejilla
  (nombre y apellido en la misma fila, teléfono debajo) es una decisión visual
  suya, no mía.

**Terminado:** el guion imprime `ok` en las cuatro páginas; capturas enviadas.
Sin commit salvo arreglo de layout (`fix(landing): …`).

---

### Fase 4 — Versión y estado (solo con el número confirmado en la Fase 0)

- `backend/app/config.py:16` `APP_VERSION = "0.92.0"` y
  `frontend/lib/version.ts:1` `CURRENT_VERSION = "0.92.0"` — el mismo número.
- `VersionEntry` nueva al principio de `CHANGELOG` en `version.ts` (EN/ES, sin
  tildes como las vecinas): título «Last name on every public form, and one
  address per public page» / «Apellido en todos los formularios publicos, y
  una sola direccion por pagina publica»; tres `changes`: el campo y que es
  obligatorio; que el host del panel redirige a la marca; que nada cambia para
  el lead que llega sin nombre.
- `CHANGELOG.md`: `## [0.92.0] — <fecha>` encima de la 0.91.0, `### Added`
  (apellido) y `### Changed` (middleware), en el tono de las anteriores.
- `PROJECT_STATUS.md`: **sección nueva arriba**, no reescribir la fila `:106`
  (fue una verificación correcta de la 0.85.0; la historia se queda). Dice
  que la 0.92.0 cambia ese comportamiento y por qué, anota el campo nuevo, la
  decisión del dueño sobre obligatoriedad y el riesgo de conversión (§6).
- `test_version_is_one_number.py` verde; suite backend completa verde (el
  bump toca `config.py`).

**Terminado:** los cuatro bloques de §3 verdes. Commit
`docs(status): v0.92.0 — apellido obligatorio y el panel deja de servir las publicas`.
push de cada rama a `origin` según se cierra (lo exige el goal).

---

### Fase 5 — Despliegue **[CRÍTICA] — solo con autorización del dueño en mensaje aparte**

*Por qué crítica: el VPS es el compartido con Zorros y BlackVolt; el
middleware va horneado en el bundle (`next build` con el `.env` del VPS); y el
clasificador de Claude Code **ha bloqueado `git merge --ff-only` en el VPS
cuatro veces** (`PROJECT_STATUS.md:501,524`). No se rodea: el merge, la
construcción y el arranque los ejecuta **el dueño en su terminal**.*

**Precondiciones (se miden, no se asumen):**
- [ ] Autorización del dueño.
- [ ] Sesión par avisada por `SendMessage` **antes** de tocar el VPS, y sin
  despliegue suyo en marcha.
- [ ] VPS: `git rev-parse --short HEAD` = **`2588c2c`**. Si no, **parar** y
  rebasar sobre lo que haya (un bundle contra el commit equivocado falla;
  forzar, nunca).
- [ ] VPS: `curl -s localhost:8011/api/v1/health` = `0.91.0`.
- [ ] Copia del `.env`: `cp .env .env.bak.$(date +%Y%m%d)_v0910` (no cambia
  ninguna variable; es el patrón). **Sin migración, sin copia de base**: no
  hay esquema nuevo; `alembic current` se queda en 055 y **no se ejecuta
  `alembic upgrade`**.

**Lo que hago yo (llevar la rama, bundle, no push directo):**
```bash
cd ~/eko-calculator && git bundle create /tmp/apellido.bundle 2588c2c..feat/f4-version
git bundle verify /tmp/apellido.bundle
scp /tmp/apellido.bundle ender-vps:/tmp/
ssh ender-vps 'cd ~/Eko-AI-RealEstate && git fetch /tmp/apellido.bundle feat/f4-version:refs/remotes/bundle/apellido && git rev-parse --short refs/remotes/bundle/apellido'
```

**Lo que ejecuta el dueño, en su terminal (cuatro órdenes, con el `cd`, sin `!`):**
```
cd ~/Eko-AI-RealEstate && git merge --ff-only refs/remotes/bundle/apellido
cd ~/Eko-AI-RealEstate && docker compose build backend frontend
cd ~/Eko-AI-RealEstate && docker compose up -d backend frontend
curl -s localhost:8011/api/v1/health
```
La última tiene que decir **0.92.0**.

**Reversión:** `git reset --hard 2588c2c` + `docker compose build backend frontend`
+ `docker compose up -d backend frontend`. Sin migración que deshacer.

**Terminado (todo medido en producción, salida pegada en `PROJECT_STATUS.md`):**
```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://inmo-demo.ekoaiautomation.com/calculator   # 308 https://www.denverhomestory.com/calculator
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://inmo-demo.ekoaiautomation.com/fall         # 308 …/fall
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://inmo-demo.ekoaiautomation.com/             # 307 …/leads
curl -s -o /dev/null -w '%{http_code}\n' https://inmo-demo.ekoaiautomation.com/leads                        # 200 — el panel intacto
for p in / /fall /contact /calculator; do curl -s -o /dev/null -w "$p %{http_code}\n" "https://www.denverhomestory.com$p"; done   # 200 ×4
curl -s https://www.denverhomestory.com/api/v1/health                                                        # 0.92.0
curl -s https://www.denverhomestory.com/fall | grep -c 'ln-lastname'                                         # ≥ 1
```
Más una captura real de `/fall` en producción a 390 px con los dos campos
(`prod-verify.mjs` como patrón) → `SendUserFile`. **Ningún lead de prueba
enviado a producción.** Commit
`docs(status): v0.92.0 desplegada y verificada en produccion`.

---

## 5. Backlog (fuera de esta rama)

| Qué | Evidencia | Por qué no ahora |
|---|---|---|
| Email obligatorio en `/contact` | su `Field` no lleva `required`; el backend lo rechaza sin email | scope: el dueño pidió apellido |
| Test que cruce las claves `contact.*` y `landing.form.*` con `find_violations` (Fair Housing) y con `/eko/i` | `test_calculator_copy.py` solo barre `calculator.*` | copia trivial hoy; la guarda vale cuando crezca |
| Apellido como columna propia | §2.1 | solo si el panel llega a necesitar ordenar o saludar por nombre de pila |

## 6. Riesgos anotados

- **Dos campos obligatorios más en un formulario cuyo tráfico viene de un
  Short en el móvil cuestan conversión**, y el que abandona no aparece en
  ningún informe. El dueño lo decidió con el dato delante; queda escrito
  para poder revisarlo con números si el ritmo de leads cae.
- El 308 lo cachea el navegador: una pública en el host del panel deja de
  verse hasta vaciar caché.
- `origin/main` puede moverse entre la Fase 0 y la 5 (la sesión par trabaja
  en el mismo repo). Antes del bundle, `git fetch` y comprobar que
  `2588c2c` sigue siendo el HEAD del VPS y que la rama contiene lo que haya
  llegado a `main`; si no, rebasar y repetir §3.
- Si la sesión par no responde al número de versión, la Fase 4 **espera**; no
  se escribe `0.92.0` por suposición.

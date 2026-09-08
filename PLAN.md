# PLAN.md — El CTA que falta en `/calculator`, y la guarda que no lo vio

> **Ejecutor:** una fase a la vez; implementa, valida, cierra. Cada número sale
> de una salida pegada. Un verde que no se ha puesto rojo con una mutación no
> cuenta. **En este repo no se cuenta ni se concluye con `grep` ni `cat`**: el
> proxy `rtk` reescribe su salida (ver §1.2).

## 1. Contexto

### 1.1 El defecto

`/calculator` mide «llegó al formulario» y **nunca** «pulsó para ir», porque no
hay nada que pulsar. Medido con `python3` sobre `main` (`f16afbe`):

| Fichero | `id="consult"` | `href="#consult"` | `data-track` |
|---|---|---|---|
| `app/calculator/page.tsx` | **1** | **0** | **0** |
| `components/landing/Landing.tsx` (la home) | 1 | 3 | 5 |

`LandingTracker.tsx:143` dispara `cta_click` **solo** cuando
`href === "#consult"`, etiquetándolo con `data-track`. Sin ancla, el evento es
inalcanzable: no es que se pierda un dato, es que la página tiene una sección de
formulario a la que **el visitante no tiene forma de saltar** después de ver su
cifra. El embudo lo refleja como si nadie quisiera hablar.

**Por qué nadie lo vio:** `track.test.ts:339-343` exige que cada ancla `#consult`
lleve su `data-track`, pero **solo lee `Landing.tsx`**. Una página sin ninguna
ancla pasa la guarda por vacuidad.

### 1.2 La norma de método

El proxy `rtk` **reescribe la salida** de las herramientas sin avisar, por dos
vías distintas, las dos medidas el 8-sep:

- `cat -n frontend/middleware.ts` imprimió **68 líneas** donde `wc -l` dice
  **119**: elimina los bloques de comentarios. En este repo eso es grave — la
  mitad de las decisiones de diseño viven ahí, y la auditoría de cierre de la
  v0.92.0 encontró seis afirmaciones falsas, **todas dentro de comentarios**.
- `grep CONTENT_SLOT docker-compose.yml` devolvió **solo** las coincidencias de
  `.env.example`, y llevó a concluir que compose no declaraba esas variables.

**La prueba de un segundo:** `wc -l` frente a lo que imprimió `cat`.
**La norma:** para leer o contar, `Read`, `sed -n` o `python3`.

Ya está en memoria. Esta rama la escribe además donde la ve quien trabaje en el
repo, que es el sitio que faltaba.

## 2. Alcance

**Dentro:** el ancla que falta en `/calculator` con su `data-track`, sus cadenas
EN/ES, extender la guarda de `track.test.ts` a cualquier página pública con una
sección `#consult`, y la norma de método en `CLAUDE.md`.

**Fuera:** `app/fall/page.tsx` y `next.config.js` — **son de la sesión
`Viral Videos DHS`**, que trabaja en `feat/otono-2026`. No se tocan. Tampoco se
cambia el diseño de la sección `#consult` ni la aritmética.

**Versión: 0.94.0** (la 0.93.0 está reservada por esa sesión). A confirmar con
ella antes de escribirla.

## 3. Fases

### Fase 0 — rama y verde de referencia
Rama `feat/f1-cta-calculator` desde `origin/main` (`f16afbe`). Correr los cuatro
bloques y anotar los números. Referencia esperada: backend **1779**, vitest
**379**.

### Fase 1 — el ancla, sus cadenas y la guarda
- `app/calculator/page.tsx`: un `<a href="#consult" data-track="result">` **dentro
  del bloque que solo se renderiza cuando hay cifra** y `cappedBy !== "floor"` —
  un CTA que dice «hablemos de esto» sin un «esto» no significa nada. Altura
  táctil ≥ 44 px, como los chips.
- `lib/i18n.tsx`: `calculator.result.cta` en **EN y ES**, junto a las
  `calculator.result.*` que ya existen, mismo orden en las dos secciones.
- `lib/__tests__/track.test.ts`: la guarda pasa a recorrer **las páginas públicas
  que declaran `id="consult"`** y exige, para cada una, (a) al menos un ancla
  `href="#consult"` y (b) que todas lleven `data-track`. Es lo que convierte
  «ningún ancla» de aprobado-por-vacuidad en rojo.
- `CLAUDE.md`: la norma de §1.2.
- **Mutaciones:** quitar el `data-track` → rojo; quitar el ancla entera → rojo
  (es la que antes pasaba); dejar la página sin `id="consult"` → la guarda no
  debe exigirle nada, y `/fall` en `main` es el caso real que lo comprueba.

### Fase 2 — versión y estado
`config.py`, `version.ts` (constante + entrada), `CHANGELOG.md`,
`PROJECT_STATUS.md`. Con el número confirmado, no antes.

### Fase 3 — pre-despliegue y parar
Bundle, checklist, reversión. **No se despliega sin autorización del dueño.**

## 4. Verificación

Local: `tsc`, `vitest`, `next lint`, `next build`, prerender, `pytest`, `ruff`.
**En navegador real** (Playwright, iPhone 13 y escritorio): que el ancla exista
tras escribir una renta y un ahorro, que **no** exista con el formulario vacío,
que al pulsarla el desplazamiento acabe en la sección del formulario, y que el
alto táctil sea ≥ 44 px. En producción, tras desplegar: la cifra y el enlace
presentes en el HTML servido.

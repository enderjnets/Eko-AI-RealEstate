# PROJECT STATUS

Estado de ejecución del plan `~/.claude/plans/si-haz-el-plan-jazzy-sifakis.md`
(**v0.55.0 — el Estudio de Contenido, encontrable y usable**). Es un estado, no
un diario. La v0.54.4 quedó cerrada y desplegada el 26-ago-2026; su historial
vive en el plan y en git.

## Contexto en una línea

El dueño buscó en el panel «la parte donde se controlan los vídeos» y no la
encontró: existe, pero el menú la llama «Today» y la cola está enterrada al
fondo de esa página. Al investigarlo apareció algo peor: **`brokerage_line` no
tenía puerta de entrada** — el modelo lo tiene y dos puertas lo exigen, pero la
API lo rechazaba con 400 y no había campo en Ajustes.

## Fases

| # | Fase | Estado |
|---|---|---|
| 1 | `brokerage_line` tiene por fin una puerta (API + Ajustes) | ✅ completada |
| 1b | `booking_contact_email` se guarda (fuera de plan, pedido por el dueño) | ✅ completada |
| 2 | Contenido sale del escondite (`/content` + menú + tema oscuro) | ✅ completada |
| 3 | El vacío explica por qué está vacío (`/content/status`) | ⏳ pendiente |
| 4 | Subir el clip desde el teléfono + bump v0.55.0 | ⏳ pendiente |

Rama única: `feat/estudio-visible`. **Sin commits a `main`. Sin despliegue.**

---

## Fase 1 — la puerta de `brokerage_line` (completada)

**Commit:** `c16487e` en `feat/estudio-visible`.

### Checklist de "terminado" — resultado real

| # | Criterio | Resultado |
|---|---|---|
| 1 | Tests en verde, sin saltados | ✅ **1014 passed** en 98 s, base recreada desde cero. Cero `skipped` |
| 2 | Lint / typecheck | ✅ `ruff check app tests` → *All checks passed!* · `npx tsc --noEmit` → sin salida · `npx vitest run` → **90 passed** |
| 3 | Build compila | ✅ `docker build -f backend/Dockerfile` → exit 0 · `npx next build` → *Compiled successfully*, 16/16 páginas |
| 4 | Cobertura del código nuevo | ✅ `settings.py` main **82%** → rama **83%**; `content_render.py` main **86%** → rama **86%** (mismas 20 líneas sin cubrir). Medido en un `git worktree` de main |
| 5 | Sin secretos ni endpoints internos | ✅ barrido del diff con grep de claves/tokens/IPs internas → cero coincidencias |
| 6 | Entrada validada, errores manejados, sin prints | ✅ `max_length=200` = `String(200)`; blanco-o-espacios se normaliza a `NULL`; endpoint bajo `require_admin`; sin `console.log` ni `print` en el diff |

### Verificación en el mundo real (no inspección visual)

- **Mutación obligatoria**: quitar `brokerage_line` de `SettingsPatch` pone
  **2 tests en rojo** (`test_put_updates_brokerage_line`,
  `test_put_brokerage_line_can_be_cleared`) — que es exactamente el bug que
  existía: `extra="forbid"` devolvía 400. Restaurado y verde otra vez.
- **Round-trip por HTTP real** contra un backend local: GET → PUT
  `"Natalia & Robbie · Engel & Völkers Aspen"` → GET, con `·` y `ö` intactos.
- **Navegador**: escrito el valor en Ajustes → *Save changes* → verificado
  **en Postgres**, no en pantalla. Y el camino inverso: vaciar el campo y
  guardar deja `NULL`, con lo que la puerta lee `""` → **CERRADA**.

### Decisiones y por qué

- **Sin `min_length` en `brokerage_line`**: mandar `""` es como un broker lo
  borra, y debe poder hacerse sin endpoint especial. Las dos puertas ya tratan
  blanco-o-espacios como "sin poner" (`content_render.py`, `content_studio.py`).
- **Corregida la entrada v0.52.0 del changelog de la app** (`version.ts`): decía
  al cliente que el campo «vive ahora en Ajustes» cuando no existía puerta. Ese
  changelog es UI viva, no historia.
- **`backend/.coverage` desrastreado y gitignorado**: se había colado en el
  commit `6d90380` de la v0.54.4 — contaminación de artefactos causada por el
  propio checklist que obliga a medir cobertura. Las fases 2–4 vuelven a medir.

### Auditoría de cierre — 1 bloqueante, corregido en esta fase

🔴 **BLOQUEANTE (corregido): un apóstrofo mataba todos los clips en cola, para
siempre.** `_escape_drawtext` escapaba `'` como `\'` y luego interpolaba el
resultado **dentro de comillas simples** (`text='...'`), donde ffmpeg copia los
backslashes literalmente: el primer apóstrofo cerraba la comilla y el resto del
grafo se reinterpretaba como sintaxis de filtro. Y al fallar, `render_pending`
estampa `rendered_at` y **nada lo reinicia jamás** (`content_render.py:269`), así
que "O'Brien Realty" no rompía un render: mataba de forma permanente todos los
clips encolados. Latente hasta ahora porque el campo era inescribible; **esta
fase es lo que permitía teclearlo**.

Arreglo, elegido tras medir en vez de razonar: escapar sin comillas arregló
`'` `:` `%` `\` `"` `&` `$` **y seguía muriendo con `,` `;` `[` `]`** — y
"Smith & Jones, Realty, Inc." es como se llaman las brokerages. Cada ronda
arreglaba los caracteres pensados y dejaba los no pensados, así que el texto
pasó a **`textfile=`**: ffmpeg lee los bytes literales y no queda micro-lenguaje
para la entrada del operador. Solo la ruta entra en el grafo, y se escapa igual
(`_escape_graph_path`) porque "la ruta es segura" es la forma de suposición que
produjo el bug. Verificado con ffmpeg real sobre 7 nombres hostiles, uno de
inyección incluido.

**El test que lo dejó pasar, sustituido.** El anterior afirmaba la *forma* del
escapado — exigía que se produjera `\'`, la codificación que rompe — y estaba
verde con la función rota, porque ninguna prueba mandó nunca un apóstrofo a
ffmpeg. **Y la mutación destapó un fallo en mi propio arreglo**: con el módulo
mutado el texto salía **vacío** y los tests de entradas hostiles pasaban igual,
porque solo miraban dimensiones — un vídeo sin identificación es exactamente lo
que Colorado prohíbe. Añadido `test_the_brokerage_text_actually_reaches_the_pixels`
(dos nombres → dos end-cards distintas). La mutación pone hoy **3 tests en rojo**.

Otros hallazgos corregidos en fase: la ayuda i18n prometía que el motivo se ve
en Contenido (`render_error` no está expuesto — pasa a Fase 3); el changelog
prometía "ships in v0.55.0"; el test de vaciado probaba `""` cuando la UI manda
`null`; `_restore` no comprobaba fallos; sin test de 201 caracteres → 422.

### Hallazgos abiertos (backlog, no bloquean)

- 🟠 **IMPORTANTE, PREEXISTENTE — un render fallido es irreversible.**
  `render_pending` estampa `rendered_at` en cualquier fallo y la consulta solo
  toma `rendered_at IS NULL`; nada lo reinicia. Un fallo transitorio (disco
  lleno, OOM) mata el clip igual que uno permanente. Hace falta distinguir
  "no se pudo ahora" de "no se podrá nunca".
- 🟡 **MENOR — un byte NUL da 500 en vez de 422.** `{"brokerage_line": "A\u0000B"}`
  pasa Pydantic y revienta en asyncpg. Preexistente en todos los campos de texto.
- 🟡 **MENOR — skew de despliegue**: con `extra="forbid"`, un frontend nuevo
  contra un backend viejo devuelve 422 para **todo** el formulario. Riesgo bajo:
  compose levanta ambos juntos.
- 🟠 **IMPORTANTE, PREEXISTENTE — el nav de escritorio no cabe entre 768 y
  1279 px**: desborda 380/248/132 px a 768/900/1024. Se muestra desde `md` pero
  solo cabe desde `xl`. El arreglo real es que el nav de escritorio empiece en
  `xl` y el tab-bar cubra la tablet — lo que exige meter «Hoy» (`/console`) en
  el tab-bar, que hoy no está. No se puede contener con `overflow` (rompe el
  desplegable del Inbox: ver Fase 2).
- 🟡 **MENOR — el tab-bar elide etiquetas en pantallas pequeñas** con las 7
  pestañas del operador: a 375 px «Contenido» (por 1 px) y «Propiedades»; a
  320 px cuatro de siete. Sin desbordamiento de página; el icono identifica.
- 🟡 **MENOR — `/docs` sin acceso por debajo de 1280 px**: es su único enlace
  en toda la interfaz y ahora es `hidden xl:inline-block`.
- 🟡 **MENOR — suciedad entre tests**: `test_content_gate_is_absolute.py` deja
  `brokerage_line` con su constante en vez de `NULL`.

## Fase 1b — `booking_contact_email` se guarda (completada)

**Commit:** `87541ed` en `feat/estudio-visible`. Fuera del plan: salió de la
auditoría de la Fase 1 y el dueño pidió arreglarlo antes de seguir.

El input existía desde que se añadió el campo y **nunca estuvo en el payload de
`handleSave()`**. El fallo era silencioso en la peor forma: el PUT sale, devuelve
200, aparece «Guardado ✓», y acto seguido `setData(updated)` sobrescribe el
estado local con el del servidor — así que **la dirección escrita desaparece de
la pantalla mientras la página dice que guardó**. Sin ella, Cal.com no puede
agendar a un lead que solo dejó teléfono, que son la mayoría.

**Verificado rompiéndolo, en el navegador contra Postgres:**

| | PUT | valor en la BD |
|---|---|---|
| con el bug reintroducido en vivo | sí, 200 | `None` — descartado en silencio |
| con el arreglo | sí, 200 | `'visitas@ejemplo-verificacion.com'` |

**La guarda no es para este campo, es para el siguiente.** Un test de este campo
habría sido un test del bug de ayer. `frontend/lib/__tests__/settingsFormWiring.test.ts`
afirma la FORMA: el conjunto de campos pasados a `set(...)` y el conjunto de
claves del payload de `settingsApi.update({...})` deben ser iguales. Quitar la
línea del arreglo pone el test en rojo **nombrando el campo**. Incluye un test
de cordura (si los regex dejan de casar, dos conjuntos vacíos serían "iguales"
y no probarían nada).

Checklist: **1014 backend** + **92 frontend** verdes · `tsc` sin errores ·
`next build` *Compiled successfully* · diff de 1 línea sin secretos.

## Fase 2 — Contenido sale del escondite (completada)

**Commit:** `PENDIENTE_2` en `feat/estudio-visible`.

`ContentQueue` movido a `components/content/`, página propia `/content`, quitado
de «Hoy», restyleado del tema claro al oscuro, y entrada «Contenido» en el nav
de escritorio **y en el tab-bar del móvil** (el clip se graba y se sube ahí).

### Checklist — resultado real

**1014 backend** + **92 frontend** verdes · `ruff`/`tsc` sin errores ·
`next build` *Compiled successfully* con `/content` en la tabla de rutas ·
diff sin secretos · sin `console.log`.

### Verificado en navegador, con datos sembrados

Los cinco estados que un grep no puede ver, renderizados a 500 px (móvil real):
cola de aprobación, borrador con la caja de Fair Housing en ámbar nombrando las
4 frases, editor en línea, campo de motivo de rechazo, y pieza rechazada. La
puerta devolvió **422** al intentar enviar a aprobación la pieza que viola Fair
Housing. Datos de prueba borrados después.

### Auditoría de cierre — 1 bloqueante, corregido en fase

🔴 **BLOQUEANTE (mío, corregido): `overflow-x-auto` en la fila de enlaces
rompía el desplegable del Inbox en TODAS las páginas.** Lo añadí para contener
un desbordamiento horizontal. Por CSS, en cuanto `overflow-x` deja de ser
`visible`, **`overflow-y` computa a `auto`**: el contenedor recorta en ambos
ejes y el desplegable vive dentro de él. Medido en la app real: menú de 402 px,
**0 px visibles**, y un clic sobre él lo recibía `MAIN`. Agravante: ocultar la
barra de scroll —también mío, para ganar espacio— **borraba la única pista
visual** del recorte. Retirado; ahora `overflow-y: visible`, el menú sale
410 px fuera de la fila y el clic lo recibe el menú.

🟠 **Dos regresiones de contraste, mías, corregidas**: los placeholders del
editor **son los únicos rótulos** de esos campos (no hay `<label>`) y quedaron
a **2,37:1** → ahora **7,04:1**; el botón Aprobar a **2,54:1**, peor que el
3,30:1 que sustituyó → texto oscuro sobre el verde de marca, **7,74:1**.

### Lo que NO se arregló, medido en vez de inferido

El nav ocupa **845 px frente a 865 px antes de estos cambios** — 20 px menos,
con un elemento más (padding `px-2 xl:px-3` y `API` reservado a `xl`). Por
tanto el desbordamiento a **768 px (380), 900 (248) y 1024 (132)** es
**preexistente** y queda ligeramente mejor. Arreglarlo de verdad es rediseñar
la navegación de tablet: ver backlog.

### Siguiente paso concreto

Fase 3: `GET /api/v1/content/status` + estado vacío que nombra la causa +
exponer `render_error` (hallazgo de la Fase 1) + chips por plataforma.

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
| 4 | Subir el clip desde el teléfono + bump v0.55.0 | ✅ completada |

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

**Commit:** `3c3b296` en `feat/estudio-visible`.

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

## Fase 3 — el vacío explica por qué está vacío (completada)

**Commit:** `e51cda2` en `feat/estudio-visible`.

`GET /api/v1/content/status` (booleanos + conteos, sin valores de configuración),
`render_error` expuesto y pintado por fin, chips por plataforma, y un diagnóstico
que nombra las causas reales en vez de «no hay nada aquí».

### Checklist — resultado real

**1020 backend** (base recreada, cero saltados) + **92 frontend** · `ruff`/`tsc`
limpios · `next build` OK · cobertura `content.py` 63%→64%, `content_studio.py`
100%→100% · diff sin secretos.

### Verificado rompiéndolo

- **El instrumento discrimina**: con la brokerage vacía el diagnóstico lista esa
  causa; al ponerla **desaparece**. Mutar `brokerage_line_set` a `True` pone un
  test en rojo; mutar `PUBLISHING_AVAILABLE` a `True`, otro.
- **El caso que el auditor describió**, en navegador: pestaña «Rechazados» vacía
  con 3 piezas en otra → «Nada en esta pestaña — pero hay 3 pieza(s) en las
  otras», en vez de culpar a la configuración.
- **Control positivo**: con todo encendido y piezas en pantalla, la caja
  **desaparece**. Ya no es un banner permanente.

### Auditoría de cierre — 1 bloqueante (en mi propio test), corregido

🔴 **BLOQUEANTE: mi helper de test borraba la línea de brokerage de TODAS las
organizaciones.** `UPDATE agent_settings SET brokerage_line = :v` **sin
`WHERE`**, sobre una sesión *bypass* que la RLS no frena, y el `finally` las
dejaba a `NULL` en vez de restaurar. En una base con datos reales, correr la
suite dejaba `render_pending` rechazando todos los clips — una avería que se lee
como bug de producto. Ahora lee el valor previo, filtra por `org_id` y lo
devuelve.

**Multi-tenant (la sospecha que yo mismo levanté):** el auditor verificó la
cadena completa y **la RLS sí cubre las dos consultas** en la configuración
soportada. Pero con `DATABASE_URL_APP` vacío la app conecta como dueño, la RLS
no aplica, y el arranque **tolera** ese estado con una org real + la demo: ahí
un `.first()` sin filtro devuelve la fila que Postgres quiera, y el panel podría
decirle a un admin que le falta la identificación legal teniéndola. Filtrado
explícito + el mismo rechazo ruidoso que `settings.py` cuando no hay org atada.

**Dos de mis cinco tests no podían ponerse rojos**: uno comparaba la salida del
endpoint contra **la misma constante que el endpoint lee**; el otro prometía
verificar el orden de rutas, que aquí no es determinante. Corregidos y
verificados por mutación.

**Otros corregidos en fase**: la caja era global pero el vacío es **por
pestaña** (`counts` llegaba en la misma respuesta y no lo usaba nadie); el
enlace «Ponerla en Ajustes» era un muro para roles `member`; `render_error`
filtraba el `stderr` de ffmpeg con rutas internas a cualquier autenticado — y
**mi cambio es el que lo puso en pantalla**; y el `hasattr(status,"value")` era
rama muerta que, de dispararse, habría escrito una clave inventada.

## Fase 4 — subir el clip desde el teléfono (completada)

**Commit:** `b78aba5` en `feat/estudio-visible`. Bump a **v0.55.0**.

`contentApi.upload` con `XMLHttpRequest` (no `fetch`: no puede reportar
progreso de subida en ningún navegador, y el caso de uso es un teléfono con
datos móviles mandando cientos de MB), `UploadClip.tsx` sin atributo `capture`
—con él el móvil fuerza la cámara y no deja elegir de la galería, que invierte
el flujo real—, y el clip aterriza en Borradores.

### Checklist — resultado real

**1022 backend** (base recreada, cero saltados) + **101 frontend** · `ruff` y
`tsc` limpios · `next build` OK · cobertura `content.py` 63%→64% · versión
0.55.0 en los tres sitios con paridad atada por test · diff sin secretos.

### Verificado en navegador, no por inspección

Subida real de un clip de 2,1 MB desde la interfaz, y **hash del fichero en
disco idéntico al original** — la prueba de que el cuerpo crudo llegó intacto.
Un `FormData` habría escrito bytes multipart como si fueran el vídeo y habría
devuelto 201 igual. Un PDF devuelve `API 415: Expected a video file (...)` y
**no deja fichero huérfano**.

Siete mutaciones, siete tests muertos: `FormData` en vez de cuerpo crudo ·
quitar `encodeURIComponent` (los clips se llaman `IMG_0421 (1).mov`) · quitar
el progreso · volver a `statusText` · quitar el timeout · quitar la guarda de
`total > 0` · quitar el tope de 100.

### Auditoría de cierre — 0 bloqueantes; 4 hallazgos míos corregidos

Los cuatro vectores de seguridad, descartados **con prueba**: del `filename`
solo sobrevive el sufijo y el fichero se guarda como UUID (traversal
imposible); `viewer` recibe 403 en backend; cookie `samesite=lax` corta CSRF;
`org_id` se estampa en `before_flush`.

- **Carrera introducida por mí**: al saltar a Borradores quedaban dos cargas en
  vuelo sin guarda y la vieja podía ganar. `lib/latestWins.ts` existía para
  esto, con un docstring que describe este daño, y no lo usé. Aplicado.
- **El mensaje de error se quedaba vacío en el camino más probable**: bajo
  HTTP/2 `statusText` es `""`, así que un 413 de proxy se leía `"API 413: "`.
  Y **mi propio test lo bendecía** al comprobar `/413/` con regex en vez del
  mensaje entero. Ahora `xhrDetail` cae al cuerpo crudo, como `errorDetail`.
- **La barra se quedaba pegada para siempre** sin timeout ni salida — en la
  situación exacta para la que existe la barra. Timeout de 10 min + clave
  traducible.
- **El CHANGELOG afirmaba un mecanismo inventado**: «verificado con un hash
  byte a byte». La comprobación la hice yo a mano; el test no existía. Ahora
  cita `test_upload_stores_the_clip_and_serves_it_back`, que sí compara.
- Menores corregidos: `NaN%` con fichero de 0 bytes, botón de subir oculto para
  `viewer` (convención del repo), y los textos de fallo del cliente por i18n.

### Backlog nuevo (no bloquea)

- Cloudflare puede cortar el cuerpo muy por debajo de 500 MB en planes
  no-Enterprise: **verificar contra el plan real** antes de prometer 500 MB por
  el túnel. No hay comprobación de tamaño en cliente.
- Fichero huérfano si falla el commit tras el streaming (preexistente, ahora
  alcanzable desde la UI). Sin rate limit ni cuota por organización.
- Los botones aprobar/rechazar tampoco están ocultos para `viewer`
  (preexistente).

### Estado de producción

**✅ v0.55.0 DESPLEGADA y verificada el 26-ago-2026.** `/api/v1/health` →
`0.55.0`, `/content` → 200, los cuatro workers arrancados sin errores, sin
migraciones que aplicar (verificado: 0 ficheros en el diff), y
`CONTENT_STUDIO_ENABLED` / `CONTENT_RENDER_ENABLED` **siguen en `false`** —
esta versión no enciende nada. `GET /content/status` devuelve 401 a un anónimo.

**✅ v0.55.1 DESPLEGADA** (`9c46d62`, tag subido): corrige la cifra de subida
publicada. `/api/v1/health` → `0.55.1`, cero errores en el log, y verificado en
el bundle servido que no queda ninguna afirmación de «500 MB» — la única
mención que sobrevive es la frase de la corrección explicando lo que decíamos.

**🔴 Ajustes: el texto entró en el campo equivocado.** El dueño escribió
`Engel & Völkers Aspen` en **`agency_name`**, no en `brokerage_line`. Un solo
PUT en el log, `updated_at` 21:15. Consecuencias: los vídeos **siguen sin poder
renderizarse** (la puerta lee `brokerage_line`, que sigue vacío), y el asistente
ahora se presenta a los leads como «Engel & Völkers Aspen» — más correcto que
antes, pero no era lo buscado. Los dos campos son confundibles: `agency_name` va
primero en la misma caja. **Backlog: separarlos o renombrarlos.**

**🔴 Fallo vivo encontrado de rebote:** el saludo dice *«...and which area of
Miami»* — resto de los datos de demostración. Estas agentes son de Denver/Aspen.
Cualquier lead que escriba hoy recibe eso.

### El límite de subida, medido contra producción

```
 99 MB -> HTTP 401  (respondió nuestro backend: Cloudflare lo dejó pasar)
120 MB -> HTTP 413  (respondió Cloudflare en el borde)
```

**El túnel corta en ~100 MB, no en los 500 del ajuste.** Salió como sospecha de
la auditoría de la Fase 4 —que dijo explícitamente «verifícalo, no lo leí de una
fuente»— y por eso se midió. Las pruebas no crearon ninguna fila.

### Pendiente de una persona (no de código)

Con `AUTH_ENABLED=true`, tres comprobaciones necesitan sesión y el agente no
maneja contraseñas:

1. **Ajustes** → escribir `Engel & Völkers Aspen` en «Identificación de la
   brokerage». Decidido el 26-ago: es el texto de la firma de Natalia y el único
   de tres candidatos que **cabe** en el ancho del vídeo (los otros tocan los
   bordes o se cortan; renderizado con el código real).
2. **Contenido** → tras el paso 1, la causa «no hay identificación de la
   brokerage» debe **desaparecer**. Si no, el diagnóstico es decoración.
3. **Inbox** → abrir el desplegable en escritorio y comprobar que se ve entero.
   Se rompió durante la Fase 2 y ningún test lo cubre.

### Backlog abierto

- **Sin comprobación de tamaño en el navegador**: un clip de 4K sube ~100 MB y
  recibe HTML de Cloudflare en vez de una frase. `CONTENT_UPLOAD_MAX_MB=500`
  produce un 413 propio que el túnel hace inalcanzable: texto muerto.
- Nav de escritorio no cabe entre 768 y 1279 px (preexistente, 20 px mejor).
- Un render fallido es irreversible aunque el fallo sea transitorio.
- Fichero huérfano si falla el commit tras el streaming; sin rate limit por org.
- Botones aprobar/rechazar visibles para `viewer` (preexistente).
- `/docs` sin acceso por debajo de 1280 px.

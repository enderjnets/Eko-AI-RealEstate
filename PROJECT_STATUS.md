# PROJECT STATUS

Estado de ejecución del plan `~/.claude/plans/si-haz-el-plan-jazzy-sifakis.md`
(**el embudo Denver Home Story**). Es un estado, no un diario: el historial de
v0.56.0 y anteriores vive en git y en el plan.

---

## 🟢 EN CURSO — la analítica del embudo (`PLAN.md`, rama `feat/analitica-embudo`)

### ✅ F1 — eventos de la landing: esquema + endpoint público · `de15475`

> **Sin desplegar.** El checkpoint A necesita también F2 (el tracker): F1 sin
> emisor no recoge nada y F2 sin F1 escribe contra un 404.

**Checklist, con la salida real** (base `eko_test_analitica`, recreada):

| Comprobación | Resultado |
|---|---|
| `pytest` desde base recreada | **1469 passed**, 0 failed, **0 saltados**, 4:35 |
| `ruff check app tests` | All checks passed |
| `tsc --noEmit` · `vitest run` | limpio · **200 passed** (frontend intacto en esta fase) |
| `docker build -f backend/Dockerfile` | exit 0 |
| Cobertura, ficheros nuevos | `landing_analytics.py` **96,8 %** · `models/landing.py` **96,5 %** |
| Cobertura, `public.py` | **94,4 %** frente al 89,8 % de partida — ver la nota de medición |
| Cobertura total | 80,8 % → **81,1 %** |
| Secretos / depuración en el diff | ninguno (barrido por forma sobre las líneas añadidas) |

⚠️ **Nota de medición, porque el número desnudo engaña.** Con el arnés que usa
el repo, `public.py` aparenta bajar de 89,8 % a 83,7 %. Es un artefacto:
`coverage` no traza lo que corre dentro del greenlet de SQLAlchemy, así que en
un handler `async` **todo lo que va después del primer `await db.execute(...)`
sale como no cubierto aunque los tests demuestren que escribe filas**. Medido
con `concurrency = greenlet`, el mismo fichero da **94,4 %**, y las 17 líneas
que quedan son 15 preexistentes (interiores del limitador, los `except` de
`capture`, el `ValueError` de la ruta de medios) y 2 defensivas nuevas. El
mismo artefacto explica el «62 %» de `analytics.py` en el diagnóstico del plan.

**Qué entra**: migración **051_landing_sessions** (dos tablas con RLS
`ENABLE`+`FORCE`, política y GRANT), `models/landing.py`,
`services/landing_analytics.py` (clasificación pura + purga),
`POST /api/v1/public/landing`, `session_id` en `POST /api/v1/public/leads`,
tres settings nuevos en sus tres sitios de cableado, la purga colgada del tick
del monitor, y 79 tests nuevos en cuatro ficheros.

**Mutaciones verificadas** (guardar, mutar, ver rojo, restaurar, md5 idéntico):
compartir el presupuesto de la captura · quitar `FORCE ROW LEVEL SECURITY` ·
quitar el estampado explícito de `org_id` en el INSERT core · borrar el enlace
sesión→lead · desconectar la purga del bucle · quitar el tope diario · volver a
calcular los contadores en Python. **Siete, todas rojas y restauradas.**

### Consultas al advisor

| # | Motivo | Decisión |
|---|---|---|
| 1 | Arranque + puerta de F1 [CRÍTICA] (una sola consulta, cubre los dos disparadores) | Rama `feat/analitica-embudo` según el plan, no `feat/<fase>`, que partiría fases apiladas. Cuatro correcciones aplicadas antes de escribir código: el INSERT core **no** lo estampa `before_flush` (org_id explícito); 8 KB de cuerpo era incoherente con un lote máximo → **16 KB**; **medir el estado real de RLS antes** de escribir la guardia; y el enlace sesión→lead nunca puede romper el 202 |
| 2 | Hallazgo bloqueante de la auditoría: las sesiones no se purgan nunca | **La retención NO es el arreglo** — no acota el abuso y sí destruye el denominador histórico del embudo. El control es un **tope diario de sesiones nuevas por agencia**. La retención de sesiones solo será posible cuando F7 tenga una tabla de agregados. Y para la actualización perdida: **expresiones SQL, no `FOR UPDATE`**, que pondría una espera de bloqueo en un handler público |

### Auditoría de cierre (2 subagentes, revisión de código ya escrito)

**Bloqueante (1), corregido en la fase:** `landing_sessions` no se purgaba y
nada acotaba su número — 8.640 filas permanentes al día desde una sola
dirección, sin captcha. Arreglado con `LANDING_SESSIONS_PER_DAY=20000`, sobre
la **creación** de sesiones y por día local de la agencia; una visita ya
registrada sigue fusionando sus balizas, así que un visitante real nunca se
trunca a medias.

**Importantes (4), corregidos:** actualización perdida en los contadores con dos
balizas concurrentes —`max_scroll_pct` podía **bajar**, justo lo que el
comentario prometía que no— resuelto con expresiones SQL; el 400 no registraba
nada, así que una deriva del tracker habría dejado la tabla a cero en silencio;
el techo global se cobraba **después** de leer y parsear el cuerpo, que es el
fallo que el endpoint hermano documenta como outage pasado; y `session_id` con
`pattern` convertía un fallo del tracker en un **422 que tumbaba el lead** —
exactamente la inversión que ese bloque existe para evitar.

**Menores corregidos:** tipos `BigInteger` del modelo alineados con la
migración y los dos índices compuestos declarados (autogenerate ya no propone
borrarlos); predicado `org_id` en la purga; `commit` incondicional; `path` sin
query string; `form_submit` deja rastro en la sesión; docstring del oráculo
suavizado, porque el tiempo de respuesta **sí** distingue aunque el estado no.

**Al backlog, con motivo:** clave foránea compuesta `(org_id, session_id)`; el
hueco entre el límite de 256 KB del middleware y los 16 KB del handler; la
confianza en las cabeceras `cf-*` y en la IP del cliente, inherente a estar
detrás del túnel; la purga cada 300 s para una retención de 90 días, correcta y
derrochadora; y `MAX_TRACKED_IPS` ahora aplica a dos mapas, así que el techo de
memoria del limitador se dobla a 10.000 entradas.

### Incidencia de coordinación, resuelta

Compartíamos `eko_realestate_test` con la sesión «fix-caption-rendering»: sus
`DROP DATABASE` borraron la migración 051 a mitad de una pasada y produjeron
185 rojos que **atribuí por error** a la opción de cobertura `greenlet`. Se lo
dije como bueno y **lo he retractado**: la opción no está descartada, era el
borrado. Yo me he mudado a `eko_test_analitica` y `eko_realestate_test` queda
para ellos.

### Hallazgos abiertos

- 🔴 **Hueco del plan, decisión del dueño:** F1 gana `LANDING_SESSIONS_PER_DAY`,
  que el plan no contemplaba, y F7 gana una tabla de agregados como requisito
  previo a cualquier retención de sesiones. **No he editado `PLAN.md`.**
- 🔴 **Choque de versión:** el plan reservaba 0.72.0 para el checkpoint A, pero
  la sesión vecina la desplegó anoche. El checkpoint A pasa a **0.73.0**.
- Producción quedó anoche en **`c68aaf7`**, `/api/v1/health` → **0.72.0** (antes
  `02f0ac8` / 0.71.1). Ése es el punto de reversión del checkpoint A.
- La pieza 10 sigue sin vídeo. El botón «Rehacer el vídeo» ya aparece; pulsarlo
  es **acción del dueño** (la sesión vecina no pudo, y yo tampoco debo: exigiría
  fabricar un token de sesión).

### ✅ F2 — el tracker en la landing · checkpoint A cerrado en **v0.73.0** · `5cd543e`

> **Sin desplegar. Autorización pendiente del dueño.**

| Comprobación | Resultado |
|---|---|
| `pytest` desde base recreada | **1474 passed**, 0 failed, **0 saltados**, 4:42 |
| `vitest run` | **228 passed** (eran 200; +28) · `tsc --noEmit` limpio |
| `ruff check app tests` | All checks passed |
| `next build` con las `NEXT_PUBLIC_*` reales | exit 0, y **`/` sigue siendo estática** (`○`) |
| `docker build -f backend/Dockerfile` | exit 0 |
| Secretos / depuración en el diff | ninguno |

**Un intento de corrección gastado**, y el fallo fue real: `useSearchParams()`
en el tracker rompía el `next build` («should be wrapped in a suspense
boundary») y habría dejado la portada fuera del renderizado estático. Resuelto
leyendo `window.location.search` dentro del efecto: el componente no pinta nada
y lee la query una sola vez tras montar, así que el gancho no aportaba nada y
costaba la página entera.

**Mutaciones verificadas** (cinco): ignorar Global Privacy Control · dejar de
recordar la atribución · quitar `session_id` del formulario · montar el tracker
dentro del héroe · quitar las etiquetas `data-track` de las anclas.

### La verificación que importa: un navegador real, no «debería»

Pila local levantada (backend en 8099 contra una base de usar y tirar, frontend
en 3199 con las variables reales) y **Chrome recorriendo la página**: llegar con
`?utm_source=tiktok&utm_content=piece-7`, leer las cuatro secciones, tocar
«llamar», rellenar el formulario y enviarlo. Lo que quedó escrito en la base:

| | escritorio | teléfono (UA de iPhone) |
|---|---|---|
| origen / pieza | `tiktok` / `piece-7` | `tiktok` / `piece-7` |
| dispositivo · navegador | `desktop` · Chrome | **`phone` · Safari** |
| scroll máximo | 75 % | 75 % |
| secciones vistas | las cuatro | las cuatro |
| toques en «llamar» | 1 (`where: hero`) | 1 |
| formulario empezado / enviado | sí / sí | no / no |
| **lead enlazado** | **sí** (`beacon-live@example.test`) | — |

Y el embudo contado como lo contará el informe: **2 visitas → 2 interesados →
2 toques en llamar → 1 empezó → 1 envió → 1 lead**. Repetido tras el cambio de
`useSearchParams`, con resultado idéntico: no se da por bueno lo que ya no es
el mismo código.

🔴 **No medido**: iOS Safari de verdad. La emulación usa su cadena de agente,
que es lo que clasifica el dispositivo, pero `sessionStorage` bloqueado y el
comportamiento de `sendBeacon` en un WebView de Instagram siguen sin
comprobarse en hardware. La primera comprobación real es un teléfono.

### Auditoría de F2 — ⚠️ MÍA, NO INDEPENDIENTE

El subagente **murió por límite de sesión** (429, `rate_limit`) sin emitir un
solo hallazgo: su única salida fue «voy a leer el commit». Así que la auditoría
la hice yo, sobre mi propio código, y **eso vale menos** — un autor es el peor
revisor de sus propios supuestos. Queda etiquetada como tal por si conviene
repetirla con ojos ajenos cuando haya cuota.

**Un hallazgo, y de la peor clase para esta función.** `newSessionKey` llamaba a
`globalThis.crypto.getRandomValues` sin comprobar que exista. En un navegador
sin `crypto` lanzaba **dentro** del `try` de `sessionKey`, cuyo `catch` la volvía
a llamar — lanzaba otra vez, la excepción escapaba del efecto y **se llevaba la
página por delante**. La analítica nunca puede tumbar la landing que mide.
Corregido con un respaldo por `Math.random`: la clave solo necesita ser única
entre las visitas de una agencia en un día, no autentica ni protege nada.
Mutación O verificada.

**Comprobado y sano, con evidencia:**

| Qué | Resultado |
|---|---|
| Recursión de `flush()` | no puede colgarse: `record` vacía a los 25 y cada pasada acorta la cola |
| Temporizador | `disarm()` en `flush`, en `stop` y en la limpieza |
| Simetría de listeners | **4 añadidos, 4 quitados** (era el fallo que corregí antes) |
| Contrato con el servidor | 8 campos enviados, 8 aceptados; **ningún** nombre de evento ni sección fuera del conjunto cerrado |
| `path` | `pathname`, sin query — y el servidor vuelve a recortarla |
| `referrer` | se envía entero, se **guarda solo el host** (`referrer_host`) |
| Honeypot, consentimiento y Turnstile | el diff de `ConsultForm` no toca ni una línea suya |
| `getTracker()` tras desmontar | devuelve `null`; el envío es `?.`, así que no hace nada |

**Menores aceptados, no corregidos:** dos `focus` en el mismo tick podrían
emitir dos `form_start` (el servidor usa `COALESCE`, así que la marca de tiempo
es correcta igual); y `beaconSender` devuelve `true` al entregar a `fetch` sin
esperar la respuesta — es «entregado», no «recibido», y así lo dice su
documentación.

### 🔴 Antes de desplegar el checkpoint A — leer esto

**Mi rama NO contiene la v0.72.0 que se desplegó anoche.** Está apilada sobre
`feat/landing-marca` (0.71.1), mientras que la 0.72.0 vive en
`feat/maquina-de-video-dhs` (`c68aaf7`). Desplegar esta rama tal cual
**revertiría el arreglo de la puerta de la marca**. Antes del despliegue hay que
integrar `c68aaf7` en esta rama — y eso es un merge, que **no hago sin pedirlo**.

### Runbook del checkpoint A (preparado, no ejecutado)

1. Integrar `c68aaf7` en `feat/analitica-embudo` (**pedir permiso**) y correr la
   suite otra vez sobre el resultado. **Los conflictos ya están medidos en seco**
   (`git merge-tree`): son exactamente tres, y ninguno de código —
   `backend/app/config.py`, `frontend/lib/version.ts` y `CHANGELOG.md`, los tres
   solo por la línea de versión. Resolución: **gana 0.73.0** y se conservan las
   dos entradas de changelog, la de 0.72.0 debajo de la de 0.73.0. Alternativa
   más limpia para producción, decisión del dueño: rebasar mis dos commits
   **encima** de `c68aaf7`, que deja un historial lineal pero reescribe una rama
   ya empujada.
   ⚠️ **`git reset --hard c68aaf7` solo sirve como reversión DESPUÉS de esa
   integración**; hoy `c68aaf7` no es antepasado de esta rama.
2. Copia del `.env` del VPS: `cp .env .env.bak.$(date +%Y%m%d)_v0730`.
3. Bundle → `scp ender-vps:/tmp/eko.bundle` → `git fetch` + `merge --ff-only`.
4. `docker compose build backend frontend` — **el frontend hay que reconstruirlo**
   aunque no haya variables nuevas: el tracker es código de cliente.
5. **Migrar con la imagen nueva**: `docker compose run --rm -T backend alembic
   upgrade head` → debe dejar `051_landing_sessions`.
6. `docker compose up -d backend frontend`.
7. Verificar por el dominio público: `/api/v1/health` → **`0.73.0`**; abrir
   `https://www.denverhomestory.com/?utm_source=tiktok` desde un teléfono y
   comprobar en la base que aparece la fila con `source='tiktok'` y `country`
   no nulo (si `city` es nula, falta el clic de Cloudflare — decisión 4 del plan).
8. **Reversión**: `git reset --hard c68aaf7` + rebuild. ⚠️ **No hacer
   `alembic downgrade`**: borraría lo ya recogido, y el código viejo convive sin
   problema con las tablas nuevas.

### ✅ RESUELTO — el carril de vídeo vuelve a tener imágenes (rama `fix/imagenes-fal`)

> 4-sep, `f0a2ba5` + `643ebff`, **no fusionado**. El obrero del ROG corre este código ya.

**El diagnóstico heredado era correcto y el mecanismo que yo supuse no.** Dije
que `fetch()` no podía tumbar un trabajo porque degrada a tarjeta de marca, y
me faltó leer `produce.py:357`: un guard deliberado exige **al menos una**
imagen real y lanza `ValueError` cuando ninguna escena la consiguió. Ése es el
error del diario, once veces, cada una detrás de una narración ya pagada.

**La causa raíz no era una clave borrada.** El instalador sí vació las tres,
pero la de Kling ya no se podía reponer: esa cuenta pasa a emitir **una sola
API key** (`api-…`) y `pictures.py:90` firmaba un JWT con el par
`ACCESS_KEY`/`SECRET_KEY`, el esquema que se retira. Con el access vacío no
llamaba a nadie. Medido en vivo: la clave nueva responde `200 code=0` como
Bearer directo.

| Medición | Resultado |
|---|---|
| Pexels desde el ROG | `http=200` |
| Kling, api key nueva como Bearer | `http=200`, `code=0 SUCCEED` |
| fal.ai desde el ROG | `http=200` |
| `pictures.fetch()` real en el ROG | **`fal`**, JPEG de 775 293 bytes (`ffd8ffe0`) |
| **Vídeo completo, trabajo 11** | **entregado el 4-sep 05:54**, las **5 escenas con `fal`**, marca de agua presente (correlación 0,975), **0 errores y 0 avisos**, 88 s de principio a fin |
| **Juicio del dueño sobre ese vídeo** | **«se ve bien»** — visto entero el 4-sep. Es lo único que ningún test da: que las cinco imágenes digan lo que dice el guion |
| Pieza 10 en la cola | aprobada por el dueño a las 06:05, **programada en Buffer** (TikTok 5-sep 08:30, Instagram y YouTube el 6). Pieza 9 sale antes: **TikTok hoy 08:30** |
| `worker/tests` | **85 verdes**, 0 saltados |
| ruff en los ficheros tocados | 9 antes, **9 después** — ninguno nuevo |
| Mutaciones | 4, todas rojas y restauradas por md5: quitar la rama de fal en `fetch`; quitar la puerta de la clave; que el 403 no agote el día; cobrar antes de que fal acepte |

Qué cambia: **fal.ai primero**, Kling **sólo** cuando no hay `FAL_KEY` (los
proyectos vecinos aún tienen un par válido), Pexels detrás. Tres decisiones que
no se ven en el diff:

- La clave se lee **sólo del entorno**. El primer borrador leía también
  `~/.config/fal/key`, que **existe en el Mac de desarrollo**: cualquier test
  que llegara a `fetch()` habría comprado una imagen y pasado en verde.
- El cargo al libro va **después** de que fal acepte, como Kling hace en su
  `task_id`. Lo escribí al revés en el primer commit, diciendo «igual que
  Kling» sin leer hasta su línea 143: cobrando antes, **diez minutos de caída
  de fal gastaban el tope de 8 y dejaban el resto del día en Pexels** sin que
  nadie lo viera. `test_a_refusal_is_not_charged` ya fijaba la regla con el
  nombre. Corregido en `643ebff`.
- Un **403** de fal es saldo agotado, no credencial mala, y **no** sube como
  excepción: `NoBalance` se desenrolla fuera de `fetch()` sin pasar por Pexels,
  así que una cuenta vacía habría dado tarjeta en blanco a cada escena → guard
  de `produce.py` → trabajo muerto → reintento → **narración pagada otra vez**.
  La forma exacta del incidente que este proveedor venía a cerrar. Ahora se
  dice una vez, gasta el presupuesto del día para que nadie vuelva a preguntar,
  y el vídeo sale con foto de banco.
- Kling **no** es respaldo de un fallo de fal: contesta sólo en máquinas sin
  credencial de fal.

🔴 **Lo que sigue abierto y no he tocado**:

- **El orden invertido sigue vivo**: la narración se paga antes de comprobar
  que hay proveedor de imágenes. Hoy ya no sangra porque hay dos proveedores
  vivos, pero el defecto es el orden, no los reintentos.
- **`install-on-rog.sh:79` sigue con `cat > ~/.eko-render.env`**, que es lo que
  borró las claves. Le he añadido `FAL_KEY=` a la plantilla y al README, pero
  **el arreglo del `cat >` es `9127947`, en `fix/la-puerta-de-la-marca`** — de
  otra sesión, y no lo duplico.
- ~~El obrero no coge trabajo hasta las 13:00~~ — el dueño autorizó abrir la
  ventana a las 05:52; el vídeo salió en 88 s y las horas quedaron
  **restauradas** a `[1,2,13,15,16,17,21,23]`. La cadena entera (guion → voz →
  Whisper → 5 imágenes de fal → montaje → marca) está probada.
- Tope diario en **8 imágenes**, heredado de cuando cada una era un clip caro
  de Kling. Con fal a céntimos, un segundo vídeo del día cae a Pexels sin que
  nadie lo pida. Sube `RENDER_IMAGES_PER_DAY` cuando quieras.

### 🔴 Lo que queda del incidente — acción del dueño

Lo reporta la sesión «fix-caption-rendering» en la madrugada del 4-sep, y no lo
he tocado ni verificado yo:

- **`install-on-rog.sh` borró tres claves de `~/.eko-render.env` sin copia**
  (`PEXELS_API_KEY`, `KLING_ACCESS_KEY`, `KLING_SECRET_KEY`). El instalador las
  reescribió con `cat >`. **Hay que reponerlas a mano** — el carril de vídeo
  generado no puede producir nada hasta entonces. Su instalador ya está
  corregido en `9127947`, en su rama.
- **El obrero del ROG está parado** (`systemctl --user stop eko-render-worker`),
  a propósito: el trabajo 11 entraba en bucle de 3 intentos cada ~70 s y **cada
  intento narraba con MiniMax antes de morir — 11 narraciones pagadas** entre
  las 23:19 y las 23:44.
- 🔴 **Por qué costó dinero, y esto es lo que hay que arreglar**: el obrero
  **paga la narración ANTES de comprobar que hay proveedor de imágenes**. Con
  las claves borradas, cada reintento compraba una narración para morir en el
  mismo punto. Los reintentos no son el defecto — el orden sí: lo que no puede
  fallar se verifica antes de gastar. Es la misma forma que
  [[feedback_pagar_dos_veces_el_insumo]], un escalón más arriba.
- Descartadas por la sesión vecina, con evidencia, quién reencoló: **no fue el
  sweep** (`_enqueue` exige 24 h y llevaba 2) ni **la consola** (en
  `ContentQueue.tsx` `onRebuild` solo cuelga del `onClick`, y el único
  `useEffect` carga la lista: sin sondeo ni acciones automáticas, una pestaña
  abierta en `/content` no lo explica).
- Queda sin explicar **quién reencoló** ese trabajo: `_enqueue` solo reencola un
  job `FAILED` tras 24 h de enfriamiento y llevaba 2. **No fui yo**: en esa
  ventana conducía Chrome contra una pila local (`eko_live_check`, puertos 8099
  y 3199) y no he llamado a ningún endpoint de `content` ni de `render-jobs` en
  toda la sesión. La consulta que lo aclara, para el dueño:
  `SELECT id, piece_id, status, attempts, worker, claimed_at, updated_at FROM render_jobs WHERE piece_id=10 ORDER BY id`.
  **Me la pidieron a mí y la he declinado**: a esa sesión se la bloqueó su
  clasificador de permisos, y ejecutarla yo anularía esa decisión sin que nadie
  la revise.

### Heredado de la sesión «fix-caption-rendering» al cerrar (no es de este plan)

Dos hallazgos suyos que no tocaron y que quedan aquí para que no se pierdan al
morir su sesión. **Ninguno se arregla en esta tanda**: son del carril de vídeo.

- 🔴 `render_watch` solo mira el **latido** del obrero, así que un trabajo en
  `failed` deja el vigía en «ok» y la alarma no puede sonar. Es la misma forma
  de avería que este proyecto ya pagó dos veces: el vigilante mide que el
  proceso vive, no que el trabajo salga.
- `/data/media` tiene 12 mp4 y solo 6 referenciados; nada los barre.

### 💡 IDEA DEL DUEÑO (4-sep) — pedirle al sistema una pieza concreta

No es de este plan y no se ha empezado. Queda escrita porque la parte difícil no
es la pantalla.

**Lo que pidió**: una sección en `/content` donde escribir la descripción de lo
que se quiere para un post, adjuntar **opcionalmente** una imagen o vídeo de
referencia, elegir si sale con foto(s) o con vídeo, y **elegir el modelo entre
los disponibles — de los gratis a los de pago — con el coste estimado a la vista
en el propio selector**.

Lo mejor de la idea es lo último: hoy se elige proveedor a ciegas y el precio
aparece en la factura. Cuatro cosas que hay que resolver bien o hacen daño:

1. **El precio no puede estar escrito en la pantalla.** Un número en el
   componente envejece en silencio y miente con cara de dato. Va en un catálogo
   único (modelo → precio por unidad → qué produce) que la UI lee; y para vídeo
   el coste depende de la duración, así que es un rango, no una cifra.
2. **La puerta de aprobación no se salta.** Una pieza pedida por el dueño entra
   como cualquier otra: pasa el rail de Fair Housing y espera aprobación. «Lo
   pedí yo» no es una exención — el producto promete que nada se publica sin que
   una persona lo apruebe, y esa frase está en la propia página.
3. **La referencia adjunta es referencia, no material.** Los ejemplos que mandó
   son Reels de otras cuentas. Como inspiración de estilo, bien; usar el vídeo
   de otro dentro de una pieza publicada es un problema de derechos, no de
   producto. La UI debe decir «referencia de estilo» y el pipeline no debe poder
   incrustarla.
4. **La descripción tiene que llegar al modelo en inglés.** Medido y pagado ya:
   un prompt en español a fal.ai no falla, **miente** — devuelve otra cosa con
   éxito. Si el dueño escribe en español hay que traducir antes de generar.

Y el tope diario de imágenes (`RENDER_IMAGES_PER_DAY`, hoy 8) tiene que cubrir
también este camino, o será la vía por la que se gasta sin freno.

### Siguiente paso — pendiente para mañana (5-sep)

El plan queda con **dos fases sin empezar** y todo lo demás desplegado.

**F6 — vistas por vídeo de YouTube.** Necesita una acción del dueño **antes** de
que se pueda probar de verdad: crear una clave en Google Cloud (APIs y servicios
→ Credenciales → Clave de API, restringida a «YouTube Data API v3») y ponerla en
el `.env` del VPS como `YOUTUBE_DATA_API_KEY`. El agente no la ve. Sin clave, el
código se escribe y se prueba con la API parcheada, pero la verificación real
espera. Coste medido: `videos.list` es 1 unidad por llamada de hasta 50 vídeos,
cuota diaria 10.000, un tick cada 6 h gasta ~4 unidades al día.

TikTok e Instagram **no** entran: sus APIs no exponen las vistas sin una app
propia con revisión de Meta/TikTok, así que esas columnas se teclean a mano
desde la consola de contenido.

**F9 — cierre documental.** `docs/analytics.md` con el diccionario de métricas:
la definición exacta de cada número, qué es medición y qué es asociación, la
retención, GPC, y qué no se guarda. Es lo que evita que dentro de tres meses
alguien lea «tasa de cierre» y suponga otra cosa.

Nada de esto bloquea el uso: lo desplegado hoy ya mide y ya se puede mirar.

---

## ✅ DESPLEGADO — v0.77.0 · checkpoint E: la analítica que se puede mirar

> **En producción el 4-sep-2026**, autorizado por el dueño. `/api/v1/health` →
> **`0.77.0`**. VPS en `c1e3cca`. **Sin migración** — `alembic current` sigue en
> `053_deal_columns (head)`, comprobado antes de levantar.

Va con las dos fases juntas: **F7** (la API v2) y **F8** (la página).

| Comprobación | Resultado |
|---|---|
| `/api/v1/health` | **0.77.0** |
| Landing pública | `200` |
| `/analytics` | se sirve `200` |
| `GET /api/v1/analytics` sin sesión | `401` — la ruta existe y el guard muerde |
| `/ig` · `/tt` · `/yt` | `200`, cada uno con su `utm_source` |

**Lo que la página contesta ahora**: de dónde vienen las visitas, hasta dónde
leen, qué secciones alcanzan, quién responde y cuán rápido, llamadas recibidas y
registradas, citas puestas y hechas, y qué tipo de negocio se cerró — sobre 7,
30 o 90 días, cortados a la medianoche de la oficina. Y cada lead tiene su línea
de tiempo.

🔴 **Falta que el dueño la abra.** Todo lo verificado arriba es que responde;
que los números signifiquen lo que dicen sólo lo puede juzgar quien conoce el
negocio. Hoy hay poquísimos datos reales, así que la mayoría de tarjetas dirán
que están vacías — y ese texto es a propósito: dice *por qué* está vacía, no un
cero que se lee como un hecho.

---

## ✅ DESPLEGADO — v0.75.1 · checkpoint C: qué negocio se cerró, y de qué red viene

> **En producción el 4-sep-2026**, autorizado por el dueño. `/api/v1/health` →
> **`0.75.1`**. VPS en `1704d37`. Migración **053_deal_columns** aplicada con la
> imagen nueva (`052` → `053_deal_columns (head)`).

| Comprobación | Resultado |
|---|---|
| `/api/v1/health` | **0.75.1** |
| Landing pública | `200` |
| Columnas de cierre en `leads` | **4** (`won_kind`, `won_value`, `won_at`, `lost_reason`) |
| `CONTENT_UTM_CAMPAIGN` en el contenedor | `video` — llega por el defecto del compose, **sin tocar el `.env`** |

🔴 **Las 5 publicaciones ya programadas en Buffer llevan el enlace SIN etiquetar.**
Se escribieron y se entregaron a Buffer antes de este despliegue, y su texto ya
está del lado de Buffer: piezas 9 y 10, entre el 5 y el 6 de septiembre. La
etiqueta empieza a aplicarse en **la siguiente pieza que se publique**, no en
las que ya están en cola. No se tocan: reescribirlas significaría borrarlas y
reprogramarlas, y una publicación duplicada cuesta más que un `direct` de más.

**Acción del dueño, sin la cual la mitad de F5 no sirve**: pegar los tres
enlaces de perfil (`docs/enlaces-de-bio.md`). El sistema etiqueta el pie de los
vídeos; el enlace del perfil no lo pone nadie más que él.

---

## ✅ DESPLEGADO — v0.74.0 · checkpoint B: el lead recuerda lo que le pasó

> **En producción el 4-sep-2026**, autorizado por el dueño. `/api/v1/health` →
> **`0.74.0`**. VPS en `67c4594`. Migración **052_lead_events** aplicada con la
> imagen nueva (`051` → `052_lead_events (head)`).

## 🧹 Base de leads vaciada — 42 de prueba, con copia previa

> Autorizado el 4-sep. **Nada de esto es reversible sin la copia**, así que la
> copia es lo primero que se hizo, no lo último.

| | |
|---|---|
| Volcado completo | `eko_pre_purge_20260904.sql`, 211 KB, **en el VPS y en el Mac** (`~/eko-realtors-backups-vps/`), sha256 idéntico en los dos |
| Ids de las 5 llamadas de VAPI | guardados aparte en `vapi_call_ids_20260904.tsv` — siguen existiendo en VAPI y son el único material real para probar el parser |
| Bajas (opt-out) entre los 42 | **0** — lo que hacía seguro el borrado: ninguna ficha era la prueba de que alguien pidió no ser contactado |

Borrado: 42 leads y, en cascada, 13 conversaciones, 157 mensajes, 1 llamada
registrada, 5 visitas y 6 seguimientos. **Intactas a propósito**: las 7 piezas de
contenido y sus 21 publicaciones (dos están programadas en Buffer y borrarlas
dejaría publicaciones huérfanas saliendo solas), y las sesiones de la landing.

**Verificado después**: `/health` en 0.74.0, la landing en 200, el colector
responde `204` y el formulario sigue rechazando un cuerpo vacío con `422`. La
fila de esa comprobación se borró.

### 📈 Y ya está entrando tráfico real

Tres visitas que **no son del dueño ni mías**, todas de esta mañana:

| Cuándo (MDT) | Qué | Recorrido |
|---|---|---|
| 08:06 | escritorio, Chrome, macOS, **San Jose** | 0 %, rebote |
| 08:25 | **iPhone, Safari, Denver** | 0 %, rebote |
| 09:07 | **iPhone, Safari, Aurora** | 0 %, rebote |

Las tres llegan como `direct`, sin referente — exactamente el techo de
atribución que el plan declaró: las apps borran el referrer. **Y las tres
rebotan sin bajar nada.** Dos de Denver y Aurora en iPhone parecen personas; la
de San Jose, con Chrome de escritorio, huele a rastreador. Es pronto para
concluir, pero esa columna de ceros es justo el número que antes no existía.

---

## ✅ DESPLEGADO — v0.73.1 · dos secciones se leían y no se contaban

> **En producción el 4-sep-2026**, con la autorización del dueño («si pasan
> todas las pruebas quedas autorizado»). `/api/v1/health` → **`0.73.1`**. VPS en
> `d3f8a1e`. **Sin migración**; `alembic current` comprobado antes de levantar:
> `051_landing_sessions (head)`.

**El defecto.** El observador preguntaba si una sección llenaba la mitad de **sí
misma**. `#about` mide 1.249 px y `#how` 1.259 px, casi el doble que la pantalla
de un iPhone 13 (664 px): lo máximo que podían intersecar era **0,53**, así que
con el umbral en 0,5 sólo contaban si quedaban casi perfectamente centradas.
Medido contra la página viva con el motor de Safari, **una lectura completa
reportaba dos secciones en vez de cuatro** — el embudo decía que la gente se iba
antes de tiempo cuando había leído entera.

Lo encontró la verificación de iOS, no un test: el dueño no tiene iPhone (usa un
Fold, y por eso su visita real sí registró las cuatro — su pantalla es más alta).

**La regla nueva es «la mitad de lo que quepa»**: media pantalla para una sección
más alta que la pantalla, media sección para una más baja. Ninguna fracción sola
sirve — exigir siempre media pantalla dejaría fuera un bloque corto. Vive en
`lib/track.ts`, no en el componente, porque es una regla y no fontanería del DOM.

| Prueba | Resultado |
|---|---|
| Backend | 1476 verdes, 0 saltados |
| Frontend | 236 verdes (5 nuevos, con los números medidos en producción) |
| `ruff` · `tsc` · `next build` (`/` estática) · `docker build` | limpios |
| **Mutación que importa**: volver al ratio del elemento | **roja** — es la que prueba el arreglo |
| Mutación secundaria: quitar la guarda de números degenerados | roja (prueba la guarda, no el arreglo) |
| **iPhone 13 (390 px) contra producción** | **4 secciones**, scroll 100 %, `tel_click` |
| **iPhone 13 Pro Max (428 px)** | **4 secciones** — el fallo dependía del alto de pantalla, un solo tamaño no lo probaría |

Las filas de verificación se borraron: en producción queda **sólo la visita real
del dueño**.

**Reversión**: `git reset --hard bf0476c` + rebuild de backend **y** frontend.
Sin tocar migraciones.

---

## ✅ DESPLEGADO — v0.73.0 · checkpoint A: la landing se mide a sí misma

> **En producción el 4-sep-2026 a las 06:2x MDT**, autorizado por el dueño en un
> mensaje aparte. `/api/v1/health` por el dominio → **`0.73.0`**. VPS en
> `bf0476c`. Migración **051_landing_sessions** aplicada con la imagen nueva
> (`050_publication_schedule` → `051_landing_sessions (head)`).

**Medido en el sitio vivo, no supuesto:**

| Prueba | Resultado |
|---|---|
| `/api/v1/health` | **0.73.0** |
| Landing pública | `200` durante y después del despliegue |
| Baliza con lote válido | `204` **y fila escrita** |
| Tipo de evento desconocido | `400`, nada escrito |
| `session` mal formada / JSON inválido | `400` |
| `POST /public/leads` tras agotar la baliza | `422` — **el presupuesto del formulario no se tocó** |
| Fila resultante | `source=other`, `utm_source=deploy-check`, `max_scroll_pct=50`, `sections_viewed=["markets"]`, `event_count=3` |

🎯 **La geolocalización está completa.** `country=US` llegó desde el primer día,
lo que ya confirmaba que las cabeceras de Cloudflare atraviesan el túnel y el
rewrite de Next. El **4-sep el dueño activó** «Add visitor location headers»
(Cloudflare → Rules → Settings → Managed Transforms) y una visita de prueba
devolvió **`US / CO / Parker`**: país, región **y ciudad**. La incógnita §6.6 del
plan queda cerrada y §7.4 hecho.

«Remove visitor IP headers» se dejó **apagado** a propósito: borraría la cabecera
con la IP del visitante, que es de donde el limitador del formulario saca a quién
está frenando.

La fila de prueba se **borró** al terminar (3 eventos + 1 sesión); las dos
tablas quedan en **0 y 0**, para que el primer visitante real sea el primero de
verdad.

**Reversión**, si hiciera falta: `git reset --hard c68aaf7` + rebuild. **No**
hacer `alembic downgrade`: borraría las visitas ya recogidas y el código viejo
convive sin problema con dos tablas que no consulta.

**Lo que falta y no es mío**: abrir la landing desde un iPhone real — iOS Safari
sigue **sin medir**, y es el navegador de la mitad de los visitantes.

---

## ✅ DESPLEGADO — v0.71.0 · la página dice de quién es

> **En producción el 3-sep-2026**, autorizado por el dueño. `/api/v1/health` por
> el dominio público → **`0.71.0`**. VPS en `bf440e5`. Sin migración.
>
> **Medido en el sitio vivo** (`https://www.denverhomestory.com`):
>
> | Qué | Resultado |
> |---|---|
> | `Denver Home Story` en el HTML | **0 → 17** |
> | `<title>` y `og:title` | `Denver Home Story · Natalia & Robbie, Engel & Völkers` |
> | Logotipo, escritorio | «Denver Home Story» a 26 px, **visible** |
> | Logotipo, móvil y menú | 19 px, **visible**, con la línea de personas debajo |
> | Frase del héroe | EN «Denver Home Story is Natalia & Robbie — …» · ES «Denver Home Story son Natalia & Robbie — …» |
> | Pie | `Denver Home Story · Natalia & Robbie · Real estate advisors · Engel & Völkers` |
> | Con `prefers-reduced-motion` | `currentTime` **0 / 5,96 / 12,36 / 18,16** (antes clavado en 0,02) y el parallax sigue vacío |
> | Sin reducir, móvil | escenario clavado en 0, vídeo siguiendo al scroll |
>
> **Reversión**: `git reset --hard 8814b64` + `docker compose build backend
> frontend` + `up -d`. Copia del `.env`: `.env.bak.20260903_v0710`.

### ✅ v0.71.1 — las dos cosas que la verificación dejó a la vista, arregladas

Desplegada y verificada por el dominio público: `/api/v1/health` → **`0.71.1`**.
VPS en `02f0ac8`. Copia del `.env`: `.env.bak.20260903_v0711`.

| Qué | Antes | Después (medido en el sitio vivo) |
|---|---|---|
| Brokerage en la web | `Engel & Völkers` | **`Engel & Völkers Aspen`**, 6 apariciones; **0** de la forma corta |
| ¿Coincide con los vídeos? | 🔴 no (`agent_settings.brokerage_line` = «Engel & Völkers Aspen») | ✅ sí |
| `<title>` | `… Engel & Völkers` | `Denver Home Story · Natalia & Robbie, Engel & Völkers Aspen` |
| Enlace del pie | `next/link` a `/login` → 308 a otro origen → **2 errores de CORS por carga** | ancla directa a `https://inmo-demo.…/login`; **consola sin errores nuestros** |

Lo que **sí** queda en la consola y **no es nuestro**: dos líneas de estilo del
widget de Turnstile (`%c%d font-size:0…`), su baliza abortada al navegar, y un
404 de `/favicon.ico` — este último sí es nuestro y es trivial, **anotado sin
arreglar** para no ensanchar la tanda.

**Por qué la brokerage importaba y no era estética**: es la identificación que
Colorado **exige** que lleve la publicidad inmobiliaria. Que la web y el vídeo
dijeran cosas distintas solo era invisible mientras la web no la enseñaba en
ningún sitio; v0.71.0 la puso en el logotipo, el pie y el título, y entonces se
vio. Decisión del dueño: igualarla a los vídeos.

### Historial: las dos cosas, cuando estaban abiertas

1. **La brokerage en producción dice «Engel & Völkers», no «Engel & Völkers
   Aspen».** Ahora se lee en el logotipo, en el pie y en el `<title>`, así que
   ya no pasa desapercibido. La decisión escrita del 26-ago era «Engel &
   Völkers Aspen», y **es la identificación legal de la brokerage que Colorado
   exige en la publicidad** — no es una preferencia de estilo. Se cambia con una
   línea del `.env` del VPS (`NEXT_PUBLIC_LANDING_BROKERAGE`) **y un rebuild del
   frontend**, porque es `NEXT_PUBLIC_*`. **Decisión del dueño**, no mía.
2. **El enlace del pie a `/login` provoca un error de CORS en cada carga.** Next
   precarga la ruta, el middleware la manda 308 a `inmo-demo…`, y el `fetch`
   entre orígenes se bloquea: `Failed to fetch RSC payload … Falling back to
   browser navigation`. **El enlace funciona** (cae a una navegación normal),
   pero deja dos errores en la consola de todo visitante. Es anterior a esta
   tanda (viene del enrutado por host). Arreglo probable: `prefetch={false}` en
   ese `Link`, o un `<a>` normal. **Backlog, no tocado hoy.**

### Detalle de la tanda

Rama `feat/landing-marca` desde `4fd35bd` (apilada, sin merge). Commits
**`b67cb86`** (la marca) y **`b354665`** (movimiento reducido).

### El dato que abre esto

El dueño: *«no se ve en ningún lado denverhomestory.com; como los visitantes
vienen de las redes de Denver Home Story y al llegar no sale nada sobre Denver
Home Story, parece que la landing no tiene nada que ver»*.

**Medido en la página que servía producción**: la cadena `Denver Home Story`
aparecía **0 veces**. El `<title>` decía «Natalia & Robbie · Engel & Völkers —
Colorado real estate». El diseño v6 la lleva en **nueve** sitios; al convertirlo
a React puse `LANDING.advisors` donde el diseño pone la marca y la borré de las
frases. Mismo tipo de fallo que la tanda anterior: **el diseño ya lo traía
resuelto y el port no lo copió.**

### Lo medido, no recordado

| Qué | Antes | Después |
|---|---|---|
| `Denver Home Story` en el HTML | **0** | **17** |
| `<title>` | `Natalia & Robbie · Engel & Völkers — Colorado real estate` | `Denver Home Story · Natalia & Robbie, Engel & Völkers Aspen` (el del diseño, exacto) |
| Logotipo de cabecera | `Natalia & Robbie` (26 px) | **`Denver Home Story`** (26 px), con `Natalia & Robbie · Engel & Völkers Aspen` debajo |
| Cabecera del menú móvil | igual defecto | igual arreglo (**un solo** componente para los dos) |
| Pie | sin marca | `Denver Home Story · Natalia & Robbie · Real estate advisors · Engel & Völkers Aspen` |
| Primera frase del héroe | «Real estate advisors buying and selling…» | «**Denver Home Story** is Natalia & Robbie — …» · ES: «**Denver Home Story** son Natalia & Robbie — …» |
| Con `prefers-reduced-motion` | `currentTime` clavado en **0,02** | avanza **5,96 / 12,34 / 18,11**, y el parallax sigue vacío |

### El defecto de fondo que se arregló de paso

El nombre público tenía **dos** derivaciones: `app/page.tsx` la construía en
línea y `app/contact/layout.tsx` la volvía a construir **bajo un comentario que
afirmaba que eran «la misma fuente para que no se separen»**. Ya eran dos. Ahora
hay una sola en `lib/landing.ts` y las dos páginas la importan.

### Mutaciones verificadas

| Mutación | Resultado |
|---|---|
| Escribir la marca en el código en vez de leerla del entorno | 🔴 (2 tests) |
| El logotipo vuelve a `LANDING.advisors` | 🔴 |
| El pie pierde la marca | 🔴 |

### Checklist

`tsc` ✅ · `vitest` ✅ **197** · backend desde base recreada ✅ **1374, 0 saltados**
· `ruff` ✅ · `next build` ✅ · `docker build` ✅ · Fair Housing ✅ 0 en 5 cadenas
EN+ES · 3 mutaciones rojas y restauradas · sin secretos.

### Despliegue: preparado y parado

Otro `NEXT_PUBLIC_*`, así que **otro rebuild** y el valor en el `.env` del VPS
**antes** de compilar: `NEXT_PUBLIC_LANDING_BRAND="Denver Home Story"`.
Reversión: `git reset --hard 8814b64` (v0.70.0, ya verificada en producción) +
`docker compose build backend frontend` + `up -d`.

### 👁️ Visto y NO reproducido — Opera de Android

El dueño reportó que en **Opera Android 101.2.5178.89973** no había efectos: ni
el vídeo con el scroll ni los demás. Comprobado con él en directo: el héroe
**sí** se quedaba fijo varias pantallas (eso es CSS y funciona sin JS), y luego
el menú **sí** abría, el idioma **sí** cambiaba y el vídeo **sí** se movía —
*«ya funciona bien, veo que se mueve como debería»*. En Chrome de Android nunca
falló. **No se cambió nada por esto.** Explicación más probable: HTML en caché
de antes del despliegue, o el clip de 17,8 MB aún sin buffer. Si vuelve, mirar
primero la caché y el estado del vídeo, no el motor.

---

## ✅ DESPLEGADO — v0.70.0 · la landing termina de ser el diseño v6

> **En producción el 3-sep-2026**, autorizado por el dueño. `/api/v1/health` por
> el dominio público → **`0.70.0`** · `captcha:on` · `llm_fallback:ok`.
> Se desplegaron **v0.69.0 y v0.70.0 juntas** (10 commits, `8d0a47a..8814b64`),
> sin migración. VPS ahora en `8814b64`.
>
> **Medido en el sitio vivo, no en local** (Playwright contra
> `https://www.denverhomestory.com`):
>
> | Qué | Resultado |
> |---|---|
> | Escenario clavado, 1440 y 390 | `top = 0` en las cuatro posiciones |
> | Leyendas | cada una a 1,00 solo en su ventana; las otras en `visibility:hidden` |
> | Barra de progreso | = p (0 / 38,01 / 63,99 / 90 %) |
> | Vídeo | sigue al scroll (t = 5,96 / 12,44 / 18,17) |
> | Sin scroll horizontal | ✅ en los tres contextos |
> | Carril de mercados | arrastra 0 → 48 |
> | Movimiento reducido | vídeo parado en 0,02 s, leyendas cruzándose |
> | Menú a 390 | capa de **390×844 exactos**, foco en el cierre, scroll bloqueado, **12 tabulaciones dentro**, Escape devuelve el foco, un enlace lleva a `#markets` |
> | Pie | los 3 canales con sus URL correctas |
> | Hamburguesa en escritorio | ausente |
> | Panel | `/login` 200, raíz 307 — intacto |
> | Vecinos | `zorros-*` y `blackvolt-*` sin tocar, `Up` 4 y 5 semanas |
>
> **Sigue sin medir: iOS Safari** — el `svh` del héroe con la barra plegándose y
> el bloqueo de scroll del menú. En escritorio `svh == dvh == lvh`, así que nada
> de lo anterior lo prueba. **La primera comprobación real es un iPhone.**
>
> Copia del `.env` antes de tocarlo: `~/Eko-AI-RealEstate/.env.bak.20260903_v0700`
> (160 líneas; ahora 163, las 3 nuevas son URL públicas, ningún secreto tocado).
>
> **Reversión**: `git reset --hard 8d0a47a` + `docker compose build backend
> frontend` + `up -d` → vuelve a 0.68.0.

### Detalle de la tanda

Rama `feat/landing-v6-afinado` desde `df8d602` (apilada sobre `feat/landing-v6`,
sin merge). Commits **`07a265b`** (motor) y **`68583fb`** (menú, escenario, pie).

### La premisa, medida antes de tocar nada

El dueño volvió a pedir la importación del proyecto de Claude Design pidiendo
«esta última versión con todos los nuevos arreglos y optimizaciones». **No había
versión nueva.** Con `/design-login` autorizado, la MCP devuelve el
`deploy-v6/index.html` remoto y es **byte a byte idéntico** al que se portó en
v0.69.0:

| Qué | Medida |
|---|---|
| md5 remoto vs local | `c88418ae1a7a18ee345055feaf521041` los dos |
| Tamaño | 58.469 bytes los dos |
| `natalia-robbie.jpg` | 85.733 B los dos |
| Carpetas del proyecto | `deploy-v4` y `deploy-v6`; nada más nuevo |

Así que «los arreglos y optimizaciones» eran los que estaban **dentro de ese
mismo v6 y el port no copió**: al convertir el fichero a React se colaron
constantes de la v4 y dos mecanismos inventados. Eso es esta tanda.

### Consultas al advisor

| # | Motivo | Decisión |
|---|---|---|
| 2 | Cierre | Tres correcciones, aplicadas: **(a)** faltaba registrar esta misma consulta; **(b)** 🔴 la reversión del runbook apuntaba a `df8d602`, que es v0.69.0 y **tampoco está desplegada** — una reversión a una versión que nunca salió no revierte nada; el objetivo es el commit que hoy corre en el VPS, y **no lo he leído en esta sesión**, así que va el comando para leerlo, no un SHA adivinado; **(c)** el respaldo del sticky no puede decidir hasta que el visitante ha entrado 40 px en el host, así que «mantiene el encuadre» estaba de más: se recupera en los primeros píxeles, no desde el primero. También recordó que la medición de `svh` en Playwright no prueba nada sobre iOS, porque en escritorio `svh == dvh == lvh`. |
| 1 | Arranque, antes de escribir el plan | Corrigió tres cosas que cambiaron el plan: **(a)** la capa del menú **no puede vivir dentro del escenario sticky** (`overflow-hidden` + el `will-change:transform` que le pone el respaldo del sticky la convertirían en bloque contenedor de `position:fixed` y la recortarían) — va como hermana de `<main>`; **(b)** los enlaces sociales son **datos**, así que por la regla de esta página van por `NEXT_PUBLIC_*` con su coste de cableado y de despliegue, no escritos en el componente; **(c)** «17,8 MB compiten con el LCP» estaba exagerado — con `preload="auto"` Chrome pide un Range de 1-3 MB, así que `preload="none"` había que **medirlo o cortarlo**. Además: ordenar la fase para que lo especulativo no bloquee lo cierto, y que el respaldo del sticky sin su mutación es decoración. |

### Lo medido, no recordado

| Qué | Medida | Consecuencia |
|---|---|---|
| **Puerta G — `preload="none"` + `data-src`** | bytes del clip transferidos **antes de que el póster termine**, a 390 px con la red estrangulada a 1,6 Mbps: **11.254 → 0**. Póster listo a 2,13 s vs 2,08 s. Total en 6 s: 1.431.754 vs 1.398.754 B | **11 KB de 17,8 MB no es un movimiento visible → G NO se despliega**, y el motivo queda escrito en el propio `<video>`. Es la puerta que yo mismo puse antes de medir |
| **Puerta A — respaldo del sticky** | inyectando `body{overflow-x:hidden}` en caliente (el CSS exacto que rompió esta página): **sin** el respaldo el escenario cae a **−878 / −1755 / −2808 px**; **con** él se queda en **0/0/0** y pasa a `position:absolute` | pasa, y la mutación existe: no es decoración |
| El playhead **converge** con la tasa nueva | tras un salto instantáneo: brecha 8,31 → 4,31 → **0 s** a los 6 s, y la tasa vuelve sola de 2× a 1× y se queda | la tasa de dos velocidades es más suave, no más lenta |
| **D se nota** | la sección `#about` ahora revela con su borde **197 px DENTRO** del viewport (umbral 0,82); antes disparaba con el borde aún por debajo del pliegue | las animaciones ocurren donde se ven |
| El menú a 390×844 | capa de **390×844 exactos** (prueba de que no la recorta el escenario), `rootOverflow: hidden`, foco en el cierre, Escape cierra y **devuelve el foco**, la página no se mueve detrás, un enlace cierra y lleva a `#markets` | ✅ |
| 🔴 **Defecto que la medición destapó** | `aria-modal="true"` **no** cambia el orden de tabulación del navegador: la 6ª tabulación salía de la capa y la 9ª caía en el **campo de nombre del formulario**, invisible detrás de un panel a pantalla completa | añadida trampa de foco; ahora **12 tabulaciones no salen** |
| El pie | 3 iconos con las 3 URL correctas; con una variable vacía su icono **no existe** (test unitario con `stubEnv`) | ✅ |
| Fair Housing | 19 cadenas nuevas EN+ES → **0 hallazgos** | ✅ |
| `contain: paint` | el retrato sigue a sangre y sin borde en la captura, con el parallax aplicado (`scale(1.11)`) | ✅ aislamiento, no recorte |

### Las mutaciones, verificadas una a una

Guardar → mutar → **ver rojo** → restaurar → md5 idéntico. Las cinco:

| Mutación | Resultado |
|---|---|
| Quitar la guarda `!coarse` del desenfoque | 🔴 |
| Volver a la tasa continua de reproducción | 🔴 |
| `host.__js = false` (matar el respaldo del sticky) | 🔴 |
| Meter la capa del menú **dentro** de `<main>` | 🔴 |
| Quitar el `.filter()` de `LANDING.socials` | 🔴 (3 tests) |

### Checklist de «terminado»

| Comprobación | Resultado |
|---|---|
| `tsc --noEmit` | ✅ limpio |
| `vitest run` | ✅ **186** (13 ficheros) |
| Suite backend desde base recreada | ✅ **1374** pasados, **0 saltados** (3 m 56 s) |
| `ruff check app tests` | ✅ limpio |
| `next build` con los `NEXT_PUBLIC_*` reales | ✅ |
| `docker build -f backend/Dockerfile` | ✅ compila |
| Fair Housing sobre el copy nuevo | ✅ 0 en 19 cadenas × 2 idiomas |
| Mutaciones | ✅ 5 de 5 rojas, restauradas por md5 |
| Secretos en el diff | ✅ ninguno |
| Auditoría de cierre | ✅ **auto-auditoría, NO independiente** (ver abajo) |

### Auditoría de cierre — mía, y por tanto vale menos

El método pide subagente; no se lanzó ninguno en esta sesión, así que **esto es
una auto-auditoría y no es independiente**, igual que en v0.69.0.

- 🔴 **Bloqueante, encontrado y corregido dentro de la fase**: el menú no
  atrapaba el foco. Está en la tabla de medidas: la 9ª tabulación caía en el
  formulario detrás del panel.
- 🟡 **Menor, anotado y no arreglado**: `aria-controls="landing-menu"` apunta a
  un id que solo existe con el menú abierto. `aria-expanded` sí lleva el estado,
  así que no se pierde información; la alternativa —dejar un `position: fixed`
  oculto permanentemente en el DOM— es peor que el defecto.
- 🟡 **Menor**: el respaldo del sticky deja `position: absolute` en línea sobre
  el escenario y no lo limpia al desmontar, y `host.__js` persiste en el
  elemento. Es el comportamiento del diseño y no tiene efecto: motor y escenario
  viven en el mismo árbol, así que uno no sobrevive al otro.
- ✅ Sin secretos en el diff (14 ficheros, +653/−40), sin
  `dangerouslySetInnerHTML`, el único enlace externo nuevo con
  `rel="noopener noreferrer"`, `.env.example` con las tres claves **vacías**,
  árbol limpio.

### Lo que NO se pudo medir, dicho como tal

- **Safari en iOS con la barra plegándose**: el cambio `dvh → svh` y el bloqueo
  de scroll del menú (`documentElement.style.overflow`, que iOS puede ignorar).
  Decidido y escrito en el componente; no medido desde un Mac.
- El color del rebote superior en un móvil real (heredado de v0.69.0).
- **Ningún test unitario cubre el comportamiento del menú**: este repo no tiene
  jsdom. Los tests leen el fuente; el comportamiento se midió en navegador.

### Decisiones y por qué

- **`preload="none"` no entra.** La puerta era mía y la medición la suspendió.
- **El vídeo sigue sin bucle** al final (decisión del dueño, 3-sep): el diseño
  lo suelta en `loop`, pero el clip termina en la casa y abre en otra
  habitación — el bucle es un corte visible.
- **Privacy y Terms no se enlazan** aunque el diseño los liste: no existen.
- **Rama apilada, no continuación de `feat/landing-v6`**, para que esta tanda
  sea revertible por separado.

### 🔴 Consecuencia para el despliegue

**v0.69.0 no se despliega sola.** El runbook preparado pasa a ser el de
**v0.70.0**, y suma un paso que antes no tenía:

1. En el `.env` del VPS (copia de seguridad antes), **antes del build** porque
   son `NEXT_PUBLIC_*` y se hornean:
   `NEXT_PUBLIC_LANDING_INSTAGRAM=https://www.instagram.com/denverhomestory/`,
   `NEXT_PUBLIC_LANDING_YOUTUBE=https://www.youtube.com/@DenverHomeStory`,
   `NEXT_PUBLIC_LANDING_TIKTOK=https://www.tiktok.com/@denverhomestory`.
2. Bundle → `scp ender-vps` → `git fetch` + `merge --ff-only`.
3. `docker compose build backend frontend` — **los dos**: `APP_VERSION` vive en
   `backend/app/config.py`.
4. **Sin migración.**
5. `docker compose up -d backend frontend`.
6. Verificar `/api/v1/health` **por el dominio público** → `0.70.0`.

**Reversión — medido en el VPS el 3-sep 20:5x**, no adivinado. El objetivo NO
era `df8d602` (eso es v0.69.0, que tampoco está desplegada; revertir a una
versión que nunca salió no devuelve nada al estado bueno):

| Qué | Medida |
|---|---|
| HEAD en el VPS | **`8d0a47ad1d00e8aa86e70abfc4b636e2d9bf64eb`** |
| Rama del VPS | `feat/maquina-de-video-dhs` |
| `/api/v1/health` | `0.68.0` · `captcha:on` · `llm_fallback:ok` |
| Árbol del VPS | limpio (0 líneas) |
| Disco | 90 G libres de 156 G (40 %) |
| Contenedores | los cuatro `Up` |
| `origin` del VPS | **`/tmp/eko.bundle`, que ya no existe** — no alcanza GitHub, así que el despliegue va por bundle nuevo |

**Reversión**: `git reset --hard 8d0a47a` + `docker compose build backend
frontend` + `up -d`, y verificar `/api/v1/health` por el dominio → `0.68.0`.
Las tres variables nuevas pueden quedarse en el `.env`: sin código que las lea
son inertes.

**Lo que se desplegaría**: 10 commits, `8d0a47a..761c0c8` — v0.69.0 **y**
v0.70.0 juntas, 20 ficheros, **ninguna migración** (verificado: `git diff
--name-only` sobre `backend/migrations/` vuelve vacío). Del backend solo cambia
`APP_VERSION`; el resto es la landing.

**No se despliega sin autorización del dueño en un mensaje aparte.**

---

## ✅ ENTREGADO — v0.69.0 · la landing pasa al diseño v6 (el héroe es una película guiada por el scroll) (el héroe es una película guiada por el scroll)

Rama `feat/landing-v6` desde `f07b719` — commit **`d5c492b`**, en `origin`. Origen: carpeta `deploy-v6` del proyecto
de Claude Design (`04db33bc…`), descargada por el dueño a `~/Downloads/deploy-v6`
(la MCP `claude_design` pide `/design-login`; se trabajó desde la copia local,
que trae exactamente los ficheros que el dueño nombró).

### Consultas al advisor

| # | Motivo | Decisión |
|---|---|---|
| 2 | Cierre | `d5c492b` sólido. Dos cosas antes de pedir autorización, hechas: **(a)** el `html` de la landing seguía crema y el héroe ahora abre oscuro → el rebote superior en un móvil enseñaría una banda crema sobre la película; ahora `html` = noche (`#0F0E0C`, como el diseño) y `body` crema, y el `themeColor` de la raíz pasa a noche. **No medible desde Chrome de escritorio**: decidido y escrito en `globals.css`. **(b)** la reversión del runbook era una frase sin comando → literal abajo, con el árbol del VPS medido. Además: confirmar el commit por `git show --stat` (14 ficheros ✓, árbol limpio ✓), no reintentar ni omitir en silencio la memoria, y no convertir el `docker build` no ejecutado en «compila». |
| 1 | Arranque: enfoque y riesgos | Enfoque B (portar al React existente, no sustituir la raíz) validado. Añadió 9 puntos, todos aplicados: quitar `autoPlay`/`loop` del `<video>` (el `loop` habría deshecho en silencio el «sin bucle»); leyendas 2–4 con `opacity-0 pointer-events-none` iniciales (sin JS y antes de hidratar se apilaban las cuatro); medir el sticky **y** `scrollWidth`; host en `svh` + stage en `dvh`, y decirlo; Fair Housing sobre las cadenas nuevas; el runbook reconstruye **backend** además de frontend (`APP_VERSION` vive en `config.py`); auditoría + cobertura declarada; desviaciones por escrito; póster a 1280; timers a la limpieza. |

### Lo medido, no recordado

| Qué | Medida |
|---|---|
| El vídeo de v6 | **Es el mismo encode** que `casa-hero.mp4`, ya en producción (1920×1080, 20,57 s, 617 frames, 6,95 Mb/s, keyframes cada 0,5 s; difieren 5,9 KB de contenedor). Cero trabajo de vídeo |
| Los JPG de v6 | Mismo encuadre que los del repo (diff medio 1,8–8,9/255 tras reescalar); solo más resolución. Tarjetas se quedan a 1200 px; `cta-bg` sube a 2400 px (fondo a sangre, retina): 537 KB → 808 KB |
| Fotograma 0 del vídeo | Un salón interior (generado por IA, `docs/hero-video-procedencia.md`); el póster v4 (`hero-plate.jpg`) era la casa = **último** fotograma. Póster nuevo = fotograma 0 a 1280 px, 92 KB |
| `body{overflow-x:hidden}` | Convierte al body en contenedor de scroll y **rompe `position:sticky`**. Con `clip`: stage `top=0` en 6 posiciones de scroll a 1440 y a 390, y `scrollWidth == clientWidth` en los dos (la regla existía por el wiggle horizontal del clip-reveal; `clip` lo sigue cubriendo) |
| Motor a 1440×900 (Playwright, viewport exacto) | host 4410 = 4,9 vh · span 3510 · leyendas: p=0 → `0,0.22`=1,00 y resto 0; p=0,38 → solo `0.27,0.49`=1,00; p=0,64 → solo `0.53,0.75`; p=0,90 → solo `0.79,1` · `currentTime` = target ±0,01 en las 6 posiciones · barra = p · al final `t=20,51`, pausado, **sin bucle** · fuera de pantalla: pausado y target `null` |
| Motor a 390×844 | host 3376 = 4,0 vh · idéntico patrón · `scrollWidth 390` |
| `prefers-reduced-motion` (`reducedMotion: reduce`) | leyendas cruzan por scroll **sin** translate; vídeo `t=0`, target `null`, pausado; reveals/drift/parallax sin tocar (visibles tal cual se renderizan) |
| Carril de mercados | arrastre real con ratón: `scrollLeft` 0 → 48 (su máximo a 1440: 3 tarjetas + «More» apenas exceden el ancho) |
| Consola del navegador | un solo error: `/favicon.ico` 404, preexistente |
| Fair Housing | 11 claves × 2 idiomas → **0** violaciones |

### Desviaciones del diseño, decididas y escritas (cabeceras de `LandingEffects.tsx` y `Landing.tsx`)

1. **Sin bucle al final del héroe**: el diseño hace `loop` en `p ≥ 1`; este clip termina en la casa y empieza en otra habitación (`e321f95` lo dejó como PENDIENTE). El cabezal se queda en el último fotograma.
2. **Reduced motion**: las leyendas siguen cruzando por scroll (son el contenido; ocultar tres de cuatro quitaría texto, no movimiento), sin el lift de 26 px; el vídeo queda en el fotograma 0.
3. **Móvil conserva lo que la mesa de 390 recorta**: la tarjeta del Valle, la 4.ª tarjeta de «cómo trabajamos» y la lista de credenciales.
4. **No se adopta**: el zoom de mesas fijas, la activación de dos vídeos, el Lucide por CDN, los enlaces muertos del pie (Fair Housing/Privacy/Terms) ni la hamburguesa sin función del móvil.
5. **Copy**: la leyenda 2 del diseño nombra a «Natalia and Robbie» y a la brokerage en el cuerpo; aquí va sin nombres (los hechos de negocio salen de `lib/landing.ts`, regla de la landing). La promesa «respuesta real el mismo día, fines de semana incluidos» de la leyenda 3 **ya estaba publicada** en `landing.how.answered.body`.

### Checklist de «terminado»

| Ítem | Resultado |
|---|---|
| `tsc --noEmit` | limpio |
| `vitest run` | **160/160** (i18nParity cubre las 11 claves nuevas) |
| `next build` (con los `NEXT_PUBLIC_LANDING_*` de producción) | compila |
| Suite backend desde base recreada | **1374 passed** (4 min 22 s); 0 saltados |
| `ruff check app tests` | limpio |
| `docker build` | **no ejecutado en local**: la imagen del frontend se construye en el VPS en el deploy; `next build` local con el mismo `package.json` es la señal que hay |
| Cobertura | **sin instrumento**: el repo no tiene cobertura de frontend (los tests son de `lib/`, no de componentes; sin jsdom). El backend solo cambia una constante de versión. Se dice, no se omite |
| Mutación | no hay guard nuevo con test que mutar; lo que protege el cambio es la medición en navegador de arriba |
| Secretos en el diff | ninguno (los valores `NEXT_PUBLIC_LANDING_*` del build local son los que ya pinta la landing pública) |
| Auditoría de cierre | ⚠️ **auto-auditoría, no independiente**: el subagente auditor murió por límite de sesión de la API (429, se reinicia 19:30 Denver) antes de leer nada; el árbol quedó intacto (verificado con `git status`). Hice yo los 8 puntos que le había dado. Hallazgos: **(importante, a11y)** los dos botones de la leyenda 4 eran enfocables con Tab estando invisibles — `opacity:0` no saca del orden de tabulación; el diseño original tiene el mismo defecto. Arreglado: las leyendas ocultas pasan también a `visibility:hidden` (motor + clase `invisible` inicial), medido con 12 Tabs reales desde el tope. **(menor)** el token `ln-warm` de v4 quedó huérfano: borrado. Limpio: claves i18n ×2, CSS generado por Tailwind (7 reglas nuevas presentes en el bundle), limpieza del `useEffect` (todo lo registrado se quita), `ConsultForm` y `/login` sin diff, ningún hecho de negocio en el copy nuevo, sin secretos |
| Test nuevo `landingHero.test.ts` (5) | fija los dos puntos «que se rompen en silencio»: el `<video>` sin `autoPlay`/`loop` y el motor sin `.loop = true`; las leyendas 2–4 con `opacity-0 invisible pointer-events-none` iniciales. **Mutaciones** (guardar, mutar, rojo, restaurar; md5 idénticos al final): `loop` en el `<video>` → rojo · quitar `invisible` de las leyendas → rojo · `v.loop = true` en el motor → rojo · control sin mutar → 5/5 |
| Teclado (Playwright, 12 Tabs desde el tope, 1440 y 390) | el foco recorre nav → idioma → carril → formulario; **ninguna parada dentro de una leyenda oculta**. Las leyendas ocultas miden `visibility: hidden`; las visibles, no |
| Navegador a 1440 y 390 con scroll real | ✅ medido arriba; capturas en el scratchpad de la sesión |
| **No medido**: Safari iOS | `dvh`/`svh` con la barra plegándose — mi Chrome no lo reproduce. Decisión escrita en `Hero`: host `svh` (el documento no cambia de largo), stage `dvh` (la película llena lo visible); el denominador de `p` se mueve una vez, poco, al plegarse la barra |

### 🚦 DESPLIEGUE PREPARADO — NO EJECUTADO (falta autorización del dueño en mensaje aparte)

Sin migración. `APP_VERSION` cambia en `config.py`, así que **se reconstruyen backend y frontend**.

1. Bundle incremental desde el Mac: `git bundle create /tmp/v069.bundle ^8d0a47a feat/landing-v6` → `scp` al VPS → `git fetch /tmp/v069.bundle refs/heads/feat/landing-v6:refs/deploy/landing-v6` → `git merge-base --is-ancestor HEAD refs/deploy/landing-v6` → `git merge --ff-only refs/deploy/landing-v6`.
2. `docker compose build backend frontend` (las `NEXT_PUBLIC_LANDING_*` son build args: **rebuild, no restart**).
3. `docker compose up -d backend frontend`.
4. Verificar por el dominio: `/api/v1/health` → `0.69.0`; `curl -sI https://www.denverhomestory.com/landing/hero-poster.jpg` → 200 y `…/hero-plate.jpg` → 404; en el navegador del dueño: la casa se queda fija mientras las cuatro leyendas se turnan y el vídeo avanza con el scroll; el formulario sigue enviando (no se tocó).
5. **Reversión**, literal: en el VPS `cd ~/Eko-AI-RealEstate && git reset --hard 8d0a47a` → `docker compose build backend frontend` (las dos: `APP_VERSION` vuelve a 0.68.0 y el frontend hornea sus build args) → `docker compose up -d backend frontend` → `/api/v1/health` → `0.68.0`. **Árbol del VPS medido el 3-sep**: HEAD `8d0a47a`, 0 ficheros trackeados modificados, 0 sin trackear no ignorados — `reset --hard` no tiene nada vivo que pisar (el `.env` está ignorado y `reset` no toca lo no trackeado). Sin datos que revertir. Vecinos `zorros-*`/`blackvolt-*`: intocables.
6. **No medido desde aquí** (Chrome de escritorio no lo reproduce): Safari iOS con la barra plegándose (`dvh`/`svh`) y el color del rebote superior; **`docker build` no ejecutado en local**. El proyecto remoto de Claude Design **no se comparó** con la copia local: la MCP pide `/design-login`.

---

## ✅ DESPLEGADO — v0.67.11 (tachar el token) + v0.68.0 (la cola con fecha) — dos verificaciones se miden solas

### Consultas al advisor (Fable 5.1, autor del plan)

| # | Motivo | Decisión |
|---|---|---|
| 2 | Cierre final: coherencia entre fases y riesgos de despliegue | Señaló que B1 y la rama «post borrado» estaban en tensión y que **nadie había medido** cómo responde Buffer a un id inexistente. Medido: devuelve `errors` con `code: NOT_FOUND` y **`data: null` para el lote entero** — así que mi arreglo B1 habría parado la reconciliación completa para siempre tras un solo post borrado, y la rama «alias null = borrado» era **inalcanzable en producción**. Reescrito para casar errores con su alias por `path`. También: cobertura contra la base medida (faltaba), aserción muerta borrada, y el estrangulamiento del tope diario al backlog. |
| 1 | Arranque: validar lectura del plan, orden, dependencias, riesgos | Lectura correcta. **Rama** `feat/fase0-tachar-token` desde `e321f95` (el plan citaba `feat/cierre-dominio-primero`, que ya no es HEAD); el deploy de 0.67.11 **arrastra `e321f95`** (hero 1080p, sin desplegar) y eso va escrito en el pre-deploy. **La Fase 0 NO despliega**: su verificación en `docker logs` pasa al checklist post-deploy. **Cobertura contra `e321f95`**, no contra `main` (que es un señuelo sin la pila). Riesgos aceptados: (a) `httpx` deja la URL en `record.args`, así que el filtro debe pasar por `getMessage()` o el test es verde falso; (b) el barrido AST puede morder a `reconcile_scheduled`; (c) el «día tomado» se calcula en zona local, nunca +24 h en UTC. |

### ✅ DESPLEGADO — 3-sep-2026, autorizado por el dueño en mensaje aparte

Los dos despliegues ejecutados en orden, por bundle incremental sobre
`42ae7440` (lo que corría, v0.67.10), fast-forward en los dos saltos.

| Paso | Resultado real |
|---|---|
| Deploy 1 → `15d62f8` | `/api/v1/health` por el dominio → **`0.67.11`**. Arrastró `e321f95` (hero 1080p), que nunca se había desplegado |
| Filtro en el proceso vivo | `httpx: True`, handler del root `True` — probado dentro del contenedor de producción, no por inspección del código |
| Deploy 2 → `8d0a47a` | build **antes** de migrar · `049_render_progress → 050_publication_schedule` · `up -d` · health → **`0.68.0`** |
| Esquema migrado | `content_publications.scheduled_at` y `.external_url` presentes; `publication_status` = pending, publishing, published, failed, **scheduled** |
| Config efectiva | `CONTENT_SCHEDULE_ENABLED=True`, huecos 20:30 / 18:30 / 08:30, lead 20 min, `BUFFER_SIMULATED=False`, tope 4/día |
| Bucle | `Content publish worker started (every 900s, cap 4 pieces/day, simulated=False)` |
| Estado de la cola | 5 piezas, las 5 `published`; **cero filas por programar**, así que el despliegue no disparó ninguna publicación |
| Vecinos | `zorros-*` y `blackvolt-*` intactos; el obrero del ROG sigue reclamando trabajos con 200 |

🔴 **La receta de verificación del runbook era IMPOSIBLE, y por dos motivos.**
El dueño la ejecutó: `notify_video_ready(8, 1)` devolvió `True` —el aviso salió
de verdad— y aun así `docker logs` no tiene **ninguna** línea de
`api.telegram.org`. No es el filtro:

1. **`docker exec` arranca un proceso aparte.** `docker logs` muestra solo la
   salida del proceso principal, así que un aviso forzado por `exec` nunca puede
   aparecer ahí. Escribí la receta sin pensar de qué proceso sale el log.
2. Y ese proceso **no tenía logging configurado**: `python3 -c` sin importar
   `app.main` no ejecuta `logging.basicConfig`, así que el root se queda sin
   handler y un INFO de `httpx` no se imprime en ningún sitio.

**Lo que sí está medido en el proceso servidor**: el filtro instalado
(`httpx: True`, handler del root `True`) y **7 líneas reales** `HTTP Request` de
`httpx` en `docker logs` —los sondeos a Ollama— **sin sobre-tachado**. Falta la
composición: una URL de Telegram real saliendo tachada por ese log. Se mide
sola con el **primer render entregado**, que dispara el timbre desde el proceso
servidor; hasta entonces es inferencia sobre tres patas medidas, no medición.

**El día local ya está gastado en los tres canales.** Las 15 filas publicadas
caen entre las 23:28 del 2-sep y la 01:34 del 3-sep en hora de Denver, así que
la primera pieza que se apruebe hoy debe irse a **mañana** en los tres canales —
es el test 2 («`published_at` de hoy toma el día») ejecutándose en producción.

**Reversión vigente**: `CONTENT_SCHEDULE_ENABLED=false` + restart. **Nunca**
volver el código atrás una vez exista una fila `scheduled`.

---

### 🚦 Runbook tal como se preparó (queda como registro)

**Dos despliegues, en este orden.** No se juntan: mientras 0.67.11 no esté, cada
aviso vuelve a escribir el token en el log.

**Comprobado antes de nada:** `agent_settings` org 1 → `timezone='America/Denver'`
(válida) y `brokerage_line` presente. Si la zona no fuera usable, nada se
programaría y la consola diría «recibe su hueco en unos minutos» para siempre.

#### Deploy 1 — v0.67.11 (`15d62f8`, rama `feat/fase0-tachar-token`)
- **Sin migración.** ⚠️ Arrastra `e321f95` (hero 1080p), que nunca se desplegó.
- Bundle → `scp ender-vps` → `git fetch` + `merge --ff-only` →
  `docker compose build backend frontend` → `up -d`.
- Verificar: `/api/v1/health` por el dominio → `0.67.11`.
- **Prueba real**: forzar un aviso de Telegram y
  `docker logs eko-realestate-backend --since 2m | grep api.telegram.org` →
  la línea existe y dice `/bot<redacted>/`.
- **Después, el dueño**: revoca el token en @BotFather y repone con
  `~/set-telegram.sh`; y **rota `SERPAPI_API_KEY`**.
- **Rollback**: `git checkout` del commit anterior + rebuild. Sin estado nuevo.

#### Deploy 2 — v0.68.0 (`21ab43e`, rama `feat/fase1-cola-con-fecha`)
- **CON migración 050.** Orden obligatorio: build **antes** de migrar, migrar
  con la imagen nueva, luego `up -d`.
- Variables nuevas: ninguna obligatoria — los cinco settings tienen defaults en
  `config.py`, `.env.example` y `docker-compose.yml`. Se tocan solo para cambiar
  las horas de los huecos.
- Verificar: `/api/v1/health` → `0.68.0`.
- 🔴 **ROLLBACK: el flag, NUNCA el código.** El camino diseñado es
  `CONTENT_SCHEDULE_ENABLED=false` + restart, sin redeploy; el código sigue
  reconciliando lo que Buffer ya tenga. **Volver al código anterior no es
  seguro** en cuanto exista una fila `scheduled`: el enum de Python viejo no
  conoce esa etiqueta y `publish_approved` revienta al leerla, y el `downgrade`
  no puede quitar un valor de un tipo enum de Postgres.

#### Verificación real de la cola (la primera pieza es la prueba)
1. El borrador de tras la medianoche UTC → el dueño lo aprueba.
2. En ≤15 min, tres filas `scheduled`. `scheduled_at` debe caer **mañana** en
   hora Denver, porque hoy los tres canales ya publicaron — es el test 2 en
   vivo: `SELECT platform, status, scheduled_at AT TIME ZONE 'America/Denver'
   FROM content_publications WHERE piece_id=<n>`.
3. En la interfaz de Buffer, el post aparece **programado a esa hora**. Es la
   primera verificación de `customScheduled` + `dueAt` contra Buffer real; si lo
   rechaza, la fila queda `failed` con su mensaje a la vista y el camino de
   vuelta es el flag.
4. La consola: fecha en hora de Denver y una cuenta atrás que **cambia** al
   mirarla dos veces con un minuto de diferencia.
5. Nunca dos el mismo día en un canal:
   `SELECT platform, (scheduled_at AT TIME ZONE 'America/Denver')::date, count(*)
   … GROUP BY 1,2 HAVING count(*) > 1` → **0 filas**.
6. Medir `dailyPostingLimits` (exige `DateTime` completo) para saber la
   profundidad de cola que el plan Free permite.

#### Backlog abierto, con evidencia
- **El tope diario estrangula la cola**: `publish_approved` limita a
  `MAX_PER_DAY − claimed` sobre `(APPROVED, PUBLISHING)` ordenado por
  `approved_at`, y una pieza programada sigue en `PUBLISHING` días con la fecha
  de aprobación más antigua — así que ocupa un puesto del límite en cada tick
  solo para ser saltada. Con 4 en cola, la 5.ª aprobada no se reclama. Es una
  profundidad de cola implícita de `MAX_PER_DAY`, ni diseñada ni testeada; con 2
  borradores/día se toca en dos días.
- Dos ejecuciones solapadas comparten día (la fila reclamada aún no tiene
  `scheduled_at`). Hoy no ocurre: un worker, una réplica, bucle secuencial.
- `_claimed_today` no cuenta piezas reanudadas. Una hora de hueco dentro del
  salto DST se resuelve en silencio. El filtro no ve un traceback (`exc_info`).
- Sin botón «desprogramar»: hoy la salida es borrar el post en Buffer, y el
  reconciliador lo cierra honestamente.

### ✅ Fase 0 — v0.67.11: el token deja de escribirse (3-sep-2026)

Fuga **mía**: `httpx` registra la URL completa de cada petición a INFO y Telegram
lleva el token en la ruta, así que el timbre de v0.67.10 escribió la credencial
viva en `docker logs` la primera vez que funcionó (07:04:34 UTC). Se arregla con
`backend/app/logging_redact.py`: un `logging.Filter` que **tacha, no silencia**
— la línea `HTTP Request … 200 OK` es la única prueba de que un aviso salió.

**Lo que la auditoría destapó y por qué la fase creció:** el docstring que
escribí afirmaba que Telegram era el único que mete una credencial en una URL.
Era falso. `services/discovery.py:295` manda `SERPAPI_API_KEY` como parámetro
`api_key`, y en producción **la clave está puesta y `DISCOVERY_SIMULATED=false`**
— fuga viva, no hipotética. Se añadió tachado de credenciales en query string
**por nombre de parámetro** (un secreto no tiene forma: `api_key=1` es tan
secreto como 64 hex) y la instalación se extendió a los loggers de uvicorn, que
tienen handlers propios con `propagate: false` y registran la query de cada
petición **entrante** (`hub.verify_token` de Meta viaja ahí).

🔴 **Acción del dueño**: rotar `SERPAPI_API_KEY` en serpapi.com. Un comando mío
de verificación imprimió el valor por una máscara mal escrita — error propio,
segunda credencial expuesta en esta tanda. También sigue pendiente revocar el
token de Telegram en @BotFather y volver a poner el nuevo con `~/set-telegram.sh`.

| Criterio | Resultado real |
|---|---|
| Suite backend, base recreada | **1350 passed**, 0 saltados |
| Suite frontend | **153 passed** |
| `ruff check app tests` | `All checks passed!` |
| `tsc --noEmit` / `vitest` | limpio / 153 |
| `docker build -f backend/Dockerfile` | compila |
| Cobertura `logging_redact.py` | **100%** (31/31); no existía en la base |
| Secretos en el diff | ninguno (el token del test es una cadena falsa etiquetada) |
| Sobre-tachado | **0** sobre los 32 literales de URL de `backend/app` |

**Mutaciones — 11, todas rojas.** Dos verdes falsos corregidos por el camino:

- `test_importing_the_app_installs_the_filter` **no podía fallar**: los tests
  anteriores del fichero ya llamaban a `install()`, así que el filtro estaba en
  el logger `httpx` pasara lo que pasara en `main.py`. Comentar la instalación
  dejaba la suite verde. Ahora corre en un intérprete nuevo por subproceso.
- **F4 del auditor**: la mitad de `install()` que recorre los handlers del root
  no tenía ningún test — borrarla dejaba 5 verdes mientras `httpcore`, `urllib3`
  y nuestros propios módulos volvían a gotear. No es redundancia: es lo único
  que cubre a todo logger que no hayamos nombrado. Test nuevo sobre la SALIDA de
  un logger deliberadamente no nombrado.

**Al backlog, con evidencia:** el filtro **no ve un traceback** — `exc_info` lo
renderiza el Formatter, que corre después de todo filtro, y
`httpx.HTTPStatusError` lleva la URL en su mensaje; `render_jobs.py:456` es un
`log.exception` alrededor del timbre, así que un `raise_for_status()` en
`telegram_notify` reabriría la fuga sin que nada se ponga rojo. Escrito en el
docstring del módulo, no solo aquí. Menores: tachado parcial con caracteres
fuera de `[A-Za-z0-9_-]`, `%3A` no casa, token sin prefijo `/bot` no se tacha
(ninguno alcanzable hoy — no hay volcado de settings).

### ✅ Fase 1 — v0.68.0: la cola con fecha y cuenta atrás (3-sep-2026)

Lo que el dueño pidió: *«un contador y fecha de cuándo cada vídeo será
publicado, en la sección de approved»*. No se podía enseñar porque no existía —
un aprobado salía con `shareNow` en el siguiente tick y el 3-sep salieron seis
posts en 107 s. La fecha solo existe si hay cola.

**La regla, en sus palabras**: «se publican 1 por bloque de mejor horario, nunca
dos a la vez». Un hueco al día por canal, a la hora local de ese canal, así que
el mismo vídeo sale a tres horas distintas: «nunca dos a la vez» vale también
entre canales.

| Pieza | Dónde |
|---|---|
| Migración `050_publication_schedule` | `scheduled_at`, `external_url`, estado `scheduled` |
| Planificador | `next_free_slot` / `_day_is_taken` / `agency_zone` en `buffer_publisher.py` |
| Reconciliador | `reconcile_scheduled`, una query con alias al principio de cada tick |
| API | `PublicationOut` +2 campos · `list_pieces` acepta varios estados · `StudioStatus` +`timezone` |
| Consola | pestaña `approved` = `approved`+`publishing`, pestaña **Publicados** nueva, `PublishSchedule`, `timeUntil`, `useNow(30 s)` |

**Tres defectos propios, cazados por sus tests y no por lectura:**

1. 🔴 **Doble publicación.** `publish_piece` salta las filas ya atendidas, y
   dejé `SCHEDULED` fuera de esa lista. Una pieza encolada sigue en
   `PUBLISHING` durante días, así que `publish_approved` la recoge **cada 15
   minutos** — habría vuelto a postear el mismo vídeo en cada tick.
2. 🔴 **El reconciliador retiraba posts vivos.** `_graphql` devuelve el sobre
   GraphQL entero y yo leía los alias del nivel de fuera: `data.get("p0")`
   daba `None` para todos y los tres se marcaban «no longer exists». Una
   lectura correcta habría marcado FALLIDOS todos los posts programados.
3. **Un test inestable mío**: `timeUntil` lee el reloj al ejecutarse, así que
   entre construir la fecha y leerla el límite se cruzaba. Congelado con
   `vi.setSystemTime`; verde tres corridas seguidas.

**Y una corrección a mi propio informe anterior:** dije que `edit_piece` tenía
un agujero en `PUBLISHING`. **Falso** — la guarda estaba ya puesta justo tras el
404; leí el cuerpo del bucle y no la cabecera. `reject_piece` lo hereda de la
máquina de estados. Los dos quedan fijados por un test, porque un `PUBLISHING`
que dura días es nuevo.

| Criterio | Resultado real |
|---|---|
| Suite backend, base recreada | **1365 passed**, 0 saltados |
| Suite frontend | **160 passed**, estable en 3 corridas |
| `ruff` / `tsc` | limpios |
| `docker build` | compila |
| GRANT de `eko_app` sobre las columnas nuevas | INSERT y UPDATE reales verificados con `scheduled` |
| Guardianes AST | verdes **sin exención nueva** — `reconcile_scheduled` vive en el publicador, que el barrido excluye |

**Mutaciones: 8 lanzadas, 7 rojas.** La octava sobrevivió y la respuesta es
honesta, no un test de relleno: quitar el `ORDER BY` del reconciliador **no
cambia ningún comportamiento observable**. Lo añadí creyendo que arreglaba un
emparejamiento erróneo de alias; el emparejamiento erróneo era el sobre GraphQL
(defecto 2). Se queda por la norma de la casa —todo `ORDER BY` se desempata con
`id`— y **el comentario que afirmaba lo contrario está corregido en el código**.

### Auditoría de la Fase 1 — 2 bloqueantes, los dos corregidos en fase

**B1 · Un 200 con `errors` de GraphQL retiraba un post VIVO.** El reconciliador
leía `data` y **nunca miraba `payload["errors"]`** — al contrario que
`parse_create_post`, que sí los trata como fallo. Un `post` limitado por cuota
vuelve como `data:{p0:{…},p1:null,p2:{…}}` **más** un array `errors`, y ese
`null` significa «este campo falló», no «este post ya no existe».

**B2 · Y ese FALLIDO falso publicaba el vídeo dos veces.** Cadena medida por el
auditor de punta a punta: fallo espurio → `_close_piece` cierra la pieza en
`FAILED` → `FAILED` es justo el estado que ofrece **Reintentar** → al
re-aprobar, la rama `fresh` libera las filas `FAILED` y las **reenvía**. Un
error transitorio de lectura terminaba en un segundo post público del mismo
vídeo. El comportamiento de re-aprobación es correcto y se queda; la defensa es
que un `FAILED` nunca se escriba desde una lectura fallida.

**Importantes corregidos también (todos con mutación roja):**

- **Inyección GraphQL + parada permanente.** `external_id` se interpolaba en la
  cadena de la query. Una comilla invalidaba el lote entero, Buffer devolvía
  400 y **todas** las demás filas quedaban sin reconciliar en cada tick, en
  silencio; y un id con forma `") { id } evil: organization(…` añadía un campo
  a nuestra propia query. Los ids viajan ya como **variables GraphQL**.
- **«Rehacer» vaciaba una pieza que Buffer sostiene.** `rebuild_piece`
  rechazaba `PUBLISHED` pero no `PUBLISHING`; borraba `media_path`, la ruta
  pública devolvía 404 a la hora del hueco y la pieza quedaba colgada para
  siempre. La guarda es nueva porque el estado es nuevo: antes `PUBLISHING`
  duraba segundos.
- **Un estado que Buffer añada dejaba la pieza colgada en silencio.** Sigue sin
  inventarse un veredicto, pero ahora se grita: `log.error` nombrando las filas.
  Y un `sending` con un objeto `error` transitorio ya no se retira.
- **Cinco invariantes solo cubiertas en el modo apagado.** Los 25 tests previos
  se fijaron a `CONTENT_SCHEDULE_ENABLED=False`, y eso dejó pausa de cuota,
  re-aprobación, tope diario y fallo parcial sin gemelo en modo cola — que es
  el de producción. **La re-aprobación es el paso 4 de B2 y no la miraba nada.**
  Cuatro gemelos añadidos.
- 🔴 **Un test mío no podía ver el fallo que nombraba.**
  `test_a_denver_evening_is_the_next_utc_day` corría sobre tabla vacía, así que
  `_day_is_taken` nunca se consultaba y la mutación que su propio docstring
  describe lo dejaba **verde**. Ahora siembra la fila reservada, y enrojece.

**Al backlog, con evidencia:** dos ejecuciones solapadas comparten día (la fila
reclamada aún no tiene `scheduled_at`); hoy no ocurre —un worker, una réplica,
bucle secuencial— pero la regla depende de un supuesto de despliegue y no de la
base. `_claimed_today` no cuenta piezas reanudadas. Una hora de hueco dentro del
salto DST se resuelve en silencio.

**Confirmado sano por medición, no por razonamiento:** DST en las dos
transiciones de Denver sin día saltado ni repetido; RLS aísla los huecos entre
agencias (la agencia A no pierde ni ve los de B); una pausa de cuota no gasta
día; dos piezas del mismo tick sí se ven entre sí.

| Criterio final | Resultado |
|---|---|
| Suite backend, base recreada | **1374 passed**, 0 saltados |
| Suite frontend | **160 passed** |
| `ruff` / `tsc` | limpios |
| Mutaciones | 8 de la fase (7 rojas, 1 sin efecto observable y documentada) + **6 de los arreglos, todas rojas** |

### 🔴 Lo que Buffer hace de verdad con un post borrado (medido, refuta el plan)

El plan decía «post inexistente (`null`) → FAILED». **Falso.** Consulta real
con un id bien formado que no existe:

```
{"errors":[{"message":"Post not found for id: 0000…","path":["p1"],
            "extensions":{"code":"NOT_FOUND"}}],"data":null}
```

Dos consecuencias, las dos contra lo que estaba escrito: Buffer **no** devuelve
un `null` limpio para un post borrado —devuelve un error—, así que esa rama era
inalcanzable; y **un solo id malo anula `data` del lote entero**, de modo que un
post borrado habría dejado todas las demás filas sin reconciliar en cada tick,
para siempre y en silencio. El reconciliador casa ahora cada error con su alias
por `path`: `NOT_FOUND` es un veredicto sobre ESE post, cualquier otro código es
una lectura que falló y la fila se pregunta otra vez. Cuatro mutaciones sobre
esta lógica, las cuatro rojas.

**Cobertura contra la base `e321f95`** (el checklist la exigía y faltaba):
`buffer_publisher.py` **84% → 87%** con 128 sentencias más, `content.py`
56% → 56%, total 67% → 72%. No baja.

### 🔴 La verificación de la Fase 1 hay que rehacerla (medido 3-sep)

El plan dice «aprobar la pieza 3 con v0.68.0 desplegada» y «3 y 5 esperan a la
cola». **Caducó**: las cinco piezas (3, 5, 6, 7, 8) están `published` con sus 15
filas en `published` — el dueño las aprobó y el `shareNow` de hoy las sacó.
`PUBLISHED` es terminal: **no queda pieza con la que probar la cola**. El
sustituto natural es el borrador que el estudio genera tras la medianoche UTC
(`CONTENT_MAX_DRAFTS_PER_DAY=2`), y de regalo cae en el caso que más importa:
hoy los tres canales ya publicaron, así que el primer hueco libre es **mañana**.
No es avería: el tope diario aguantó (la pieza 3 no gastó presupuesto porque sus
filas eran del 31-ago, pieza reanudada). Y la pieza 8 publicada **cierra la
verificación de v0.67.9**.

### Mediciones para la Fase 1, ya hechas

| Qué | Medido | Consecuencia |
|---|---|---|
| `PostStatus` de Buffer | `draft · error · needs_approval · scheduled · sending · sent` | el estado de fallo **es `error`** — el plan lo daba por no verificado |
| `PostPublishingError` | `message · rawError · supportUrl` | `last_error` sale de `message` |
| `pg_enum` (`db/base.py:32`) | usa `values_callable` con `.value` | `ADD VALUE 'scheduled'` casa con `SCHEDULED = "scheduled"` |
| Barrido AST vs `reconcile_scheduled` | `test_only_the_guarded_entry_point_reaches_the_wire` excluye `buffer_publisher.py`; el test de orden solo inspecciona `publish_piece` | **sin exención nueva** si vive en el publicador y lo llama `publish_approved` |
| El agujero de `edit_piece` | `content.py:386-396` confirmado | 409 en `PUBLISHING` (1e) |

---

## ✅ v0.67.9 y v0.67.10 — LA VOZ INVITA A LA WEB, Y HAY TIMBRE (3-sep-2026)

### v0.67.9 — el cierre hablado

El vídeo ya **enseñaba** el dominio 3 s; ahora el locutor lo **dice** en el mismo
instante. Escrito fonéticamente —`Denver Home Story dot com`— porque
`worker/spoken.py:116` borra cualquier URL antes de que el locutor la vea, y esa
regla es correcta: leída en alto, una URL es «denverhomestory punto com» en el
mejor caso. Como palabras no hay nada que borrar, la regla **no se toca**, y el
cierre llega gratis a los subtítulos amarillos porque se transcriben del audio.

**Tres líneas rotando**, escritas a mano: una fija se oye 30 veces al mes, y una
que escriba el modelo cada día acaba prometiendo de más. Se descartó la variante
del dueño «le responderán todas sus preguntas» — el embudo real es que Natalia
devuelve la llamada.

🔴 **Riesgo que el advisor cazó y la base confirmó**: el modelo **nunca** devuelve
`narration` — en las cuatro piezas de producción `length(narration)` es
**exactamente** `length(script)`. Añadir el cierre al campo crudo habría dado una
narración compuesta **solo por el cierre**: un vídeo de 4 s. Se materializa desde
`script`.

**Corrección a mi propio plan, y al advisor**: dijimos que añadirlo en
`_scene_plan` esquivaría el filtro. **Falso** — `_all_violations` llama a
`_scene_plan` él mismo. El sitio sigue siendo `_with_cta` por otras razones
(acceso al índice y al setting, y `_scene_plan` es un serializador puro), pero la
mutación planeada no habría enrojecido. La usada: cegar el filtro a la narración.

### v0.67.10 — el timbre en Telegram

Se avisa en cuanto un vídeo puede aprobarse. **Reutiliza el bot de EkoRog** por
decisión del dueño, como función extra y **sin tocar nada suyo**: enviamos con su
identidad a la API de Telegram; su código, su unidad y su comportamiento quedan
igual. Comprobado de paso: `eko-rog-bot` está **desactivado** ahora mismo y **da
lo mismo** — el aviso no pasa por su proceso.

⚠️ **Reserva registrada**: ese bot lo administra otro proyecto. Si rotan el token
enmudecemos y el síntoma será «no me llegó el aviso». Está escrito en el módulo.

- Dispara sobre el **estado resultante**, no sobre la transición: una pieza
  generada limpia **ya** está en `NEEDS_APPROVAL` cuando llega el render — la
  forma del incidente de la pieza 5 — así que un timbre atado al `advance`
  callaría en el camino más común. **Mutación verificada**: al atarlo a la
  transición, el caso `needs_approval` se pone rojo.
- **Enlace, nunca el guion.** Un mensaje con el texto invita a aprobar desde el
  móvil sin ver el vídeo, que es lo único que la puerta existe para impedir.
- El **barrido de bajas cazó el módulo solo** antes de que yo lo declarara —
  segunda vez hoy que un guardián de este repo hace su trabajo.

### Estado y lo que falta
- **1343 backend + 153 frontend** verdes, `ruff` y `tsc` limpios. Desplegado y
  verificado por el dominio: `0.67.10`.
- Desplegado **inerte**, confirmado en producción: `undeliverable_reason()` →
  `TELEGRAM_BOT_TOKEN is unset`; el enlace ya resuelve a
  `https://inmo-demo.ekoaiautomation.com/content`.
- 🔴 **Faltan dos valores del dueño**: `TELEGRAM_BOT_TOKEN` (el de EkoRog) y
  `TELEGRAM_CHAT_ID`. Van al `.env` del VPS tecleados o por tubería; el agente no
  los ve.
- 🔴 **Las piezas 6 y 7 NO tendrán cierre hablado, ni rehaciéndolas**: el cierre
  se añade al ESCRIBIR el guion y ellas ya tienen su `scenes.narration` guardada.
  El primer vídeo con voz invitando es el de esta tarde (~18:05 MDT), o se fuerza
  hoy subiendo `CONTENT_MAX_DRAFTS_PER_DAY` a 2 — cuesta un guion y una
  narración; **decisión del dueño**.

### Advisor
- **Arranque** → validó las dos fases e independientes; cazó los tres riesgos
  (narración None, condición del timbre, early-return de `_with_cta`) y corrigió
  la verificación de mi plan. Los tres verificados por mí antes de aplicarlos; el
  primero confirmado con datos de producción.

---

## ✅ REHACER UN VÍDEO, Y UNA COLA QUE NO MIENTE (3-sep-2026) · v0.67.7 y v0.67.8

El dueño rehizo las dos piezas a las 22:48 y vio «El vídeo se está haciendo»
durante una hora sin que pasara nada. **No estaba roto: en el ROG eran las 22 y
esa hora no está en su ventana** (13, 15, 16, 17, 21, 23, 1, 2). Verificado con
hecho, no con explicación: el obrero reclamó el primer trabajo a las
**23:00:44**, 44 segundos después de abrirse la ventana.

- **v0.67.7 — `POST /content/{id}/rebuild`.** Una pieza renderizada era
  definitiva: la única forma de tener un vídeo con un cambio del montador era
  esperar al guion de mañana, cosa rara que decirle a quien acaba de cambiar el
  montador porque no le gustó el vídeo. Se rehace desde las `scenes` de la
  propia fila. Cuesta una narración; las imágenes vuelven de la caché.
  **Un clip GRABADO se rechaza**: no tiene plan del que rehacerse y su
  `media_path` es la única copia de lo que se filmó. Mutación verificada.
- **v0.67.8 — la cola dice lo que pasa.** El mismo giro servía para tres
  situaciones distintas. `render_jobs` gana `stage`/`progress` (el obrero los
  rellena mientras narra, transcribe, busca imágenes y monta) y `monitor_state`
  gana `detail`, donde el latido registra si el tick cayó dentro de su horario
  — **fuera de la lógica de alarmas a propósito**: estar fuera de ventana es el
  obrero portándose bien, no una avería. La barra **nunca** se inventa en el
  cliente: sin informe es indeterminada, porque una barra que avanza sola es una
  mentira con animación. Migración `049_render_progress`.

### Verificado contra el sistema vivo
- Reclamo a las 23:00:44 UTC-6, medido en `render_jobs.claimed_at`.
- Progreso real leído en la base durante el montaje: `finishing`, **88%**.
- `monitor_state.detail` → `{"hours": [1,2,13,15,16,17,21,23], "within_hours": true}`.
- **Pieza 6 rehecha y su fotograma MIRADO**: cierre nuevo, `denverhomestory.com`
  grande en la caja y la brokerage pequeña debajo, sobre foto real.
- 1329 backend + 153 frontend en verde, `ruff` y `tsc` limpios. Un test nuevo
  afirma que el listado **devuelve** `render_state`/`stage`/`progress` — sin él,
  arreglar el giro no valdría nada si el campo no llega al navegador.

---

## ✅ EL CIERRE INVERTIDO: EL DOMINIO MANDA (2-sep-2026) · rama `feat/cierre-dominio-primero`

El dueño miró el último fotograma y vio lo contrario de lo que quiere: la línea
legal en caja negra a 48 px, y `denverhomestory.com` en crema a 40 px **sin
caja**, lavándose contra una foto clara. Los vídeos existen para llevar tráfico
a esa dirección.

**Ahora**: dominio en blanco a 64 px **en la caja**, arriba. Brokerage a 34 px
con **borde** en vez de una segunda caja — dos cajas apiladas pesan más que la
imagen que etiquetan. Tarjeta final en 3 s, sin tocar; los dos `enable=` y la
etiqueta `[out]` intactos.

**Blanco y no el crema de marca, y eso se midió**: sobre un fotograma claro el
crema dejó **cero** píxeles de relleno — las letras se leían como contornos
huecos, porque `#F5E6C8` y una foto pálida son el mismo color. En blanco, 3.984
px de cuerpo. La separación bajo la caja se **deriva** del cuerpo y del relleno
de la caja, no se elige. Medido en el ROG: caja 857 px de 1080, brokerage 433.

**Colorado exige IDENTIFICAR la brokerage, no que domine.** Un test fija el
suelo en 32 px para que un recorte futuro no convierta la identificación en un
trámite ilegible.

### Terminado (verificado, no por inspección)
- `pytest worker/tests` → **70 pasan**, código de salida 0. Mutación: intercambiar
  los dos cuerpos → `test_the_domain_leads_and_the_brokerage_follows` en rojo,
  restaurado en verde.
- `ruff check ../worker` → los **3 hallazgos previos**, ninguno nuevo (un import
  sin usar y dos órdenes de import en ficheros de test; `worker/` nunca estuvo
  en la puerta del protocolo, que es `ruff check app tests`).
- Fotograma renderizado en el ROG y **mirado**, sobre fondo claro **plano** —
  que es el peor caso para el crema y por eso refuerza el cambio a blanco.
- `test_a_real_render_is_vertical_and_carries_the_mark` corre el `build_command`
  completo sobre fondo con textura y **afirma la correlación de la marca ≥ 0,15**
  (`test_worker.py:325`): la tarjeta NUEVA pasa la comprobación de marca.
- Sin secretos en el diff; sin prints de depuración.
- Cobertura: **no medida**. El diff es solo del obrero y entra con dos tests
  propios que cubren las líneas nuevas, pero no he corrido `pytest-cov` contra
  la línea principal para compararla — lo digo en vez de afirmarlo.

### Advisor
- **Cierre** → fase correcta y cerrable; pidió comprobar el job 8 tras mis
  reinicios (resultado: `done`, attempts=2, se auto-recuperó y la pieza 7 tiene
  vídeo), cerrar el punto 4 con el test de render real, y corregir dos
  imprecisiones de este mismo documento. Aplicado todo.
- **Arranque** → plan validado, una sola fase, sin dependencias. Riesgos que
  nombró: (1) el desplazamiento vertical viejo no libra la caja nueva → derivado;
  (2) el test no puede leer los textos porque van por fichero → identifica cada
  cláusula por `d.txt`/`b.txt`; (3) no perder `[out]` ni los dos `enable=` →
  comprobado por test. Corrigió además mi cuenta de tests (68, no 64).

- **Auditoría de subagente: NO lanzada** en esta micro-fase (diff de ~40
  líneas). En su lugar: mutación verificada, fotograma mirado y tres
  mediciones. Si el dueño la quiere igualmente, se lanza.

### 🔴 Hallazgo abierto, con evidencia — NO es de esta fase
`verify.brand_is_present` **da un falso negativo sobre un fotograma pálido y
plano**. Aislado sin una sola línea de texto: fondo claro plano → **0,090**
(umbral 0,15, rechaza); fondo oscuro plano → 0,994; fondo con textura → 0,551.
Muestrea en **t=1,0 s**, o sea la PRIMERA escena: si esa foto es pálida y de poca
textura, el trabajo entero se rechaza tras haber pagado la narración. Los
renders reales dieron 0,416 y 0,927, así que no está demostrado con una foto de
verdad — pero el mecanismo sí. Dirección: comparar contra la marca **compuesta
sobre el fondo local**, o correlacionar solo los píxeles opacos de la marca.

### Siguiente paso
Rama `feat/cierre-dominio-primero` **sin fusionar y sin PR** (norma del dueño).
**Verificado mirando el fotograma**: la pieza 6 y la 7 llevan la tarjeta
**vieja** (brokerage grande en caja, dominio pequeño debajo). Se montaron antes
de este cambio. Decisión del dueño: aprobarlas así o reconstruirlas, y cada
reconstrucción cuesta una narración de MiniMax.

⚠️ El ROG corre ahora el código de esta rama. Si la rama se descarta, hay que
redesplegar el obrero desde la línea principal.

---

## ✅ EL TITULAR DE CADA ESCENA, YA DIBUJADO (2-sep-2026)

Decisión del dueño: **dibujarlo sobre cada foto**. Hasta ahora el modelo lo
escribía, el filtro Fair Housing lo revisaba y **nadie lo pintaba** salvo en la
tarjeta de respaldo, que ya no se usa.

Geometría **medida dos veces**, y la primera estaba mal de una forma que merece
quedar escrita: medí con la fuente **por defecto** de drawtext (27,3 px por
carácter) y el obrero pasa `DejaVuSans-Bold`, más ancha. Renderizado de verdad,
«Mid-Range: Single-Family Homes» ocupó **1029 px de 1080** — 25 px de margen — y
a 34 caracteres llegaba a 1080 exactos, o sea recortado. Máquina correcta,
fuente equivocada. Con la fuente real: **48 px y 30 caracteres por línea**, dos
líneas = 60, que es justo el tope que `content_writer` pone a `on_screen_text`.

Y un defecto que **solo se veía mirando el fotograma**: con un `\n` dentro de un
solo `drawtext`, este ffmpeg parte la línea **y además dibuja el salto como una
caja de glifo ausente** al final. Invisible en toda medición, porque la caja cae
dentro de la caja envolvente que mide el ancho. Ahora va **un `drawtext` por
línea**, cada uno centrado por su cuenta.

**Decisión del dueño sobre la brokerage**: se queda **solo quemada en el vídeo**,
no va al pie del post. No se toca `_with_cta`.

---

## 🟡 EL ROG SE QUEDA SIN MEMORIA, Y NO ES NUESTRO (2-sep-2026)

Aviso de la sesión «Bittrader Youtube», **verificado aquí en el journal** y no
aceptado de palabra: ComfyUI murió por OOM tres veces esta madrugada (04:11,
04:15, 04:19), con `Failed with result 'oom-kill'` y 7,5 GB residentes en el
proceso matado. La secuencia encaja con su reconstrucción: 04:09:22 un
`GET /v1/models` desde **127.0.0.1** (endpoint compatible OpenAI) y 04:09:31 un
runner de Ollama cargando un modelo qwen2 — el tag de 9,0 GB, no el de 3,3 que
usa nuestro fallback. Ellos lo trazan a la config viva de openclaw; **eso no lo
he verificado y no abro esa config**, no es nuestra.

**Nuestra exposición, medida:** el obrero no estaba corriendo (las 04 no están en
su ventana) y su pico es modesto — Whisper int8 y ffmpeg. Pero openclaw puede
pedir ese modelo a cualquier hora, y un render matado a media faena **ya pagó su
narración de MiniMax**; el reintento la paga otra vez.

**Lo hecho, solo en lo nuestro:** el tick del obrero se niega a empezar si
`MemAvailable` baja de **1,5 GB**, igual que ya se negaba por disco.

El umbral empezó en 3 GB **elegido a ojo**, y la otra sesión nombró lo que eso
cuesta: un listón por encima de lo que de verdad necesitamos se niega a trabajar
en una máquina que puede alojarnos, y con el modelo grande residente eso dura
horas — callar el canal para evitar un coste que nunca se produjo. Medido en vez
de estimado: Whisper `small.en` int8 sobre 30 s de narración **0,57 GB**, y el
ffmpeg más pesado (zoompan a 1080x1920) **0,75 GB**, y van en secuencia. 1,5 GB
es el doble del pico real, con test que fija que **con 3,4 GB disponibles sí
arranca**. Sin bump: no cambia comportamiento visible para el cliente.

**Su corrección, aceptada**: en BitTrader no se perdió ningún vídeo — systemd
reinició ComfyUI y la corrida terminó en `[retry-ok]`. El coste fue reintentos y
tiempo. En NUESTRO carril sí se pagaría dos veces la narración (verificado:
`tts.narrate` escribe en un workdir que se borra en el `finally`; solo las
imágenes tienen caché), que es lo que justifica el guard aquí y no allí.

**Atribución cerrada por ellos**: la config viva de openclaw declara el proveedor
`local` con `baseUrl http://localhost:11434/v1` y el modelo `qwen2.5:14b` con
32K de contexto — el `/v1/` es el endpoint del `GET /v1/models` que medí a las
04:09:22. El pico real supera los 9 GB del fichero por el contexto.

🔴 **Decisión del dueño, no nuestra**: modelo más pequeño en openclaw, limitar
concurrencia, o ampliar RAM. 15 GB para tres proyectos es el problema de fondo.

---

## 🔴 v0.67.5 + v0.67.6 — LO QUE APARECIÓ AL MIRAR LAS OTRAS PIEZAS (2-sep-2026)

### El post que espera en la cola de otro no está publicado (v0.67.5)

`CreatePostInput.needsApproval` es **non-null** en el esquema de Buffer y no lo
mandábamos: funcionaba por su defecto. Si ese defecto fuera `true`, el post se
quedaría en la cola de aprobación **de Buffer** mientras `createPost` nos
devuelve un id, y habríamos registrado PUBLISHED para algo que nadie publicó.
Va explícito en `false`.

De paso: `test_the_voice_lane_books_a_seller_on_the_valuation_calendar` reservaba
«dentro de 3 días» y la oficina abre de lunes a viernes — pasaba o fallaba según
el día de la semana en que se corriera la suite. Desde un lunes caía en jueves;
hoy, miércoles, cayó en **sábado**, la reserva se rechazó correctamente y el
fallo decía «the booking never reached Cal.com», que suena a carril roto y era
un fin de semana. Ahora aterriza siempre en laborable.

### No se puede aprobar un vídeo que no existe (v0.67.6) — avería REAL en producción

**La pieza 5 está `approved` sin vídeo, y lo estará para siempre.** El dueño la
aprobó el 1-sep a las 01:59, cuando la pieza llevaba en `needs_approval` desde
que su texto pasó el filtro pero el montaje seguía corriendo. Al entregar el
fichero, `_refuse_unless_awaited` devolvió **409** —correctamente: ya no esperaba
render— tres veces, y el job 6 murió. No se publicó **solo** porque el publicador
exige `media_path`: suerte, no diseño.

Dos guardas correctas por separado se comieron el caso de en medio. Ahora la API
rechaza aprobar sin `media_path` diciendo por qué, y la cola muestra «el vídeo se
está haciendo» donde estaba el botón.

### 🟢 ESTADO DE LAS PIEZAS (2-sep, medido)

| Pieza | Estado | Vídeo | Qué hacer |
|---|---|---|---|
| 3 | `failed` | sí | **Reintentar** + **Aprobar** (dos clics) — o dejarla |
| 5 | `approved` | **no** | 🔴 **rechazarla**: no tiene arreglo, su job murió con 3 intentos |
| **6** | `needs_approval` | **sí** | 🟢 **el camino limpio: un solo clic en Aprobar** y sale a los tres canales |

La 6 se montó hoy, ya con los subtítulos amarillos y el final completo. Es la
candidata al primer post real.

### 🔴 SIGO BLOQUEADO EN LO MISMO, Y ES DE DISEÑO

Aprobar exige sesión (`AUTH_ENABLED=true`) y **no me fabrico una**: esa puerta es
la que hace que un humano con licencia responda de lo que se publica. El
clasificador también bloquea escribir el estado a mano en la base de producción,
y hace bien.

`CONTENT_PUBLISH_INTERVAL_SECONDS` sigue **temporalmente en 60** (era 900).

---

## 🔴 v0.67.4 — LA PRIMERA PUBLICACIÓN REAL: TRES RECHAZOS (31-ago-2026)

El dueño aprobó la pieza 3 y preguntó por qué no salía en ningún lado. No salía
porque la publicación estaba apagada a propósito (`CONTENT_PUBLISH_ENABLED=false`,
`BUFFER_SIMULATED=true`). Encendida —**con los tres canales a la vez, decisión
del dueño frente a mi recomendación de ir uno a uno**— Buffer rechazó los tres,
cada uno por un motivo distinto.

| Canal | Lo que dijo Buffer | De quién era |
|---|---|---|
| TikTok | «Video could not be read from its URL» | **nuestro**: `HEAD` a la ruta pública → **405** |
| YouTube | «require a title… require a category» | nuestro: no mandábamos ninguno |
| Instagram | «require a type (post, story, or reel)» | nuestro: faltaba declararlo reel |

**Nada se publicó**: los tres sin `external_id`, rechazados al crear el post.

### El 405, que es el interesante

Starlette añade `HEAD` a toda ruta que responda `GET`; **el `APIRoute` de
FastAPI no**. Buffer sondea con `HEAD` antes de descargar, recibía 405 y
concluía «no pude leer el vídeo» — un mensaje que apunta al fichero, a la URL y
al túnel, y ninguno era el problema. La ruta ya responde `GET` y `HEAD`, con la
misma puerta de estado (medido: con la pieza en `failed`, `HEAD` da **404**, no
405 — el método se acepta, lo que rechaza es el estado).

### Los metadatos, leídos del esquema y no adivinados

Introspección de `YoutubePostMetadataInput`, `InstagramPostMetadataInput` y
`TikTokPostMetadataInput`: `categoryId` (no «category»), `type: "reel"`,
`shouldShareToFeed`. Los tres exponen `isAiGenerated`, así que se declara en los
tres. Y `CreatePostInput.needsApproval` es **non-null y no lo mandábamos**: si su
defecto fuera `true`, el post se quedaría en la cola de aprobación **de Buffer**
mientras `createPost` nos devuelve un id igual — habríamos registrado PUBLISHED
para algo que nadie publicó. Ahora va explícito en `false`.

### El aviso de IA era falso

El pie decía «Contains AI-generated visuals» sobre un vídeo donde **cada imagen
es una fotografía con licencia de Pexels**. Lo sintético es la voz. Sobre-declarar
sigue siendo una afirmación falsa en publicidad de dos agentes con licencia.
Ahora: «Narrated with a synthetic voice.» — cierto en toda pieza de este carril.
La pieza 3 conserva el texto viejo a propósito: cambiarlo publicaría algo que el
dueño no aprobó.

### `failed` era un callejón sin salida

La única salida era un `UPDATE` a mano en producción. Hay endpoint
`POST /content/{id}/retry` y botón en la consola; devuelve a **NEEDS_APPROVAL**,
no a APPROVED — aprobar otra vez cuesta un clic y conserva la invariante de que
un humano aprobó exactamente lo que salió.

### 🔴 BLOQUEADO, y es de diseño

La pieza sigue en `failed`. Reintentarla exige los dos clics del dueño: la API
está tras `AUTH_ENABLED=true` y **no me fabrico una sesión** — esa puerta es la
que protege el carril. El clasificador también bloquea escribir el estado a mano
en la base de producción, y es correcto que lo haga.

`CONTENT_PUBLISH_INTERVAL_SECONDS` está **temporalmente en 60** (era 900) para
que el reintento no tarde quince minutos. Devolver a 900 tras el primer post.

---

## ✅ v0.67.3 — LOS SUBTÍTULOS Y EL FINAL QUE FALTABA (31-ago-2026)

El dueño pidió dos cosas mirando el vídeo generado: subtítulos amarillos con la
palabra creciendo al pronunciarse, «como en The Power Unleashed», y que **«al
final sale cortado, no termina»**. La segunda resultó ser un fallo serio.

### El corte: cada pausa entre escenas no pertenecía a ninguna escena

`plan_shots` daba a cada escena el tramo de la primera a la última palabra de su
grupo. El silencio ENTRE grupos no lo cubría nadie, así que la pista de imagen
salía más corta que la voz por la suma de esas pausas y `-shortest` se llevaba
la diferencia del final. **Exit 0, sin log, sin error.** Medido: el guion de la
pieza 3 termina en «...the specifics of your situation.» y el vídeo entregado se
paraba en «the» — cuatro palabras menos, en una pieza que ya se le había
enseñado a una persona.

- Las escenas **teselan** el audio: el corte cae donde EMPIEZA la primera
  palabra de la siguiente, que sigue siendo frontera de palabra y no pierde
  tiempo.
- `-shortest` fuera: `apad` + `-t` explícito. Un desajuste de longitud ahora
  añade silencio, nunca quita voz.
- Y **se mide**: si la imagen dura menos que la última palabra, el montaje falla
  con el motivo en la consola en vez de entregar un vídeo sin final.
- El end-card se temporiza contra la duración **medida**, no la planificada — si
  no, la identificación de la brokerage se queda fuera del cuadro.

### Los subtítulos: amarillos, y la palabra hablada crece

`#FFFF00` con borde negro grueso, palabra activa al 126%, un evento ASS por
palabra. Forma leída de `~/BitTrader/agents/karaoke_subs.py` (solo lectura).

### Y lo que destapó: cuatro palabras no son una anchura

Medido en el ROG **con su tipografía**, no con la del Mac: la línea
«certain features, certain neighborhoods.» del guion real renderizaba **1080 px
justos en un cuadro de 1080** — una palabra colgando por cada lado, y eso ya
pasaba con los subtítulos blancos. Bajar la fuente no era la palanca (41 px para
que cupieran esos 40 caracteres). Las líneas cortan ahora también por
presupuesto de caracteres (26, medido a 34 px/carácter). La línea más ancha del
guion real: de 1080 px a **757, con 160 px de margen a cada lado**.

### Verificado en el vídeo, no en el código

62 tests verdes, dos mutaciones comprobadas (reponer los huecos → rojo; blanco
en vez de amarillo → rojo). Reconstruida la pieza 3: **30,97 s** frente a 29,40;
fotograma en 29,75 s con «situation.» en pantalla; en 8,6 s crece «Reality,» y
en 8,9 s crece «the». **El montaje se corrió una vez fuera de la ventana
horaria** del ROG (00:0x MDT, load 0.03, solo CPU, ninguna de las horas cargadas
del otro proyecto) — el servicio sigue respetándola.

---

## 🔴 PENDIENTES ANTES DE ENCENDER LA PRODUCCIÓN DE VÍDEOS (30-ago-2026)

Nada de esto se enciende hasta que las cuatro estén hechas. Orden por lo que
desbloquea, no por esfuerzo.

| # | Qué | De quién | Estado |
|---|---|---|---|
| 1 | Línea de brokerage en Ajustes | dueño | ✅ **hecho** — `Engel & Völkers Aspen`, verificado en la base de producción |
| 2 | La voz del canal | dueño | ✅ **hecho** — `English_CalmWoman` a 1,06 con emoción, elegida entre cuatro variantes |
| 3 | Música de fondo | dueño | ✅ **hecho** — 4 pistas de Pixabay, licencia verificada, instaladas y recomprimidas |
| 4 | **Completar los perfiles de los tres canales** | dueño | ✅ **hecho** (2-sep). Verificado por mí: descripción de YouTube con el dominio, y la cuenta de IG con el nombre visible puesto. Las **bios** de IG y TikTok van por palabra del dueño: IG no las expone y TikTok da la misma respuesta a un handle real y a uno inventado |
| 5 | Instalar el obrero en el ROG | yo | 🔴 **bloqueado**: la máquina está encendida pero no da shell (ver abajo) |

### 4 · Los perfiles de los canales — por qué bloquea

Decisión del dueño (30-ago): **no se enciende la producción hasta que los tres
perfiles estén completos.** Y es la decisión correcta: los vídeos existen para
llevar tráfico a `denverhomestory.com`, y hoy **el canal de YouTube no tiene ni
descripción, ni país, ni enlace**. Publicar en un perfil vacío es gastar
producción en un embudo que no recoge — la misma regla de orden del 27-ago que
dice que no se manda tráfico a una puerta que no atiende nadie.

**No lo puedo hacer yo, y la razón es distinta en cada plataforma:**

- **TikTok e Instagram no tienen API para editar la biografía.** No falta una
  credencial: el endpoint no existe. Publicar, leer métricas y responder
  comentarios sí; el perfil se edita a mano por diseño de las dos plataformas.
- **YouTube sí tiene** `channels.update` para descripción y país, pero exige un
  OAuth propio con proyecto de Google Cloud en modo *Production* — justo el
  trámite que este proyecto evitó usando Buffer. Montarlo para cambiar dos
  campos una vez cuesta más que pegarlos.
- **La vía del navegador se intentó y falló**: la extensión de Chrome no crea
  el grupo de pestañas (tres intentos). Si el dueño la reinicia, se retoma.

Textos listos para copiar, con enlaces directos y el porqué de cada línea:
`~/Downloads/dhs-perfiles.md`. Los tres pasan el filtro Fair Housing
(comprobado) e identifican la brokerage, porque una descripción de canal es
publicidad permanente y Colorado la regula igual que a un anuncio.

Lo que más rinde no es la descripción: son el **país** (YouTube lo usa para
decidir a quién recomendar el canal; vacío, compite contra el planeta) y el
**enlace** sobre el banner.

---

## ✅ EL OBRERO ESTÁ INSTALADO Y FUNCIONA (30-ago-2026, 21:39 MDT)

Primer vídeo hecho por la máquina, de punta a punta y contra producción:

```
21:39:18  el obrero reclama el trabajo 1
21:39:35  faster-whisper transcribe 11,98 s de audio
21:39:45  marca comprobada EN EL FOTOGRAMA: correlación 0,927
21:39:46  entregado
```

Y del otro lado: la pieza pasó de `draft` a **`needs_approval`** con un fichero
nuevo de **1080×1920, 12 s, con audio**. La persona sigue en medio; el obrero
no aprueba nada.

### Lo que hubo que arreglar para instalarlo

**Los pines de `requirements.txt` estaban calibrados para una máquina que no
existe.** El ROG corre **Python 3.14 con ffmpeg 8**, y las versiones fijadas de
PyAV y Pillow no tienen rueda para ninguno de los dos: pip intentó COMPILARLAS
y murió contra una API de ffmpeg tres versiones mayores más nueva de la que esas
releases conocían. Sin fijar, las cinco entran con rueda precompilada (av 18.1,
Pillow 12.3, faster-whisper 1.2.1). El fichero ahora declara **mínimos, no
pines**: fijar es el instinto correcto para las dependencias de un producto, y
aquí fijaba el obrero a un intérprete imaginario.

De paso quedaron instaladas las cabeceras de ffmpeg (`libav*-dev`) — aditivas y
reversibles, aunque al final no hicieron falta.

### Configuración viva

| Qué | Valor |
|---|---|
| Servicio | `eko-render-worker` · unidad de **usuario**, `enabled`, con `linger` |
| Ventana horaria | 13, 15, 16, 17, 21, 23, 1, 2 MDT — comprobada en cada tick |
| Voz | `English_CalmWoman` · 1,06 · emoción |
| Whisper | `small.en` en **CPU** |
| Kling / Pexels | **sin clave a propósito** — el carril generado cae a tarjetas de marca |
| Panel | `RENDER_WORKER_ENABLED=true`, `CONTENT_RENDER_ENABLED=true` |

### Lo que sigue apagado

`CONTENT_STUDIO_ENABLED=false` (no se generan guiones) y `BUFFER_SIMULATED=true`
con `CONTENT_PUBLISH_ENABLED=false` (no se publica nada). **Encender eso sigue
bloqueado por los perfiles de los canales**, que es decisión del dueño.

---

## ✅ EL ROG: DIAGNOSTICADO, ARREGLADO LO NUESTRO (30-ago-2026)

Volvió tras el reinicio del dueño, y el diario **sí** persistía (478 MB), así
que la causa quedó registrada.

### Fue memoria, y el disco queda descartado con número

```
Aug 30 14:24:56 … systemd-journald: Under memory pressure, flushing caches.
   … repetido sin parar hasta las 14:52:51, y a las 14:54:10 dejó de escribir
```

Disco: **49 % usado, 455 GB libres.** La hipótesis del disco —razonable por el
historial de esta máquina— está muerta con la medida delante.

Por qué el `grep "oom-kill"` del dueño no devolvió nada: **el OOM killer nunca
llegó a actuar.** La máquina se ahogó en presión de memoria antes de que el
kernel matara a nadie; `sshd` aceptaba el TCP y no conseguía avanzar, que es
justo lo que veíamos desde fuera.

### Lo que encontramos de paso: casi 3.800 reinicios fallidos por arranque

| Servicio | Reinicios en el arranque que murió | De quién | Por qué falla |
|---|---|---|---|
| `ekoo-chromium` | **1281** | otro proyecto | falta el binario de Playwright |
| `resend-proxy` | **1267** | otro proyecto | busca `/tmp/resend_proxy.py`, y `/tmp` se vacía en cada reinicio |
| `ollama-bridge` | **1266** | 🔴 **NUESTRO** | se ata a `172.20.0.1`, la puerta de una red de Docker que **ya no existe** |
| `ollama-bridge-tailnet` | 161 | 🔴 **NUESTRO** | arranca antes de que la tailnet tenga dirección |

No está probado que estos bucles causaran el ahogo —Ollama solo ocupa 5,6 GB de
los 15— y decirlo sería inventar una causalidad. Lo que sí es cierto: son
desperdicio puro, llevaban así desde siempre, y dos eran nuestros.

### Arreglado (lo nuestro, y solo lo nuestro)

- **`ollama-bridge` deshabilitado.** Se creó cuando el backend corría en el ROG;
  desde la mudanza al VPS en agosto no queda ni un contenedor nuestro en esa
  máquina, y `172.20.0.1` no existe. Verificado antes de tocarlo: la dirección
  no está en ninguna interfaz y no hay contenedores `eko-realestate-*` allí — un
  servicio que **no consigue arrancar no puede tener consumidores**, así que
  apagarlo no puede romper a nadie. Reversible con `systemctl enable`.
- **`ollama-bridge-tailnet` espera ahora a tener dirección.** `After=tailscaled`
  no bastaba: que el demonio arranque no significa que la IP exista. Espera
  acotada a 60 s y falla ruidosamente si no aparece, en vez de girar en
  silencio.

Verificado después de cada cambio: `/api/v1/health` por el dominio sigue en
`llm_fallback: "ok"` y el puente sigue escuchando en `100.88.47.99:11434`.

### 🔴 Lo que NO toqué, y el dueño debería mirar

`ekoo-chromium` y `resend-proxy` son de otro proyecto y siguen reiniciándose
cada ~20 segundos, para siempre. Los dos fallan por cosas triviales, y el
segundo **no puede funcionar nunca** tal como está: su script vive en `/tmp`, y
`/tmp` se borra en cada arranque.

---

## 🟡 v0.67.1 — LA VOZ ELEGIDA, Y EL FILTRO QUE NO OÍA (30-ago-2026)

**La voz del canal: `English_CalmWoman` a 1,06 con emoción**, elegida por el
dueño entre cuatro variantes del mismo guion. Cálida sin sonar a anuncio — que
importa, porque la landing promete «quince minutos, sin discurso de venta» y una
locución comercial contradiría el producto en tres segundos. La velocidad no es
adorno: la emoción sola estiraba el guion de 15,5 s a 17,9 s, y en vídeo corto
esos tres segundos son gente que se va.

Generar las muestras destapó de paso que **mi cliente exigía un `GroupId` que
esta cuenta no usa** — medido contra su API, autentica solo con la clave. El
locutor se habría negado en silencio y los vídeos habrían salido con la voz
gratuita de respaldo.

### Auditoría del carril B — dos bloqueantes, los dos reproducidos

1. 🔴 **El filtro Fair Housing no leía la narración ni los rótulos.** Los dos
   campos que estrenó la v0.67 eran justo los dos que ninguna puerta miraba.
   Medido: un guion con «great schools», «safe neighborhood» y «perfect for
   families» en la narración devolvía **cero hallazgos** y se auto-avanzaba a la
   cola de aprobación. Es la **tercera** vez que este repo envía un filtro que
   no cubre el carril vivo. El arreglo no es añadir dos comprobaciones: es que
   ahora hay **una sola** función (`content_studio.text_violations`) que el
   escritor, la consola y la puerta de publicación comparten.
2. 🔴 **Editar una pieza borraba el hallazgo contra una imagen.** Nadie puede
   editar las escenas desde la consola, así que la única salida para una pieza
   retenida por un prompt rechazado era tocar un texto o pulsar Enviar — y eso
   recalculaba los hallazgos desde tres campos y los limpiaba. El obrero acababa
   **pagando por dibujar el prompt que la puerta había rechazado**.

Y cinco más: «$1.2 million» se leía «one point two **dollars** million»; un
vídeo del carril B sin voz se aceptaba; la denylist tenía huecos de
singular/plural entre sus propias palabras; el carril B se encolaba sin línea de
brokerage y quedaba en bucle de 24 h gastando dinero cada vuelta; y las escenas
sobrantes se pagaban y nunca aparecían.

**Dos tests que no podían fallar**, señalados por el auditor y sustituidos: el
del cargo a Kling llamaba al contador a mano, y el de precios solo probaba
«$1.2M» — la forma que funcionaba.

**Cierre**: 1310 backend · 153 frontend · 50 del obrero verdes; ruff y tsc
limpios; las dos mutaciones de los bloqueantes verificadas en rojo.

---

## 🟡 v0.67.0 — EL CARRIL B: GUION → VÍDEO NARRADO (30-ago-2026) · construido, NO encendido

Fase 3. Un borrador generado ya no es solo texto: trae una **lista de planos**
y una **narración**, y el vídeo se construye **antes** de que llegue a una
persona. Esa es la decisión de producto que sostiene todo lo demás — lo que se
aprueba es el vídeo, no una descripción de él.

**Fair Housing se aplica también a la imagen.** Cada `visual_prompt` pasa el
filtro de frases Y una denylist de descriptores de personas. Un fotograma lleno
de un solo tipo de hogar dice quién es bienvenido sin una sola frase que nadie
pueda editar en revisión. Medido: bloquea «a young family on the porch», «una
pareja joven», «a smiling couple»; deja pasar «the manor house» (sin tropezar
con «man»), «keys on a kitchen counter», «the Front Range at sunrise».

**Guarda de idioma sobre el texto NARRADO**, no sobre el titular — el fallo que
costó días de publicación en el idioma equivocado en el proyecto vecino — y
caza la MEZCLA, que es lo que un modelo produce de verdad.

**Voz**: MiniMax T2A con edge-tts de respaldo, sobre un guion normalizado
(«$450,000» → «four hundred and fifty thousand dollars»). **Imágenes**: Kling →
Pexels → tarjeta de marca; caché **en el punto de pago** y tope diario propio,
porque ese paquete de Kling es un saldo compartido con otros dos proyectos.
Planos **cortados a la voz** con los tiempos de Whisper.

**Auditoría de la fase anterior — dos bloqueantes reales, reproducidos:**

1. 🔴 **La música cortaba la narración por la mitad.** Un segundo
   `-filter_complex` (ffmpeg se queda con el último) más `[0:a]` consumido dos
   veces. Medido antes: vídeo 6 s / audio **2,5 – 3,5 s, distinto en cada
   ejecución**, con código de salida 0. Medido después: 6,01 s, idéntico en tres
   ejecuciones. El test que existía comprobaba una subcadena y no podía verlo.
2. 🔴 **Un obrero rezagado podía pisar un vídeo ya publicado** y borrar el
   fichero aprobado. Ahora `/result` y `/fail` exigen trabajo reclamado y pieza
   aún en revisión, y se comprueba **antes** de gastar la subida.

Y cinco importantes más, todos corregidos: modelo de voz por idioma (era inglés
puro en un producto bilingüe), errores de ffmpeg que llegaban **vacíos** a la
persona (se leía `stdout` con los errores en `stderr`), un trabajo fallido que
condenaba el clip para siempre, ficheros huérfanos en el volumen, y **los tests
del obrero que no corrían en CI**.

**Un defecto propio que encontró un test, no la inspección:** `violations=None`
se guardaba como JSON `null` y no como SQL NULL, así que `IS NULL` no casaba
nunca y el barrido del carril B no encontraba trabajo jamás. `message.py` ya
llevaba `none_as_null=True` desde una lección anterior; el modelo de contenido
no la había heredado. La migración 048 normaliza lo existente.

**Cierre**: 1306 backend · 153 frontend · 40 del obrero verdes; ruff y tsc
limpios. **Cinco mutaciones verificadas en rojo** — y la quinta solo después de
escribir el test que faltaba: quitar el arreglo del audio dejaba todo verde
porque ningún test renderizaba con música de verdad.

### ✅ Desplegado INERTE y verificado contra el mundo (30-ago)

| Qué | Medida |
|---|---|
| `/api/v1/health` por el dominio público | **`0.67.0`**, `llm_fallback: "ok"` |
| Migraciones 046, 047, 048 | aplicadas; `render_jobs` existe con **0 filas**, `content_pieces.scenes` presente |
| La cola del obrero | **503** desde fuera — cerrada, porque `RENDER_WORKER_TOKEN` está vacío. No 401: no está configurada |
| La ruta pública de media | **404** para una pieza inexistente |
| Publicación | `BUFFER_SIMULATED=true`, `CONTENT_PUBLISH_ENABLED=false`; los 3 ids de canal leídos desde el contenedor coinciden con la organización real |
| `CONTENT_PUBLISH_ORG_ID=1` | puesto: sin él el publicador se negaría, y con razón — hay dos organizaciones |
| Panel y landing | `/login` 200 · `www.denverhomestory.com` 200 |
| Vecinos | `zorros` 302 · `app.ekoaiautomation.com` 200 · `ekoaiautomation.com` 200; sus contenedores llevan 4-7 semanas arriba, sin tocar |

Respaldo del `.env`: `.env.bak.20260830-video`.

🔴 **Nada está encendido.** `CONTENT_STUDIO_ENABLED=false`,
`CONTENT_RENDER_ENABLED=false`, `RENDER_WORKER_ENABLED=false`,
`BUFFER_SIMULATED=true`, y la unidad del ROG sin instalar. Todo eso es la
Fase 4 y **exige el «adelante» del dueño**, con él delante para mirar las apps.

---

## 🟡 v0.66.0 — EL OBRERO DE RENDER Y LOS SUBTÍTULOS (30-ago-2026) · construido, NO instalado

Fase 2. El carril A deja de renderizar dentro de la API y **encola** para la
máquina que tiene el equipo de vídeo, que además pone los **subtítulos** — la
mitad de un short que casi todo el mundo ve en silencio.

**Forma**: el obrero **tira, nadie le empuja** (ningún puerto se abre en el
ROG); Whisper en **CPU** a propósito (la GPU de esa máquina es de otro
proyecto, y la sesión vecina midió que la VRAM libre oscila entre 3,4 y 6,0 GB
en horas: cualquier número caduca); **unidad systemd de usuario, nunca cron**
(el crontab del ROG lo reescribe entero un self-heal cada 15 min); ventana
horaria **comprobada en cada tick**, no declarada a un timer, porque
`OnCalendar` con `Persistent=true` dispara tarde tras un corte de luz. Horas
acordadas con la sesión BitTrader: 13, 15, 16, 17, 21, 23, 1, 2 MDT.

**Lo que se verifica de un resultado**: el panel **no se fía del obrero** —
re-sondea el fichero (1080×1920, audio, duración) porque un obrero mal
configurado o a medio actualizar produce vídeo legible del tamaño equivocado. Y
el obrero **mira un fotograma**: correlaciona la esquina donde compositó la
marca contra la marca que debía llevar. Es la lección del vídeo que salió con
la marca de otra empresa pasando todas las puertas.

**Auditoría de la fase anterior — tres hallazgos reales, los tres corregidos:**

1. 🔴 **Una pausa por cuota dejaba plataformas sin publicar para siempre.** El
   conjunto de «ya hechas» incluía las filas `PENDING`, así que la plataforma
   que un 429 liberaba se saltaba en cada tick siguiente. Pieza clavada en
   `PUBLISHING`, vídeo medio publicado, sin nadie que lo rescatara.
2. **Una pieza fallada y re-aprobada no podía publicarse nunca.**
3. 🔴 **Cualquier organización publicaba en los canales de la primera.**
   Producción tiene **dos** organizaciones (la real y una «Demo» en trial, que
   el barrido incluye). `CONTENT_PUBLISH_ORG_ID` dice de quién son los canales;
   sin él, con más de una organización, no se publica nada. ⚠️ **Al desplegar
   hay que poner `CONTENT_PUBLISH_ORG_ID=1` en el `.env` del VPS** o la
   publicación se negará — correctamente.

Y el test de la pausa por cuota **no podía fallar**: comprobaba el estado
intermedio y nunca el tick siguiente. Sustituido.

**Cierre**: 1276+14 backend · 153 frontend · 20 del obrero (con un render real
de ffmpeg) verdes; ruff y tsc limpios; la imagen compila. **Cuatro mutaciones
verificadas en rojo**, y una quinta que **NO se puso roja a la primera**: quitar
la verificación del resultado dejaba la suite verde porque el test mandaba
basura, que ya rechaza `ffprobe`. El test que faltaba manda un vídeo válido de
1920×1080 y ahora la mutación muerde.

🔴 **Pendiente y NO hecho**: instalar la unidad en el ROG. Es Fase 4 y **exige
el «adelante» del dueño**. El ROG estuvo caído esta tarde y volvió; su
`ollama-bridge` (el del puente de Docker, nuestro) está en bucle de reinicio
desde el arranque porque intenta atarse a `172.20.0.1`, que no existe hasta que
Docker crea la red. **No afecta a producción**: medido en el dominio,
`llm_fallback: "ok"` — el VPS alcanza Ollama por la tailnet y ese puente sí
está activo. El de Docker quedó obsoleto con la mudanza al VPS; **no lo he
tocado**, decisión del dueño si se apaga.

---

## 🟡 v0.65.0 — LA PUBLICACIÓN EXISTE (30-ago-2026) · construida, NO encendida

Fase 1 de la máquina de vídeo de Denver Home Story. Rama
`feat/maquina-de-video-dhs` desde `feat/landing-denver-home-story`.

**Qué se construyó**: `services/buffer_publisher.py` publica una pieza
APROBADA en YouTube, TikTok e Instagram por Buffer (GraphQL `createPost`,
`shareNow`, **nunca `thumbnailUrl`**, `isAiGenerated` solo a TikTok y derivado
de `ContentKind`). **Reclamar-luego-registrar por publicación**: la fila se
confirma ANTES de la llamada, así que una caída no puede volverse un segundo
post; una fila atascada en `PUBLISHING` no se reintenta sola. **Guarda de
organización**: pregunta a Buffer los canales de `BUFFER_ORG_ID` y se niega si
los ids configurados no son suyos. Ruta pública
`GET /api/v1/public/content/{id}/media` con dirección **estable** (Buffer
descarga al publicar y rechaza URLs firmadas) cuya puerta es el **estado** de
la pieza; borrador, rechazada e inexistente dan el **mismo** 404.

**Medido, no supuesto** (Buffer, con nuestra clave, 30-ago): los 3 canales
conectados (ni `isDisconnected`, ni `isLocked`, ni cola pausada), IG con
`instagram_business_content_publish`, YT con `youtube.upload`, TT con
`video.publish`; cuota **250/día y 3000/30 días, 10 usadas** → la cuota es por
clave/organización y **no compartimos** el cupo de BitTrader (su bloqueo vence
el 21-sep). Canal de YouTube `UC9wpgdqHHpGRTqF5pSR7wgA`: **0 vídeos, 1
suscriptor, descripción vacía** — falta perfil.

**Dos defectos reales que encontraron los tests nuevos, no la inspección:**

1. 🔴 **`BodySizeLimit` cancelaba toda respuesta en streaming de la app.** Su
   `replay()` devolvía `http.disconnect` a la segunda lectura, y Starlette
   escucha ahí la desconexión de cada `StreamingResponse`: cabeceras correctas
   y **cero bytes**. Ahora delega en el servidor, que es quien sabe si el
   cliente se fue. Afectaba a cualquier streaming futuro, no solo a esta ruta.
2. **Una pausa por cuota dejaba la pieza clavada para siempre**:
   `ensure_publishable` exigía `APPROVED` y el reanudado llega en `PUBLISHING`.
   Ahora acepta `resuming=True` — la pieza llegó a ese estado pasando por esta
   misma puerta, y la brokerage y Fair Housing se revalidan igual.

**Cierre**: 1254 backend + 153 frontend verdes desde base recreada, ruff y tsc
limpios, imagen del backend compila. **Tres mutaciones verificadas en rojo**:
saltarse `ensure_publishable` (3 rojos), quitar el filtro de estado de la ruta
pública (5 rojos), quitar la guarda de organización (2 rojos). El barrido de
opt-out exigió declarar el módulo nuevo: **exento con motivo escrito** — un
vídeo en un canal público es difusión, no un mensaje, y no hay destinatario
cuyo consentimiento comprobar. Se cumplió por fin la promesa que
`test_content_gate_is_absolute.py` llevaba escrita desde v0.52 (`_reaching`):
por AST, `publish_piece` consulta la puerta **antes** del cable, y nadie fuera
del módulo puede llamar a sus funciones de red.

🔴 **NO está encendido y no debe encenderse todavía**: `BUFFER_SIMULATED=true`,
`CONTENT_PUBLISH_ENABLED=false`, sin canales configurados en el `.env`. El
encendido real es la Fase 4 del plan y **exige el «adelante» del dueño**, con
él delante para mirar las apps.

---

## ✅ v0.64.1 — LA LANDING SE MUEVE (28-ago-2026, tarde)

El dueño cotejó la página viva contra el lienzo v4: faltaba toda la
coreografía de scroll. Portado el **motor de `deploy-v4`** de Claude Design
(carpeta descargada por el dueño) a `LandingEffects.tsx` — literal función a
función, cotejado numéricamente por el auditor. **Decisión del dueño: portar
el motor, NO el reemplazo literal** que proponía Claude Design (su index.html
apuntaba el CTA al teléfono: habría desmontado el formulario real).

Medido EN EL DOMINIO VIVO: placa 0.86→1.0401 con el scroll, vídeo del héroe
(4,8 MB, keyframes densos) frotándose y corriendo libre, carril de mercados en
`grab`, wiggle horizontal 0. Auditoría: 0 bloqueantes; 3 importantes corregidos
en fase (guard de overflow-x que el original traía, pop de hidratación de la
placa —ahora nace autorada a 0.86—, vídeo aparcado bajo reduced-motion) + rail
con `pointercancel`. NO portado a propósito: el escalado de mesas de trabajo
fijas, su navegación de anclas y el Lucide por CDN. Health `0.64.1`.

⚠️ La marca de agua MLS aparece también en las tarjetas de Aspen y Valley del
carril, no solo en el fondo del panel — la decisión del dueño sobre las fotos
cubre las cuatro.

---

## ✅ v0.64.0 — LA LANDING VIVE EN `www.denverhomestory.com` (28-ago-2026)

Rama `feat/landing-denver-home-story` (`78d32a5`→`f3b0f0c`), 4 fases + auditoría
(0 bloqueantes; I-1/I-2 corregidos en fase), desplegada y **verificada contra el
mundo**:

| Qué | Medida |
|---|---|
| `www.denverhomestory.com` | **200**, landing v4, cert válido (Universal SSL — arregló de paso el cert roto del aparcamiento), canónica correcta, `index,follow` |
| Ápex | **301 → www** (Redirect Rule) |
| Enrutado por host | brand`/leads` → 308 panel · panel`/` → 307 `/leads` · `/login` 200 · `/contact` 200 |
| health público | `0.64.0`, `llm_fallback: ok`; `BOOKING_OFFERS_PAUSED=true` dentro del contenedor |
| **Aviso a Natalia E2E REAL** | captura en producción → fila interna `sent` con id de Resend → **correo llegó al Gmail** (verificado en el buzón); duplicados no reenvían; lead de prueba borrado y buzón restaurado |
| Clara (VAPI) | guion interino vivo: toma datos, **no ofrece horas**, «Natalia will call you in the next few hours»; herramientas de reserva **quitadas** (backup en `~/eko-vapi-backup-20260828.json` para reactivar) |
| Turnstile | 🔴→✅ la site key solo permitía `inmo-demo`; **añadido `denverhomestory.com`** por API. El widget bloquea navegadores automatizados (correcto); falta UNA pasada humana del dueño |
| Vecinos | zorros 302 · blackvolt 200 (intactos tras reiniciar solo nuestro túnel) |

**Infra**: túnel `eko-realtors` con 3 hostnames; DNS: CNAMEs proxiados al túnel
(aparcamiento borrado — reversión: `A @` 13.248.243.5 + 76.223.105.230,
`CNAME www`→apex, todo gris); `.env` respaldado en `.env.bak.20260828-landing`;
`agency_phone=+17208249313` en Ajustes.

**🔴 Para el dueño**: (1) una pasada humana del formulario en el dominio nuevo
(el captcha bloquea mi navegador automatizado, como debe); (2) decisión sobre la
foto de fondo del panel de consulta: lleva marca de agua **«©2026 Property of
Aspen/Glenwood MLS»** — una foto de MLS licenciada para fichas, usada en
marketing; recomendación: sustituirla.

**Backlog**: M-2 de la auditoría (`required` del email cableado en el frontend,
desincronizable de `CAPTURE_REQUIRE_EMAIL`); claves i18n huérfanas (reach/voices).

**Siguiente — reactivación de citas** (decidido por el dueño 28-ago): editor
maestro de disponibilidad (admin edita a cada agente); horas de Natalia
(9:00–21:00 ×7, llamadas) bajo SU usuario y apagar el calendario de prueba del
dueño; activar su calendario compartido como fuente de conflictos en Cal.com;
**prueba real** (hora ocupada suya deja de ofrecerse) → quitar la pausa y
restaurar las herramientas de Clara automáticamente.

## Contexto en una línea

El embudo es: vídeos → redes de @denverhomestory → `www.denverhomestory.com` →
formulario o llamada → el sistema filtra, agenda y hace seguimiento → todo se
controla desde el panel. La **Fase A** es la casa: mover el sistema del portátil
de casa (ROG) al VPS, donde ya viven Zorros y Black Volt.

---

## ✅ v0.63.1 — CALENDARIO REAL ENCENDIDO (28-ago-2026, ~00:55 MDT)

El dueño reportó «My availability no está disponible» — la página decía la
verdad (modo simulado). Antes de girar el interruptor se desactivaron **tres
minas**, cada una con su test y su mutación roja:

1. **Cal.com escribía al cliente en español** — `"language": "es"` cableado en
   el attendee. Test sobre el **cuerpo real** enviado, no sobre el fuente.
2. **Abrir la página podía vaciar la oferta**: aprovisionar crea una agenda
   VACÍA, y una fila activa de nacimiento haría que `pick_agent` la prefiriese
   al event type de la agencia → el asistente ofrecería CERO horas porque
   alguien miró una página. Las filas nacen **apagadas**.
3. **Guardar horas ES el interruptor** — guardar activa, vaciar apaga.

**Verificado contra el mundo real, no «debería»:**
| Prueba | Resultado |
|---|---|
| health público | `0.63.1` · `CALENDAR_SIMULATED=false` DENTRO del contenedor |
| Huecos reales | el código de producción devolvió **20 huecos de Cal.com** (09:00, 09:45, 10:30… America/Denver) |
| Aprovisionado real | el primer intento se comió un **500 de Cal.com** en la 3ª agenda → 502 claro, parcial conservado; el **reintento reanudó**: 200, 4 actividades configuradas, **0 duplicados, todas inactivas** |
| Suite | **1216 backend** desde base recreada · 153 frontend · ruff/tsc limpios |

⚠️ **Consecuencia viva**: las reservas de Clara son ahora REALES en Cal.com
(confirmaciones al cliente **en inglés**). Los conflictos se leen solo del
calendario `denverhomestory@gmail.com` hasta que Natalia comparta el suyo — la
doble reserva de Natalia sigue posible y documentada.

**Lección de instrumentación (a memoria):** el restore por `cp` del arnés de
mutación cayó en el mismo **segundo** que el `.pyc` mutado; CPython validó el
bytecode por mtime y ejecutó `"es"` con el fuente ya en `"en"`. Purga de
`__pycache__` + `PYTHONDONTWRITEBYTECODE=1` en arneses desde ahora.

## ✅ DESPLEGADO — v0.63.0 en producción (28-ago-2026, ~00:15 MDT)

Autorización condicionada del dueño («deploy si se pasan todas las pruebas y
auditorías») — **cumplida y ejecutada**. Bundle → VPS, build, **migración 045
con la imagen nueva y antes del up**, `up -d`.

| Verificación | Resultado |
|---|---|
| `/api/v1/health` por el dominio público | `0.63.0` · `llm_fallback:"ok"` · `captcha:"on"` |
| Migración 045 en producción | aplicada sobre un `visits` **no vacío**: filas existentes → `purpose='showing'`, sin asignar (la verdad); `agent_calendars` con 0 filas |
| Webhook de voz sin firma | **403** (sigue armado) |
| `GET /availability/me` sin sesión | **401** |
| Marca en la landing | «Engel & Völkers» ya vivo (el *build arg* esperaba esta reconstrucción); los «Aspen» restantes son texto geográfico, no la identificación legal |
| `zorros-*` / `blackvolt-*` | todos **Up**, intactos |
| Reversión disponible | rama `deploy-v062` en el VPS + `alembic downgrade 044_message_internal` (probada en ambos sentidos) |

**Nota del checkout en el VPS:** chocó con los dos scripts (`set-cloudflare-token.sh`,
`set-calcom-key.sh`) copiados por scp antes de commitearse. **Verificado por
hash que eran idénticos byte a byte** a los del branch antes de descartar la
copia local — un checkout que repone lo mismo no pierde nada, y se comprobó, no
se supuso.

**Pendiente que NO va en este despliegue:**
- 🔴 `CALENDAR_SIMULATED` sigue `true` — se apaga cuando Natalia comparta su
  calendario y la prueba real (una hora ocupada suya deja de ofrecerse) pase.
- 🔴 Nameservers: **luz verde medida a las 23:03 (0/20 en los tres resolutores)**
  y comunicada; a las ~00:10 los NS seguían en GoDaddy — acción del dueño.

## 🟢 CERRADO — «Mi disponibilidad» · rama `feat/disponibilidad-por-agente`

### ✅ Fase 3 — el horario decide las horas que se ofrecen · commit `9d46557` · **v0.63.0**

La fase que hace que las dos anteriores sirvan de algo: hasta aquí la sección
era un formulario que no cambiaba nada de lo que se le dice a un lead.

**Los DOS carriles, no uno.** Voz y texto son caminos distintos que responden a
la misma pregunta. Convertir solo el primero —lo que proponía el borrador del
plan— habría dejado al teléfono ofreciendo las horas reales del agente y al chat
las de la agencia: dos respuestas a «¿cuándo puedo ir?», sin nada que revelase
la contradicción. Convertidos los **cinco** puntos: `check_availability`, la
comprobación previa a reservar, la reserva por voz, el carril de texto
(`_real_slots_note`) y la ruta del panel.

⚠️ **Cómo se integró, porque hacerlo mal reabre una guarda de cuatro
auditorías:** `resolve_calendar_identity()` **no se toca** y la credencial sigue
saliendo de ella — existe para impedir que una organización reserve en la cuenta
del operador. Lo único que se sobreescribe es el `eventTypeId`. Sin fila se cae
al global, que es el comportamiento de siempre.

| Checklist | Resultado real |
|---|---|
| Suite backend, base recreada | **1211 pasan, 0 fallan, 0 saltados** |
| Frontend | `tsc` limpio · `next lint` sin avisos · **153** vitest |
| Lint backend | *All checks passed* |
| Build | imagen `a75c92d7…` |
| Secretos / depuración | 0 y 0 |
| Mutaciones | **4**, todas rojas |
| Bump | v0.63.0 en los cuatro sitios |

**Nota de método:** la primera mutación de la voz **no se aplicó** — mi patrón no
coincidía con el fichero — y el verde no probaba nada. Repetida contra la línea
correcta (`voice.py:473`), sí cae. Una mutación que no se aplica es un verde
falso disfrazado de comprobación.

**Decisiones:**
- **Un vendedor reserva una valoración**, no una visita de comprador.
  `activity_for_lead` es el único sitio donde se decide. Caso borde escrito: un
  lead creado en la propia llamada, aún sin intención clasificada, cae a visita.
- **`pick_agent` no es un TODO.** Con dos agentes elige al de menos citas
  **futuras** —las pasadas no cuentan, o el veterano se queda sin trabajo— y
  desempata por correo para que las horas ofrecidas y la reserva coincidan. Hoy
  hay una sola fila en producción: el camino está **dormido, no ausente**.

### Auditoría de cierre de la Fase 3 — corregida en `24bdb2b`

**La primera auditoría falló por forma, no por fondo**: salida corrupta dos
veces, y sus «146 fallos» eran de su propio entorno (146+1065 = 1211, mi mismo
total con una variable de entorno de menos). Peor: **dejó una mutación sin
restaurar en `visits.py`** —las dos líneas `event_type_id` del panel, quitadas—
y dos bases sin borrar. Restaurado a HEAD tras leer el diff, bases borradas.
**Lección: el árbol se verifica después de que el último agente muere, no
después de su primer informe.** La re-auditoría (instrucciones estrictas de
forma) entregó limpia: **sin bloqueantes, 3 importantes, 1 menor**.

| Hallazgo | Evidencia del auditor | Estado |
|---|---|---|
| **La transacción abortada** | sonda real: con `agent_calendars` ausente, el `except` devolvía el fallback y la **siguiente** sentencia de la misma sesión moría con `InFailedSQLTransactionError` — panel 500, llamada caída, lead sin respuesta. Y rollback no valía: la voz tiene un lead flusheado sin commitear en ese punto | ✅ `pick_agent_safely` en **sesión desechable propia** (la org viaja: es un ContextVar leído al abrir transacción); sustituye las 3 copias. Test que reproduce la sonda → mutación roja |
| **Hueco de mutación en el conteo de carga** | quitar `status.in_((SCHEDULED, CONFIRMED))` dejaba los 8 tests verdes: una tarde **cancelada** seguiría contando contra la agente | ✅ test que lo fija; la mutación exacta del auditor ahora es roja |
| Panel: ofrecer y reservar en dos requests | la carga o la intención pueden cambiar el agente entre medias; en real Cal.com lo rechaza (503 visible), en simulado se graba en silencio | 📋 **backlog** |
| `_busy_starts` resta las visitas de TODA la agencia de los huecos de UN agente | con dos agentes, la cita de B oculta la hora libre de A. Dormido hoy | 📋 **backlog** |

**Tras los arreglos: 1213 verdes** desde base recreada, ruff limpio, imagen
`826e5b6e…`. Verificado también por el auditor: multi-tenant de `pick_agent`
sano con sonda real de dos orgs bajo `eko_app`, `CancelledError` no se traga, la
voz es coherente ofrecer↔reservar dentro de una llamada, y cero regresiones del
cambio de firma.

**Siguiente paso concreto:** desplegar v0.63.0 (autorización condicionada del
dueño: cumplida — pruebas y auditorías en verde) y las dos verificaciones que
solo el mundo real puede dar — que Natalia comparta su calendario, y comprobar
que una hora ocupada suya **deja de ofrecerse**.

### ✅ Fase 2 — «Mi disponibilidad» · commits `adaa9c7` + `6d40afc`

Cada agente entra con su Google y declara cuándo se le puede reservar, por tipo
de cita (visita, valoración, llamada, puertas abiertas).

**El modelo de autorización es una frase:** el correo sale del token de sesión y
de ningún otro sitio. No hay parámetro `email` en la ruta ni campo `email` en
ningún cuerpo, y todos los esquemas son `extra="forbid"`. Un agente no puede
tocar la agenda de otro **no porque una comprobación lo rechace, sino porque no
hay forma de nombrar a la víctima**.

| Checklist | Resultado real |
|---|---|
| Suite backend, base recreada | **1203 pasan, 0 fallan, 0 saltados** |
| Frontend | `tsc` limpio · `next lint` sin avisos · **153** vitest |
| Lint backend | `ruff check app tests` → *All checks passed* |
| Build | imagen `2783f6a8…` |
| Secretos / depuración | 0 y 0 |
| Mutaciones | **8**, todas rojas (5 de la fase + 3 de los arreglos de auditoría) |

⚠️ **Cobertura: no se puede medir aquí, y lo digo en vez de dar un número.**
`pytest-cov` reporta 55 %/71 % en los ficheros nuevos, pero **no atribuye lo que
se ejecuta dentro de la app ASGI** — las líneas del 403 que las mutaciones ponen
en rojo salen como «no cubiertas». La prueba de que ese código corre son las
mutaciones, no el porcentaje.

### Auditoría de cierre de la Fase 2 — corregida en `6d40afc`

**Un bloqueante y cinco importantes.** Tres de los importantes eran roturas
visibles de la función recién construida, así que no fueron al backlog.

| Hallazgo | Qué rompía | Estado |
|---|---|---|
| 🔴 **BLOQUEANTE**: el centinela `""` | se escribía el id vacío **antes** de lanzar el error, y el `commit` deliberado lo hacía permanente. La guarda leía `is None`, que `""` no es → `int("")` → `ValueError` no capturado → **500 para siempre**, recuperable solo con un `UPDATE` a mano. La variante del event type era peor: **200 silencioso** y la agente dejaba de ser reservable | ✅ arreglado en dos mitades independientes |
| Un **timeout** no era `CalComScheduleError` | escapaba de todos los `except` y huerfanizaba en Cal.com el objeto recién creado; el reintento creaba otro | ✅ |
| La página **no tenía enlace a ≥1536 px** | su única entrada de escritorio era el menú `2xl:hidden`: en el monitor de la oficina no existía | ✅ |
| Cambiar de pestaña **descartaba las ediciones** | el comentario decía que no lo haría y el código lo hacía | ✅ borrador por actividad + aviso de sin guardar |
| La **contraseña de oficina** llegaba a la vista de equipo | emite token admin sin correo, y el endpoint publica el padrón del personal | ✅ ahora exige identidad |
| `_slug` **no era inyectivo** | dos compañeras con el mismo nombre de usuario colisionaban → 502 permanente para la segunda | ✅ digest del correo completo |

**Nota de método, y me corrige a mí:** mi primera mutación del bloqueante
**no puso el test en rojo**. Mutar una sola mitad del arreglo no basta, porque
cada mitad protege por sí sola. La mutación válida es el código original entero
— y entonces sí reproduce el `ValueError: invalid literal for int() with base
10: ''` exacto del auditor.

**Aviso del propio auditor, que reporto porque él lo reportó:** una de sus
sondas hizo **una petición real a `api.cal.com`** sin sustituir `_call`. Devolvió
401, no se enviaron datos y no hubo escrituras.

**Siguiente paso concreto:** Fase 3 — que la disponibilidad decida las horas que
se ofrecen. `list_available_slots` y `create_booking` ganan `activity` y
`agent_email`; **los DOS** sitios que listan huecos (`voice.py` y
`conversation.py:812`); `LeadIntent.VALUATION` → cita de valoración.

### ✅ Fase 1 — esquema y dueño del trabajo · commit `b0c3d71`

| Checklist de «terminado» | Resultado real |
|---|---|
| Suite backend, base recreada | **1188 pasan, 0 fallan, 0 saltados** (antes: 1180) |
| Frontend | `tsc` sin errores · **153 vitest** verdes |
| Lint | `ruff check app tests` → *All checks passed* |
| Build | `docker build -f backend/Dockerfile` → imagen `9a053f8d…` |
| Cobertura del código nuevo | `app/models/agent_calendar.py` **100 %**; la única línea sin cubrir de `visit.py` (116) es un `__repr__` preexistente que mi diff no toca |
| Secretos / depuración en el diff | 0 y 0 (barrido por patrón sobre `git diff`) |
| Migración | probada en **los dos sentidos**: 045 → 044 → 045 |
| **Mutación** | política RLS permisiva `USING(true)` → **3 tests rojos**: lectura cruzada, default-deny y escritura cruzada |

**Nota de método que casi me engaña:** *borrar* la política no sirve como
mutación. Con `FORCE` la ausencia de política niega todo, así que el test falla
porque desaparece **mi propia** fila, no porque se filtre la ajena — una señal
correcta por el motivo equivocado. La mutación real es una política que **no
filtra**, que es además el bug que de verdad ocurre.

**Decisiones tomadas:**
- `agent_calendars` **no guarda horarios**, solo el vínculo persona ↔ tipo de
  cita ↔ objetos de Cal.com. Guardarlos aquí crearía la **cuarta** fuente de
  verdad sobre disponibilidad (ya hay tres: `business_hours`, que solo alimenta
  el prompt del LLM; `SIMULATED_HOURS_OF_DAY`; y la agenda de Cal.com).
- Indexada por **email de login**, no por id de cuenta, y **sin FK** a
  `allowed_users`: revocar el acceso de alguien no debe borrar la agenda contra
  la que se reservaron sus visitas.
- `visits.assigned_email` va a la **lista de recorte**, no a `EXEMPT`: en esta
  tabla la fila se escribe **después** de que Cal.com ya tiene la reserva, así
  que un fallo ruidoso dejaría una cita viva sin fila local. El truncado es
  inalcanzable — origen y destino acotados a los mismos 254.

### Auditoría de cierre de la Fase 1 — commit `6e7529f`

**Sin bloqueantes.** Esquema, RLS y migración correctos, verificados por el
auditor con su propia base. Pero encontró **dos tests que no podían fallar**, y
eso no fue al backlog: un test que certifica nada es peor que no tenerlo.

| Hallazgo | Evidencia del auditor | Estado |
|---|---|---|
| El `server_default` de `visits.purpose` **no lo cubría nada** | mutación `ALTER COLUMN purpose DROP DEFAULT` → **1188 verdes**. El `default=` de Python mete el valor en el INSERT, así que el default del servidor no se ejercía jamás. Y es lo único que hace que `ADD COLUMN NOT NULL` sobreviva a un `visits` **no vacío** — con 1 fila: `contains null values` | ✅ **corregido**: test que inserta por SQL crudo sin nombrar la columna. Mutación reverificada → **rojo** |
| La pata `org_id` del UNIQUE **no la cubría nada** | mutación a `UNIQUE (email, activity)` → **1188 verdes**, con colisión que cruza el límite de tenant: la org 2 choca contra una fila que no puede ni ver | ✅ **corregido**: test que siembra el mismo correo en dos orgs. Mutación → **2 rojos** |
| Deriva modelo ↔ migración (índice de `email`) | `alembic check`: índice declarado en el modelo, nunca creado | ✅ corregido, y de paso fuera el índice `(org_id, email)` redundante con el UNIQUE |

**Al backlog, con evidencia:** el comentario dice que una fila «no puede
pertenecer a quien no puede entrar» y **nada lo impone** — sin FK, sin CHECK. Hoy
es inalcanzable (0 consumidores de `AgentCalendar` fuera de los modelos), pero
**el servicio de la Fase 2 se escribirá confiando en esa frase**: la validación
contra `allowed_users` va ahí, no aquí.

**Tras los arreglos: 1190 verdes** (10 en el fichero nuevo), ruff limpio, ida y
vuelta de la migración otra vez limpia.

**Siguiente paso concreto:** Fase 2 — `services/agent_calendar.py` (el único
módulo que habla con `/v2/schedules` y `/v2/event-types`), el router
`api/v1/availability.py` con el correo tomado del **token** y nunca del cuerpo
—**y comprobado contra `allowed_users`**—, y la página «Mi disponibilidad».

---

## 📌 PENDIENTES — esta noche y mañana (28-ago-2026)

**✅ HECHO — nameservers movidos a Cloudflare (28-ago-2026, mañana).** El dueño
hizo el cambio en GoDaddy y todo se verificó medido, no supuesto:

| Qué | Medida |
|---|---|
| DS ausente antes del cambio | re-verificado 0/3 resolutores el 28 por la mañana |
| Delegación en el padre (`a.gtld-servers.net`) | `arely` + `damian.ns.cloudflare.com` |
| Resolutores | 8.8.8.8 y 1.1.1.1 ya con NS nuevos; 9.9.9.9 caché vieja (expira sola). **NOERROR en los tres, cero SERVFAIL** |
| Zona en Cloudflare | `pending` → `activation_check` → **`active` en 60 s** |
| SPF/DMARC | `v=spf1 -all` y `p=reject` **vivos** (pre-cargados en la zona) — Quad9 aún sirve el `_dmarc` viejo de GoDaddy unas horas |
| Web | ápex HTTP 200 (aparcamiento, como se esperaba) |

Hallazgo no-bloqueante: `https://www` da error de certificado — el cert del
aparcamiento (`CN=denverhomestory.com`) no cubre `www`. **Preexistente por
construcción** (mismas IPs, registros en gris → ruta de servido idéntica a la
de antes del cambio); la Fase B lo sustituye por el túnel de todas formas.
Queda también el `CNAME _domainconnect` → GoDaddy, reliquia inerte.

### MAÑANA

1. 🔴 **Esperar la respuesta de Natalia.** El dueño le envió el correo la noche
   del 27-ago pidiéndole que comparta su calendario de Google con
   `denverhomestory@gmail.com` en modo **«ver solo libre/ocupado»**. Es de
   Gmail, no de Workspace, así que **no hay administrador que pueda bloquearlo**.
   Cuando conteste:
   - Activar ese calendario en Cal.com como fuente de conflictos.
   - **Verificarlo de verdad**: pedir los huecos de un día en el que ella tenga
     algo puesto y comprobar que **esa hora ya no se ofrece**. Que el calendario
     aparezca en la lista **no prueba nada**.
   - Solo entonces `CALENDAR_SIMULATED=false` + reinicio del backend.
2. **Antes de ese interruptor, una versión con tres cosas** (código; pedir
   autorización de despliegue aparte):
   - Quitar el `"language": "es"` cableado en el `attendee` de
     `create_booking` — Cal.com le escribiría en español a clientes que van en
     inglés por norma del dueño.
   - **Exigir email en el formulario público** mientras el SMS esté aparcado: un
     lead que solo deja teléfono no es alcanzable, y además haría que Cal.com
     reservase con **Natalia como asistente** (cae a `booking_contact_email`).
   - Poner `agency_phone = +17208249313` en Ajustes: el número existe, contesta
     y **nadie lo tiene**.
3. **Después: la landing en `denverhomestory.com`** (túnel + `CNAME` + el diseño
   a `Landing.tsx`, conservando el formulario con su honeypot, captcha y
   consentimiento TCPA). La reconstrucción del frontend activa de paso
   `NEXT_PUBLIC_LANDING_BROKERAGE=Engel & Völkers`, que hoy está escrita pero
   **no viva** por ser *build arg*.
4. Luego `hello@denverhomestory.com` (Resend + Email Routing), **en ese orden**:
   SPF y DKIM primero, relajar el `p=reject` después.

---

## 🔴 EN CURSO — Dominio y teléfono (27-ago-2026) · rama `feat/dominio-y-telefono`

**No toca código.** No hay tests, lint, build ni cobertura que enseñar: el
«terminado» de esta fase son medidas contra el mundo real. Dicho explícitamente
para no declarar verde nada por inspección.

**Estado: BLOQUEADA en dos clics del dueño.** Lo verificable ya está verificado.

### Lo que ya medí (evidencia, no memoria)

| Comprobación | Resultado |
|---|---|
| Nameservers de `denverhomestory.com` | `ns67/ns68.domaincontrol.com` — sin mover |
| **DS en el padre** | **2 registros vivos**, TTL **21.600 s (6 h)** |
| Zona en Cloudflare | **ya existe y ya responde** desde `arely.ns.cloudflare.com` |
| Contenido real de la zona | `A @` (aparcamiento), `CNAME www`→apex, `CNAME _domainconnect`, `TXT _dmarc` de GoDaddy. **Sin MX, sin SPF, sin CAA** |
| Riesgo del cambio de NS | **bajo**: no hay correo que romper |
| ¿Cloudflare copió el `_dmarc`? | ✅ **SÍ — mi apunte anterior era FALSO.** Cotejado el 27-ago 19:40 registro a registro contra los dos autoritativos: `A @`, `A/CNAME www` y `TXT _dmarc` **idénticos** en GoDaddy y Cloudflare. **No se pierde nada en la mudanza.** Sigue sin haber SPF en ninguno de los dos |
| Números en Twilio | uno solo, `+17205946249` (sid `PNc42972…`) |
| Su `voice_url` | ngrok muerto → error 11200. Su `sms_url` es correcto |
| VAPI | `+17208249313` **activo**, asistente «Eko AI Realtors» `5d975722` |
| `/api/v1/webhooks/voice` | JSON de VAPI, **no TwiML** → Twilio no puede apuntar ahí |
| ¿El número está publicado? | `agency_phone` vacío, sin `NEXT_PUBLIC_PHONE` → **nadie lo tiene hoy** |
| Línea de brokerage | **cambiada a «Engel & Völkers»** (27-ago) por decisión del dueño, con la norma delante: **Colorado Rule C-18** exige el nombre licenciado o un *trade name* registrado en la Comisión y en el Secretario de Estado. No pude confirmar cuál es el de su firma empleadora; el dueño decidió el genérico asumiendo el riesgo. El expuesto ante C-18 es el broker con licencia. La variable de la landing también está cambiada pero es *build arg*: **no está viva hasta reconstruir el frontend** |
| ¿Mi clave de Twilio puede escribir? | ✅ **sí** — escritura idempotente, HTTP 200, **0 diferencias en 34 campos** |
| ¿La API de GoDaddy apaga DNSSEC? | 🔴 **no existe**: 0 coincidencias de «dnssec» en su OpenAPI v3 (148 KB) |
| ¿Los TwiML Bins tienen API? | 🔴 **no**: solo consola (documentación de Twilio) |
| Candados del registrador (RDAP) | ⚠️ **4 activos**, incluido `clientUpdateProhibited` → hay que **apagar el Domain Lock** de GoDaddy para cambiar los NS, y volver a encenderlo |
| Registrado / caduca | 2026-08-25 / 2028-08-25 — recién registrado, 2 años por delante |

Fotografía DNS completa guardada como línea base para el cotejo posterior.

### Lo que necesito del dueño (y por qué no puedo hacerlo yo)

1. ✅ **HECHO (27-ago, ~17:05)** — GoDaddy → DNS → DNSSEC desactivado.
   Verificado: los **13 servidores del registro `.com` ya no publican DS**
   (`a/b/m.gtld-servers.net` → solo SOA). El dominio sigue resolviendo.
   ⏳ **Pero aún NO se pueden mover los NS**: la caché de los resolutores
   públicos es **inconsistente entre nodos** — unos ya la soltaron y otros
   retienen los DS viejos con **~5,5 h** de TTL. Mover ahora haría que quien
   caiga en un nodo con caché valide contra una clave que ya no existe →
   **SERVFAIL**. Ventana segura medida: **a partir de las 22:37 del 27-ago**.
   ⚠️ **Cómo comprobarlo, porque una sola consulta MIENTE.** Medido a las
   17:28: `dig` una vez contra 8.8.8.8, 1.1.1.1, 9.9.9.9 y OpenDNS devolvió
   «sin DS» en los cuatro. Repitiendo 20 veces contra 8.8.8.8: **9 de 20
   seguían devolviendo la clave vieja**. Google es anycast y cada nodo tiene su
   propia caché. El criterio de luz verde es **0 de 20**, no «una consulta
   salió vacía».
1.c **REMEDIDO el 27-ago a las 19:39 MDT — sigue sin poder moverse, y ahora
   sé exactamente hasta cuándo.** RDAP de Verisign: `delegationSigned: **false**`
   y `last changed` **2026-08-27T23:05:06Z** — el borrado del DS entró a las
   **17:05 MDT**. Los 4 servidores de `.com` consultados (a, b, l, m) devuelven
   **0** DS. Resolutores públicos, 20 consultas cada uno: **1.1.1.1 → 0/20 ✅**,
   **9.9.9.9 → 0/20 ✅**, **8.8.8.8 → 3/20 todavía sucio**, con **11.856 s** de
   TTL por delante. Caché limpia a partir de las **23:05 MDT**.
   🔴 **Y la espera es obligatoria, no cautela — lo comprobé:** la zona de
   GoDaddy **sigue firmada** (`DNSKEY` vivo en `ns67`), así que esos 3 nodos
   funcionan bien HOY porque la firma que esperan existe: **20 de 20 consultas
   del registro `A` devuelven `NOERROR`, cero SERVFAIL**. En cuanto los NS
   apunten a Cloudflare —que sirve la zona **sin firmar**— esos nodos dejarían
   de resolver el dominio entero. El SERVFAIL lo crearía el cambio, no existe ya.

1.b **Apagar el «Domain Lock»** antes de tocar los nameservers, y volver a
   encenderlo después. RDAP dice `clientUpdateProhibited`: con el candado
   puesto, GoDaddy rechaza el cambio. (El bloqueo ICANN de 60 días por ser un
   registro nuevo **no** afecta: eso impide transferir de registrador, no
   cambiar NS.)
2. ~~Twilio → TwiML Bins~~ **RETIRADO el 27-ago: el dueño tenía razón.** No hay
   que arreglar el número de Twilio, hay que tener un teléfono que conteste — y
   `+17208249313` (VAPI) ya contesta. El de Twilio no está publicado y su único
   trabajo futuro es el SMS, aparcado. El reenvío añadía una pata, coste por
   minuto y una pieza más para llegar al mismo sitio. **Este bloqueo ya no
   existe.**
3. *(opcional)* El token de Cloudflare acotado a esa zona, para que yo haga
   SPF/DMARC y luego el correo.
   🔴 **Primer intento RECHAZADO (27-ago, 19:45).** `set-cloudflare-token.sh`
   hizo su trabajo: preguntó a Cloudflare antes de guardar nada y no guardó
   nada. Pero su mensaje no bastaba para saber qué había fallado, así que el
   segundo intento habría repetido el primero a ciegas.
   **Mi primera hipótesis era que había copiado el ID del token en vez del
   valor, y la descarté midiendo, no razonando:** alimenté al script con las
   tres formas y Cloudflare las distingue con códigos distintos — 32 hex (el ID)
   y 37 hex (la Global API Key) dan **6111 «Invalid format for Authorization
   header»**; solo una cadena BIEN formada da **1000 «Invalid API Token»**, que
   es exactamente lo que salió. Conclusión: la forma era correcta y el valor no
   es el que Cloudflare tiene — pegado a medias, tecleado a mano, o el token
   se creó/rodó después de copiarlo.
   🔴 **SEGUNDO RECHAZO, y el fallo era MÍO: el instrumento estaba roto.**
   La longitud que imprimió el script nuevo lo destapó: **53 caracteres**. Un
   token de usuario tiene ~40; **53 es la longitud de un token account-owned**
   (Manage Account → Account API Tokens). Y `/user/tokens/verify` —lo que este
   script preguntaba— **solo acepta tokens de USUARIO**: ante un token
   account-owned válido devuelve exactamente **1000 «Invalid API Token»**.
   Documentado en tres proyectos independientes que se comieron el mismo bug
   (`lablabs/cloudflare-exporter#200`, `favonia/cloudflare-ddns#1197`,
   `noorinalabs-deploy#511`). **El token del dueño estaba bien las dos veces;
   mi comprobación decía lo contrario y le echaba la culpa a él.**
   **Arreglo**: la verificación ya no pregunta «¿existe este token?» sino
   «¿puede hacer el trabajo?» — `GET /zones?name=denverhomestory.com`. Es la
   capacidad que de verdad necesitamos (Zone:Read), funciona con los dos tipos
   de token, distingue «token no reconocido» de «token válido con el ámbito
   mal», y de paso guarda el `CLOUDFLARE_ZONE_ID` para las ediciones de DNS.
   Un token falso ahora da **9109 «Invalid access token»**, no el 1000 falso.
   Sigue imprimiendo código, longitud y las confusiones de forma — **por forma,
   jamás por valor**. Verificado contra la API real en los tres casos.
   **Lección**: verifica la capacidad que vas a usar, no la existencia de la
   credencial. Un instrumento que culpa al usuario merece que se dude de él
   antes que de él. **El de GoDaddy no lo recomiendo**: no puede
   hacer lo único que hace falta, y tras el cambio GoDaddy solo es registrador.

### ✅ Zona de Cloudflare CONFIGURADA (27-ago, 19:50-20:00)

**El token entró al tercer intento**, con la comprobación arreglada:
`success — el token LEE la zona denverhomestory.com`, estado **`pending`**.
Guardado en `~/.eko-cloudflare.env` (600) junto al `CLOUDFLARE_ZONE_ID`.

🔴 **Su ámbito es MAYOR del que pedí, y hay que decirlo.** El dueño confirmó que
es un token de cuenta completa. Medido: alcanza **4 zonas** — `bittraderbot.com`,
**`blackvoltmobility.com`**, **`ekoaiautomation.com`** (que sirve el panel de Eko
AI Realtors, Zorros y Black Volt) y `denverhomestory.com`. Es decir, **tres
productos vivos de clientes al alcance de un error mío en un solo comando**.
Disciplina auto-impuesta mientras exista: **todo write va contra
`$CLOUDFLARE_ZONE_ID`**, nunca contra un nombre resuelto al vuelo, y cada script
lleva una **guarda dura** que aborta si ese id no responde `denverhomestory.com`.
Recomendación al dueño: rodarlo a un token acotado a esa zona cuando cerremos el
correo.

**Escrito en la zona (y por qué antes del corte, no después):** publicarlo ahora
hace que entre en vigor **en el instante** del cambio de NS, sin la ventana de
suplantación que dejaría hacerlo media hora más tarde.

| Registro | Valor | Motivo |
|---|---|---|
| `TXT @` | `v=spf1 -all` | el dominio no envía correo; la postura honesta es la estricta |
| `TXT _dmarc` | `v=DMARC1; p=reject; rua=…` | sustituye al `p=quarantine` que Cloudflare copió de GoDaddy, cuyo `rua` informaba **a GoDaddy** |
| `A @` ×2, `CNAME www`, `CNAME _domainconnect` | **proxy OFF** (nube gris) | estaban en naranja: Cloudflare habría intentado hablar con el aparcamiento de GoDaddy, que no lo espera → **522/526**, y el cambio de NS se habría visto como una caída. En gris el corte es **invisible** |

⚠️ **Deshacer en orden inverso al armar `hello@denverhomestory.com`**: primero
SPF+DKIM de Resend, y **solo entonces** relajar el `p=reject`.

**Verificado contra los autoritativos, con control negativo.** `A @` y
`CNAME www` responden **idéntico** en GoDaddy y en Cloudflare; el SPF sale ✗ en
el cotejo **a propósito** (existe solo en Cloudflare) — es la prueba de que el
instrumento puede fallar. Antes de eso escribí un cotejo que comparaba **dos
respuestas vacías y decía «IDÉNTICO»**: zsh no parte las palabras como bash y
`dig` recibía el nombre vacío. Lo cazó exigir respuesta no vacía, no la vista.

⚠️ **La medición del DS es RUIDOSA: 3/20 a las 19:39 y 9/20 a las 19:58.** No
es que empeorara — Google es anycast y cada muestra cae en nodos distintos. **La
puerta es el reloj, no la muestra**: TTL cumplido a las **23:05 MDT**.

### 🟡 Cal.com ARMADO, pero NO encendido (27-ago, 20:00-20:20)

Decisión del dueño: citas reales. Clave entregada y guardada por
`deploy/set-calcom-key.sh` en el `.env` (600, respaldo previo).

**Hecho y verificado contra la API:**

| Qué | Estado |
|---|---|
| `CALCOM_API_KEY` | guardada; verificada **listando event types**, no preguntando si existe |
| Event type **«Property showing»** | creado: **id `6849070`**, 45 min, **30 min de margen** después, **aviso mínimo 4 h**, ubicación **en la propiedad** y **sin enlace de vídeo** |
| `CALCOM_EVENT_TYPE_ID=6849070` | escrito en el `.env` |
| Disponibilidad real | ✅ la API devuelve huecos de 45 min a las 09:00 / 09:45 / 10:30 |
| `CALENDAR_SIMULATED` | **sigue ausente → `true`**. NO se ha encendido |

⚠️ **Lección de método, otra vez la misma:** el primer POST de creación no
imprimió nada por una comilla rota **y aun así creó el evento**. El segundo
intento lo destapó con «User already has an event type with this slug». *Sin
salida ≠ no pasó nada*: se comprueba leyendo el recurso, no el eco del comando.

🔴 **Lo que este armado NO resuelve, dicho antes de encenderlo.** La cuenta de
Cal.com es **`denverhomestory@gmail.com`** y el **único** calendario que mira
para detectar conflictos es ese mismo. El calendario de Natalia en Engel &
Völkers **no es visible**. Encenderlo hoy sustituye «horas inventadas» por
«horas reales de un calendario vacío»: mejor (márgenes, aviso, sin vídeo falso,
reserva registrada) pero **la doble reserva de Natalia sigue viva**.
**Decisión del dueño:** que Natalia comparta su calendario de E&V con
`denverhomestory@gmail.com` (basta libre/ocupado) y yo lo activo en Cal.com.
Riesgo anotado: su Workspace de E&V puede bloquear el compartir externo.

🔴 **DOS defectos de código que hay que arreglar ANTES de apagar el simulado**,
los dos encontrados leyendo `create_booking`, no en ejecución:

1. **`"language": "es"` está cableado** en el `attendee`
   (`calendar_cal.py`). Cal.com le escribiría **en español** a un cliente, contra
   la norma del dueño de que clientes y usuarios van en inglés.
2. **Un lead sin email acaba reservando a nombre de Natalia.** Cal.com exige
   email; el código cae a `booking_contact_email`, que **hoy es la dirección de
   Natalia**. Un lead que solo deja teléfono —el caso real del dueño— generaría
   una reserva con ella como asistente y sin nada para el cliente. Refuerza el
   paso de **exigir email en el formulario**.

### Bloqueo, diagnóstico y las dos salidas

**Diagnóstico:** la fase no se puede cerrar porque sus dos acciones restantes
viven en consolas sin API — medido, no supuesto: la especificación de GoDaddy no
tiene DNSSEC, y los TwiML Bins no tienen endpoint REST. No es un fallo de
ejecución ni un intento fallido; es una dependencia externa.

> Actualización 27-ago: de los dos clics **solo queda uno** (el DNSSEC, ya
> hecho). El del TwiML Bin se retiró por innecesario. Lo de abajo queda como
> registro del razonamiento.

**Salida 1 (recomendada) — esperar los dos clics.** ~5 minutos del dueño. Un
TwiML Bin lo hospeda Twilio, así que el reenvío **sigue funcionando aunque
nuestro backend esté caído**. Es la opción más fiable y la que no añade código.

**Salida 2 — servir el TwiML desde nuestro backend.** Me desbloquea del todo y
sí tendría tests, lint y build que enseñar. Se descarta salvo que el dueño la
pida: convierte nuestro backend en **dependencia de las llamadas entrantes**
(si está caído, nadie puede llamar), añade un endpoint público nuevo, y exige un
despliegue que ahora mismo no está autorizado. Peor fiabilidad para ahorrar dos
minutos de consola.

## ✅ FASE CERRADA — Enrutado por nombre de host · commit `7d2e35e`

Se descubrió al ir a construirla: **ya estaba escrita**. El plan la listaba como
pendiente; se corrigió el plan en vez de reescribir código. Lo que aporta esta
sesión es la **validación** que le faltaba, medida hoy y no por inspección.

| # | Punto del checklist | Resultado real |
|---|---|---|
| 1 | Tests | **142/142 en verde**, 10 ficheros, **0 saltados** (`npx vitest run`) |
| 2 | Typecheck | `npx tsc --noEmit` → **sin salida = sin errores** |
| 3 | Build | `npx next build` **compila**; el middleware entra en el bundle (26,7 kB) |
| 4 | Cobertura del código nuevo | `middleware.ts` + `lib/hosts.ts`: **100% líneas, 100% sentencias, 100% funciones, 95,65% ramas** (v8, instalado con `--no-save`: `package.json` intacto) |
| 5 | Secretos en el diff | **0** |
| 6 | Entrada validada / sin depuración | `hostOf()` devuelve `""` ante URL malformada en vez de reventar dentro del middleware; **0** `console.*` en los ficheros de la fase |

**Qué hace, en una línea:** el dominio de marca sirve solo `/`, `/contact` y
`/about` (308 el resto al panel); el panel manda `/` a `/leads` (307). Lista
**blanca**, no negra: olvidar añadir una página nueva la deja fuera del dominio
público, que es la dirección segura.

⚠️ **Trampa del día del despliegue**: `NEXT_PUBLIC_BRAND_URL` y
`NEXT_PUBLIC_PANEL_URL` son **build args** (`docker-compose.yml:295-296`).
Ponerlas y hacer `up -d` **no hace nada**: hay que **reconstruir** el frontend.
Hoy están vacías en el VPS, así que todo esto está inerte — y es un requisito,
no un apaño: redirigir a un nombre que aún no resuelve tumbaría el sitio vivo.

## 🔴 REGLA DEL DUEÑO (27-ago): «Eko AI Realtors» es INTERNO

> «Eko AI Realtors es la plataforma que está detrás de `www.denverhomestory.com`
> y sus redes; el público de denverhomestory.com no debe ver nada de Eko AI
> Realtors. Para uso interno sí.»

Barrido de TODAS las superficies que ve un cliente. Lo que fuga, medido hoy:

| Superficie | Qué ve el cliente | Gravedad |
|---|---|---|
| **Remitente de TODO correo** | `RESEND_FROM = "Eko AI Realtors <noreply@realtors.ekoaiautomation.com>"` — nombre Y dominio de nuestra empresa de software, en cada respuesta y en la invitación de la cita | 🔴 **el peor**: es lo primero que ve en la bandeja |
| Teléfono, saludo | *«thanks for calling Eko AI Realtors»* | 🔴 |
| Teléfono, prompt | *«You are Eko, the friendly AI assistant…»* — puede decirlo si le preguntan quién es | 🔴 |
| `appleWebApp.title` (`app/layout.tsx:29`) | «Eko AI Realtors» si alguien añade la landing a su pantalla de inicio | ⚠️ menor |

**Limpio, comprobado**: la landing (`page.tsx` sobrescribe el título con los
nombres de los asesores), `/contact`, los componentes de landing, y **todo** el
texto del backend (`conversation.py`, `visit_invite.py`, `followups.py`,
`email.py`, `sms.py`, `optout.py`: cero apariciones). El `ORGANIZER` del `.ics`
usa `booking_contact_email`, que en org 1 es Natalia — correcto.

**Arreglo, en dos tiempos:**
1. **Ahora, sin DNS**: cambiar el *nombre visible* del remitente y el saludo del
   teléfono. El dominio sigue verificado en Resend, solo cambia el nombre.
2. **Tras la mudanza del dominio**: `hello@denverhomestory.com` (Parte 3 del
   plan) elimina también el dominio delator.

Los textos exactos los decide el dueño: es su marca de cara al cliente.

## ✅ FASE CERRADA — La marca interna no llega al cliente · commit `f390b1c`

Rama `feat/auditoria-enrutado-host`. Arregla la fuga de marca **y** dos
hallazgos de la auditoría anterior que muerden justo al configurar los hosts.

| # | Punto | Resultado real |
|---|---|---|
| 1 | Tests | **153/153** (eran 142; +11), 11 ficheros, 0 saltados |
| 2 | Typecheck | `npx tsc --noEmit` sin errores |
| 3 | Build | `✓ Compiled successfully`, 17/17 páginas, middleware 26,7 kB |
| 4 | Cobertura | `middleware.ts` + `lib/hosts.ts`: **100% líneas/sentencias/funciones**, 95,23% ramas |
| 5 | Secretos en el diff | 0 |
| 6 | Depuración / validación | 0 `console.*`; `hostOf` sigue devolviendo `""` ante URL malformada |

**Mutaciones verificadas: 8/8 rojas, restaurado verde.** Devolver `/about` a
`PUBLIC_PATHS`; quitar el recorte del punto en el middleware y (por separado) en
`hostOf`; recortar un solo punto en vez de todos; quitar la guarda de hosts
iguales; `307`→`302`; quitar el `title` de `/contact`; quitar el `appleWebApp`
de la landing.

### 🔴 Bloqueante que encontró la auditoría, corregido en la misma fase (`92c2251`)

Con evidencia del HTML construido, no de la lectura del código:
`.next/server/app/contact.html` llevaba
`<title>Eko AI Realtors — Dashboard</title>` y la descripción que vende la
plataforma a inmobiliarias, con `robots: index, follow`. Es la página donde un
desconocido teclea su teléfono, la única pública indexable sin título propio, y
ese título es su resultado en Google y su tarjeta al compartirla por WhatsApp.

**La causa es la que yo mismo había escrito en el commit anterior y no apliqué
aquí**: los metadatos de Next se MEZCLAN, así que lo no declarado se hereda.
Arreglé `appleWebApp` y dejé `title` y `description` heredándose. Ahora
`/contact` declara los cinco campos y su propio `themeColor` (heredaba el noir
del panel). Medido tras el arreglo: **0 ocurrencias de «eko» en `contact.html`**.

La auditoría midió además que **el recorte del punto en `hostOf` no lo cubría
ningún test** — quitarlo dejaba los 13 en verde — y que recortaba un solo punto,
así que `host..` se colaba igual. Ambos corregidos con test propio.

**Lo que arregla:**
- `/about` fuera del dominio de marca. Esa página **vende esta plataforma a
  inmobiliarias**; servírsela a un vendedor de casa que vino de un vídeo es la
  peor página disponible. La auditoría dijo «está desindexada, arréglalo»; con
  la regla del dueño, lo correcto era lo contrario.
- `appleWebApp.title`: los metadatos de Next se **mezclan**, no se reemplazan,
  así que la landing heredaba «Eko AI Realtors» del layout raíz.
- Host acabado en punto (`www.denverhomestory.com.`): mismo nombre para DNS,
  cadena distinta para `===` → servía el panel bajo el dominio de marca.
- `BRAND_URL == PANEL_URL` → redirección infinita; ahora se trata como no
  configurado. Y la guarda deja de comprobar las URLs: `hostOf("") === ""`, así
  que esas cláusulas eran código muerto con forma de comprobación.

## 🚀 DESPLIEGUE PREPARADO — v0.62.0 (esperando autorización)

Producción: VPS `ender-vps`, **v0.61.0**. **Migraciones: NINGUNA**
(`044_message_internal` sigue siendo la cabeza). Sin variables de entorno
nuevas. Es backend + frontend, sin cambios de esquema ni de configuración.

### Antes de empezar
- `curl -s https://inmo-demo.ekoaiautomation.com/api/v1/health` → debe decir
  **`0.61.0`**. Si ya dice 0.62.0, alguien se adelantó: parar.
- Confirmar que la visita **257** sigue `scheduled` (es la que se va a cancelar
  después, y es el motivo de esta tanda).

### Pasos, en este orden
1. Bundle desde el Mac → `scp` al VPS → `git fetch` + checkout de **`7d591e4`**
   (el VPS no puede clonar de GitHub).
2. `docker compose build backend frontend`.
3. `docker compose up -d backend frontend`. **No hay `alembic upgrade`**: nada
   que migrar.

### Verificación post-deploy, medida y no «debería»
- `/api/v1/health` por el **dominio público** → `0.62.0`.
- Abrir la conversación de voz del lead 213 en el panel: los turnos deben
  leerse **en orden**, con el saludo primero (hoy salen revueltos).
- `POST /api/v1/public/leads` con cuerpo vacío → **422**, nunca 3xx.
- `zorros-*` y `blackvolt-*` arriba.

### Y SOLO ENTONCES, la limpieza que motivó todo esto
Cancelar la visita **257** por el camino arreglado → Natalia recibe un `.ics`
`METHOD:CANCEL` con el mismo UID y `SEQUENCE:1`, que **le retira la cita del
calendario**. ⚠️ Ese correo a su dirección es la **excepción deliberada** a la
norma de no enviarle pruebas: no es una prueba, es retirarle la cita falsa que
la prueba ya le puso. **Confirmar con el dueño justo antes.** Después: la visita
en `CANCELLED`, dos filas nuevas con `external_id` real, y los **3 seguimientos**
muertos (`followups.py:201` ya lo garantiza — comprobarlo, no suponerlo).

### Reversión
- Checkout de **`1f471f3`** (v0.61.0) + `build` + `up -d`. Sin migraciones que
  revertir y sin variables que restaurar.
- La cancelación de la 257, una vez hecha, **no se deshace**: habría que crear
  una visita nueva. Por eso va la última y con confirmación.

## ✅ FASE CERRADA — El orden del expediente y el nombre de la cita · `cc7e842`

Rama `feat/orden-y-nombre-de-la-cita`.

| # | Punto | Resultado real |
|---|---|---|
| 1 | Tests | **1180 backend**, 0 fallos, **0 saltados**, base recreada (+4) · frontend **153/153** |
| 2 | Lint / typecheck | `ruff` **All checks passed** · `tsc --noEmit` limpio |
| 3 | Build | `docker build -f backend/Dockerfile` → `sha256:eb4d6…` |
| 4 | Cobertura del código nuevo | Mismo límite ya documentado: `--cov` no atribuye lo ejecutado dentro del ASGI. Sustituido por **mutación**, que sí prueba ejecución |
| 5 | Secretos en el diff | 0 |
| 6 | Depuración / validación | 0 `print`/`console.log`; el nombre dictado pasa por `storable_text` |

**Mutaciones: 5/5 rojas**, y las del orden **verificadas con 60.004 filas**, no
en vacío. Quitar el desempate de `chronological()`; sacar un endpoint del común;
quitar `title=`; `elif name and not lead.name` → `elif name` (que pisaría la
ficha); y el nombre de la reserva.

**El test del orden hubo que rehacerlo dos veces**, y es la lección de la fase:
primero pasaba sin el desempate en vacío, y el segundo intento pasaba con la
tabla llena. Ver el bloqueante más abajo.

**Decisión mantenida:** `lead.name` **no** se toca. El nombre dicho va a
`visit.title`, donde una mala transcripción cuesta una cita en vez de corromper
una identidad; el calendario ya prefiere `title` sobre el nombre del lead.

### 🔴 Bloqueante de la auditoría, corregido en la fase (`ad868b4`)

**Mi test del orden se ponía verde con el bug en cuanto la tabla crecía.**
Medido: vacía → rojo; **60.000 filas → verde**. En vacío el plan es Seq Scan y
el desorden se ve; con datos pasa a Index Scan y el índice devuelve el orden de
inserción, que casualmente es el bueno. Intenté romper el HOT update para que
tocara el índice y **seguía verde**: la conclusión honesta es que no se puede
obligar a Postgres a equivocarse a demanda, así que un test que depende del
plan es una lotería, no un guard.

**La invariante se afirma ahora donde vive**: `chronological()` en
`models/message.py` es la única fuente del orden de lectura y los dos endpoints
la importan — el precedente que este repo ya tiene con `inbox.reached_somebody()`
y por el mismo motivo. Quitar el desempate pone rojo **a cualquier tamaño**, y
sacar un endpoint del común, también.

**Dos importantes más, corregidos porque tocaban lo recién entregado:**
`generate_reply_suggestions` ordenaba `created_at DESC LIMIT 20` sobre turnos
empatados y devolvía **los 20 MÁS ANTIGUOS**, tirando los 7 últimos —donde se
acuerda la cita—: al LLM le llegaba la historia mutilada. Y `_lead_language`
elegía un turno arbitrario para decidir el idioma del `.ics` **y del aviso de
cancelación**. Además, el nombre dicho no llegaba a Cal.com: arreglé
`visit.title` y dejé `attendee_name` con el viejo, así que la confirmación que
recibe **quien llamó** seguía con el nombre de otro.

**Al backlog (menores, con evidencia):** `stated_name != lead.name` es asimétrica
porque `_resolve_or_create_lead` guarda el nombre crudo sin `strip()`;
`caller_name` no se valida, así que «um my name is» ganaría en el calendario; el
docstring de `models/visit.py:53` ya es falso; e `inbox.py:198` tampoco desempata
(sin impacto: `_busy_starts` corta el caso).

**Siguiente paso concreto:** Fase 3 — desplegar (v0.62.0) con autorización, y
sólo entonces cancelar la visita 257 por el camino arreglado.

## ✅ FASE CERRADA — Cancelar una cita ahora avisa · commit `a728e05`

Rama `feat/cancelacion-comunicada`. Lo destapó la primera llamada real del
dueño: al querer limpiar la cita de prueba resultó que **cancelarla no se lo
diría a nadie**.

| # | Punto | Resultado real |
|---|---|---|
| 1 | Tests | **1176 backend**, 0 fallos, **0 saltados**, desde base recreada (+11 nuevos). Frontend intacto: **153/153** |
| 2 | Lint / typecheck | `ruff check app tests` → **All checks passed**; `tsc --noEmit` limpio |
| 3 | Build | `docker build -f backend/Dockerfile` → imagen `sha256:85068…` |
| 4 | Cobertura del código nuevo | `visit_invite.py` **2/2**. ⚠️ En `visits.py` **no se puede medir**: `--cov` no atribuye lo ejecutado dentro del ASGI (comprobado: el test que SÍ ejecuta `cancel_visit` reporta esas líneas como no cubiertas). Sustituido por mutación, que es prueba de ejecución |
| 5 | Secretos en el diff | 0 |
| 6 | Depuración / errores | 0 `print`/`console.log`; el aviso no puede tumbar la cancelación |

**Mutaciones: 8/8 rojas, restaurado verde.** Quitar la llamada de
`cancel_visit`; `SEQUENCE` siempre 0; usar los textos de reserva; dejar la fila
reenviable (`send_attempts=0`); quitar el `try/except` del idioma; borrar una
clave del bloque español; usar la etiqueta de reserva para el motivo; y
`if not local_only` alrededor del aviso.

### Auditoría independiente (`a728e05`) — 0 bloqueantes, 2 importantes corregidos

Corrió con **rol NOBYPASSRLS propio y base propia**, así que su verificación de
aislamiento vale: org A cancelando la visita de org B → **404, 0 correos**.

Los dos importantes se arreglaron **en la fase** (`7e6699b`) en vez de ir al
backlog, y uno merece explicación: **el bloque español no tenía prueba, y su
fallo es invisible** — un `KeyError` cae en el `except` general y lo medido son
**0 envíos**. Una errata ahí no da un correo raro: da una cancelación que nadie
llega a saber, con toda la suite en inglés en verde. El otro: `local_only` no
estaba cubierto pese a que el commit prometía que también avisa.

**Al backlog, con evidencia:** quitar `ORGANIZER` del `.ics` no pone rojo nada,
y el `ATTENDEE` de un CANCEL conserva `PARTSTAT=NEEDS-ACTION;RSVP=TRUE`, o sea
que pide aceptar o rechazar un evento ya retirado. Tocan `icalendar.py`, que
comparten reserva y cancelación, así que van con su propia tanda.

**Lo que el plan no vio y apareció al ejecutar:** `cancelled=True` **no estaba
completo por dentro**. Solo llegaba al `.ics` y al `method=` del MIME; el asunto
y el cuerpo seguían saliendo de la copia de reserva, así que el correo habría
dicho *«Your visit is confirmed»* con un adjunto que la cancela. Y
`build_visit_ics` aceptaba `sequence` que nadie pasaba: un CANCEL habría salido
con `SEQUENCE:0` y **Outlook puede ignorarlo** (RFC 5546).

**Decisiones:** el aviso sale **después** del commit y su fallo **no** revierte
la cancelación — deshacerla devolvería una cita a la que el agente ya no va a
ir. `local_only` **también** avisa: ese flag significa «no llames al proveedor»,
que es justo cuando más importa que lo sepa una persona.

**Siguiente paso concreto:** Fase 2 del plan — el desempate por `id` en
`conversations.py:127` y el nombre dicho en `visit.title`.

## ✅ v0.61.0 EN PRODUCCIÓN — desplegada y verificada (27-ago-2026)

Autorizada por el dueño y desplegada desde `fbd2bea`. **Sin migraciones**
(`044_message_internal` sigue siendo la cabeza).

| Verificación | Resultado real |
|---|---|
| `/api/v1/health` por el dominio público | **`0.61.0`**, `llm_fallback:"ok"`, `captcha:"on"` |
| Remitente de correo | Enviado uno real al dueño y **releído desde la API de Resend**: `from: Denver Home Story <noreply@realtors.ekoaiautomation.com>`, `last_event: delivered` |
| Título de `/contact` en producción | `Contact Natalia & Robbie · Engel & Völkers Aspen` — era `Eko AI Realtors — Dashboard` |
| «Eko AI» en las páginas públicas | **0** en `/` y en `/contact` |
| Rutas con los hosts sin configurar | `/`, `/contact`, `/about`, `/leads`, `/login` → **200**: el middleware sigue inerte, como debe |
| Formulario público | `POST /api/v1/public/leads` → **422** (validación), **nunca 3xx** |
| Webhook de voz sin firma | **403** |
| `agency_name` org 1 | `Denver Home Story` (era `Natalia & Robbie`) |
| Zorros y Black Volt | arriba desde hace 3, 4 y 7 semanas; `zorros.ekoaiautomation.com` responde |
| Datos | 77 mensajes · 38 leads · 4 visitas. El +1 es **la llamada de prueba del dueño**, no dato mío |

**Hallazgo bueno de propina:** esa llamada real prueba que la identificación por
identificador de llamada **funciona** — se archivó en la ficha que ya existía con
ese teléfono (lead 213, del 26-may) en vez de crear una nueva. Es exactamente el
mecanismo que el reenvío TwiML descartado habría puesto en riesgo.

**Reversión (no usada, escrita):** checkout de `0857451` + `build` + `up -d`;
borrar la línea `RESEND_FROM` del `.env` (vuelve al default de compose);
`UPDATE agent_settings SET agency_name='Natalia & Robbie' WHERE org_id=1`; el
prompt anterior de VAPI está guardado. Respaldo del `.env` en `~/.env.bak.v060`
(600). Sin migraciones que revertir.

### Pendiente de confirmación humana
El dueño debe **volver a llamar** a `+1 720 824-9313`: su prueba fue a las 16:44
y el asistente se cambió a las ~17:20, así que oyó el saludo antiguo.

### Backlog nuevo (menores, no bloquean)
- `/api/v1/health` publica `"app":"Eko AI Inmobiliario"` — nombre de la
  plataforma **y en español**, en un endpoint público.
- El pie de la landing enlaza a `/login`, que sí muestra el nombre de la
  plataforma. Lo resuelve el 308 en cuanto se configuren los hosts.
- `NEXT_PUBLIC_LANDING_BROKERAGE` dice «Engel & Völkers **Aspen**» con el
  mercado en Denver — decisión de Natalia.

## Auditoría independiente del enrutado por host (`7d2e35e`)

**Bloqueantes: ninguno.** Descartó con evidencia el open-redirect, el salto del
matcher por `%2e%2e`/`//` (Next normaliza antes del middleware), y verificó la
inercia en servidor real con las variables vacías.

| # | Hallazgo | Estado |
|---|---|---|
| I1 | **`/about` quedó desindexada hoy**: el `robots:{index:false}` del layout raíz es nuevo y `/about` no exporta `metadata` que lo sobrescriba, pero sí está en `PUBLIC_PATHS`. Regresión real y ya viva | backlog, **arreglar antes de publicar la marca** |
| I2 | `Host: www.denverhomestory.com.` (con punto final) **sirve el panel** en el dominio de marca: el middleware quita el puerto pero no el punto | backlog, **arreglar antes de configurar los hosts** |
| I3 | `BRAND_URL == PANEL_URL` produce **bucle de redirección infinito**, sin guarda ni test | backlog, alcanzable a mano en la transición |
| M1–M4 | 4 huecos de mutación (la suite queda verde al mutar): `307`→`302`, los dos `.toLowerCase()`, y media guarda de inercia **inalcanzable** (`hostOf("")==""` hace que `!PANEL_URL` nunca se evalúe) | backlog |

I1, I2 e I3 **no bloquean hoy** (todo inerte), pero I1 ya está viva y I2/I3
muerden justo el día que se configuren los hostnames — que es esta semana.

### Hallazgos abiertos del asistente de voz (importantes, no bloquean)

Medido en el asistente vivo `5d975722` el 27-ago:

- 🔴 **Fallo de marca**: saluda con *«thanks for calling Eko AI Realtors»*. Quien
  llama viene de un vídeo de **Denver Home Story** y busca un agente
  inmobiliario, no una empresa de software. Cambiable por API; el texto lo
  decide el dueño.
- ⚠️ Corre con `claude-sonnet-4-5` de **Anthropic** mientras el resto del
  producto va con Kimi/MiniMax. No viola CLAUDE.md (la regla prohíbe el OAuth
  del plan Max, no una clave de pago dentro de VAPI), pero es gasto por token
  que nadie vigila.
- ⚠️ Transcripción fijada a **inglés**. Coherente con la decisión de «todo en
  inglés por ahora»; un hispanohablante saldría transcrito como basura.
- `agency_phone` **vacío** en Ajustes: hasta que lleve `+17208249313`, el
  sistema no se identifica con ningún teléfono.

### Decisiones tomadas y por qué

- **Reenvío TwiML en vez de importar el número a VAPI.** Importar exige
  entregarle a VAPI el Account SID y el **Auth Token maestro** de Twilio: con él
  puede comprar números, mandar SMS y gastar. El reenvío no comparte ninguna
  credencial y se revierte en 10 s.
- **`callerId="{{From}}"` es obligatorio, no cosmético.** `book_visit` asocia el
  lead al identificador de llamada; sin él, todos los que llamen colapsarían en
  un único lead compartido.
- **SPF `-all` + DMARC `p=reject` en cuanto se mueva el dominio.** No envía
  correo, así que lo estricto es lo honesto — y hay que deshacerlo **en orden
  inverso** (SPF/DKIM de Resend primero) cuando se arme `hello@`.

---

## 📌 PENDIENTES abiertos (decisión tomada: se hacen más tarde)

### 1. La agenda se hace a ciegas — **DECIDIDO: Cal.com + la cuenta de Google de Natalia**, se hace más tarde (dueño, 27-ago)

Estado medido en producción hoy: `CALENDAR_SIMULATED=true`, `CALCOM_API_KEY` y
`CALCOM_EVENT_TYPE_ID` **vacías**, y las 4 visitas con `external_booking_id`
`calcom-sim-…`. La cita se **registra** bien y desde v0.58.0 se **avisa** bien;
lo que no existe es la **disponibilidad**.

Las horas se generan en `_simulated_slots` y se cruzan **solo** contra nuestra
tabla `visits` (`_busy_starts`). De la agenda real de Natalia el sistema no sabe
nada, así que puede ofrecer una hora en la que está ocupada.

**Decisión del dueño, 27-ago: opción B — Cal.com, conectado a la cuenta de
Google de Natalia. Nada de calendario interno.** Un calendario interno solo sabe
lo que alguien teclea en él, así que obligaría a Natalia a mantener su
disponibilidad en dos sitios y fallaría en silencio el día que se le olvide; y
el trabajo se tiraría al enchufar Cal.com, que se lleva la generación de horas
entera. Google Calendar directo queda descartado por coste: verificado que el
login de Google **no** es un flujo OAuth con refresh token (no hay
`client_secret` ni almacén de tokens en el repo), así que habría que construirlo
desde cero — es reconstruir Cal.com.

**Insumos que faltan, y son del dueño:** cuenta de Cal.com + API key, el event
type id de la visita, y —el que se olvida— **el Google Calendar de Natalia
conectado a Cal.com**. Sin ese tercero, encenderlo empeora las cosas: seguiría
ofreciendo horas ocupadas, pero ya con una reserva real encima de la suya.

### 2bis. El correo al cliente sale con el nombre de la plataforma, no el de la marca

**DECIDIDO (dueño, 27-ago).** Hoy el remitente es
`Eko AI Realtors <noreply@realtors.ekoaiautomation.com>`: el cliente abre el
correo de su cita y lee el nombre del **software**, no el de quien le va a
enseñar la casa. Y le pedimos que responda a un `noreply@`.

**Destino:** `Natalia & Robbie <hello@denverhomestory.com>`. La persona da la
confianza —en inmobiliaria la confianza es siempre una persona— y el dominio
pone la marca. Cuadra con la firma que ya lleva el cuerpo. El correo de
plataforma (avisos de operación, recuperación de contraseña) **se queda en
`ekoaiautomation.com`**: mismo reparto que la web, marca de cara al público y
plataforma por detrás.

**Verificado antes de decidirlo:**
- **Las respuestas del cliente SÍ llegan hoy.** `channel_routes` está vacía y el
  resolvedor cae al camino de un solo inquilino (la org `Demo` queda excluida).
  La frase «responde a este mensaje» del correo de la cita no es una promesa
  falsa. **Pero vive de un fallback**: el propio código rechaza el correo en
  cuanto exista una segunda agencia real. Al montar esto hay que crear la fila
  de `channel_routes` de verdad, no seguir viviendo del descarte.
- **Enviar como `@engelvoelkers.com` es imposible y además peligroso.** Su SPF
  termina en `-all` (rechazo duro) y Resend no está incluido; su DMARC es
  `p=quarantine` **con `ruf=mailto:MinorAlert.DMARC@engelvoelkers.com`**, así
  que un intento le llegaría a **su equipo de seguridad como una suplantación
  de marca**. Riesgo para la relación de Natalia con su brokerage. No se
  intenta, ni como prueba.
- Su dirección de E&V se queda **solo como destinataria** (`booking_contact_email`),
  que ya funciona y no cuesta nada. Usan Google Workspace, así que nuestro
  correo hacia ella tiene que ir impecablemente autenticado o lo filtran.
- 🔴 **Trampa ya puesta en el dominio nuevo**: su `_dmarc` heredado de GoDaddy
  dice `p=quarantine`. Hoy es inofensivo porque nadie envía desde ahí. En el
  momento en que cambiemos el remitente **sin haber publicado antes los
  registros de Resend, TODOS los correos a clientes van a spam.** No algunos.
- Un dominio que nunca ha enviado **no tiene reputación**: los primeros envíos
  pueden filtrarse aunque todo esté bien. Es normal, no es avería.

**Va después de la mudanza de nameservers**, porque los registros de Resend se
crean en Cloudflare.

### 2. `business_hours` no gobierna las horas que se ofrecen

`calendar_cal.py:36` — `SIMULATED_HOURS_OF_DAY = (10, 11, 14, 15, 16)`, lunes a
viernes, **cableado**. `agent_settings.business_hours` (editable en Ajustes,
09:00–19:00) no lo lee el calendario: solo se usa en `conversation.py` para
*decirle* al lead el horario. El sistema anuncia 9–19 y ofrece cinco huecos
fijos. Arreglarlo solo merece la pena si Cal.com tarda: él se lleva esa función.

---

## Atribución legible (Fase 2) — ✅ construida, SIN desplegar (27-ago-2026)

Rama `feat/registro-de-la-cita`. Cierra la tanda: **bump v0.60.0**.

**Qué hace**: `utm_*`, `gclid`, `fbclid`, `landing_variant`, `tier`, `referrer`
—capturados desde que existe la landing y que **ninguna API devolvía**— salen
ya en el lead y se pintan en su ficha («De dónde vino»). Es el dato que dice si
los vídeos funcionan, y va a hacer falta en cuanto se enciendan.

**Checklist real**:
1. ✅ 1165 backend desde base recreada (9 nuevos) · 142 frontend · 0 saltados
2. ✅ ruff limpio · tsc limpio
3. ✅ `docker build` backend OK (2e43d19a)
4. ✅ cobertura: `_attribution_of` y `_lead_out` **no aparecen en «Missing»**
5. ✅ diff sin secretos, sin prints
6. ✅ entrada externa: `_attribution_of` no lanza con `meta` no-dict, anidado
   no-dict, lista o valores no-string — con test para cada forma
7. ✅ **2 mutaciones**: quitar la lista blanca (5 rojos) · reponer el bug de
   nivel (5 rojos, incluido el de punta a punta)

**🔴 Bloqueante encontrado por la auditoría, y era mío de raíz**: la primera
versión leía el **primer nivel** de `meta`, pero `_record_attribution` anida
bajo `meta["attribution"]`. Devolvía `{}` **para todo lead real** y el bloque
de la ficha no se habría pintado nunca — con el CHANGELOG anunciándolo como
entregado. Peor: **mis tests fabricaban a mano la forma plana**, así que ocho
tests pasaban contra un camino imposible. Es un «test que no puede fallar» en
estado puro. Arreglado, y la regla nueva es que **todo test que toque la forma
almacenada pasa por `capture_lead`**, nunca por un `meta` inventado.

**Segundo hallazgo, del mismo tipo**: el test de la lista usaba `?q=<teléfono>`
creyendo filtrar. Ese parámetro **no existe** y FastAPI lo ignora en silencio:
pasaba solo porque el lead caía en la primera página. Ahora usa `sort=recent` y
afirma la posición, que es determinista.

**Decisiones**:
- Se devuelve el **primer toque**, no el último: es lo que el escritor protege
  a propósito (acreditar el último envío acreditaría siempre al retargeting).
  `attribution_later` se guarda y **no** se expone; dicho en el changelog.
- Lista blanca **importada** de `capture.py`, no copiada, con un test que
  recorre `ATTRIBUTION_KEYS` entera — dos listas habrían derivado en silencio.

**Backlog (menores)**: `tier` se pinta como chip de procedencia junto a
`utm_source` (está en la lista blanca del propio capture, pero mezcla vocabulario);
`attribution_later` sigue sin superficie; `message_count` cuenta las notas
internas; `analytics.py` no las filtra.

**Siguiente paso**: despliegue preparado abajo — **esperando autorización**.

---

## Registro de la cita (Fase 1) — ✅ construida, SIN desplegar (27-ago-2026)

Rama `feat/registro-de-la-cita` (apilada sobre feat/temas-de-vendedor). Plan:
sección «el registro completo» de `si-haz-el-plan-jazzy-sifakis.md`.

**Qué hace**: los dos correos de la invitación de una cita entran por fin en la
conversación del lead — el suyo como mensaje normal, el de la agencia como
**nota interna** (`messages.internal`, migración 044). El panel la pinta
distinta (chip «nota interna», borde punteado); el barrido de reenvío y los dos
constructores de historia del LLM la excluyen por `internal IS false`.

**Checklist real**:
1. ✅ 1156 backend desde base recreada (12 nuevos) · 142 frontend · 0 saltados
2. ✅ ruff limpio · tsc limpio
3. ✅ `docker build` backend OK (e77a5280)
4. ✅ cobertura: `visit_invite.py` 88%; lo sin cubrir son ramas previas a la fase
5. ✅ diff sin secretos (matches revisados a mano: stubs de test y el guion de
   Cloudflare, que lee el valor en runtime y no contiene ninguno)
6. ✅ sin prints/console.log; sin entrada externa nueva
7. ✅ INSERT real como `eko_app` con `internal=true`: los tests escriben por
   `get_session_factory()` (= `DATABASE_URL_APP`, RLS) — probado por el camino real
8. ✅ **6 mutaciones verificadas**, cada una roja solo en su test: filtro del
   barrido · filtro de las 2 historias LLM · intentos gastados en fallo ·
   filtro de `reached_somebody` · filtro de la vista previa · elección de hilo

**Auditoría independiente (1 subagente, cerrado)** — 2 bloqueantes + 1 subido:
- **B1** el Inbox no filtraba `internal`: la nota de la agencia se volvía «la
  última palabra» y un lead sin contestar salía del triaje en silencio (peor en
  el lead solo-teléfono, donde la nota es la ÚNICA fila). Arreglado en la
  expresión compartida `reached_somebody()` + la vista previa. Con mutación.
- **B2** registrar siempre en una conversación `email` nueva la convertía en
  «primaria» (nace con `last_at` = now): el composer saltaba a email para un
  lead solo-teléfono (`channel_identifier_mismatch`) y las sugerencias daban
  `empty_conversation`. Arreglado: el registro **reutiliza el hilo ACTIVO más
  reciente del lead**; solo crea el de email si no hay ninguno Y el lead tiene
  email; sin hilo y sin email, se omite con log. Con mutación.
- **I1→bloqueante** (reclasificado: viola el «must never break a booking» del
  propio módulo): el `rollback` sobre la sesión del llamador expiraba sus
  objetos → `VisitOut.model_validate(visit)` = 500 sobre una reserva ya
  comiteada, y la segunda fila se perdía también. Arreglado: el registro corre
  en **su propia sesión** con valores planos, nunca objetos del llamador. Test
  que accede a los atributos del llamador después del fallo.

**Hallazgos NO de mi diff, arreglados de paso con evidencia**:
- `test_consent_holds_backfill::test_the_clamp_is_right_at_the_edges` sembraba
  la fila «due today» EXACTAMENTE sobre la discontinuidad del FLOOR (reloj de
  Python vs reloj de Postgres): rojo intermitente medido. Sembrada a ~86 s.
- El stub de Resend con `return_value` fijo repetía el id y chocaba con
  `uq_messages_external_id`; ahora `_sender()` da un id por mensaje y hay un
  test que fija el comportamiento bajo colisión (se pierde 1 fila, no 2).

**Backlog (importantes/menores de la auditoría, con evidencia)**:
- M1 `message_count` (`conversations.py:171`) cuenta las internas — consistente
  con el timeline que las pinta; decidir si se excluye.
- M2 `analytics.py:82-96` sin filtro `internal`: una nota puede contar como
  primera respuesta. Menor mientras las notas sean solo de citas.
- M3 el de-flake de 0→0.001 suelta el borde exacto `NOW()==scheduled_for`; una
  mutación FLOOR→CEIL ya no se cazaría en 0. Alternativa: sembrar con now() de
  Postgres.
- M4 la burbuja interna aún dice «AI agent» + «Enviado»; el chip lo desmiente.
- M5 la nota interna queda `fair_housing_flags=NULL` («nunca revisado») y el
  vigilante no la ve — es texto nuestro; decidir si se filtra o se exime.

**Siguiente paso**: Fase 2 del plan — exponer la atribución (`ATTRIBUTION_KEYS`)
en la API del lead y pintarla en `LeadDetail.tsx`; bump v0.60.0 al cerrar la
tanda. Después: preparar deploy y PARAR (autorización del dueño).

---

## Temas de vendedor + CTA — ✅ **v0.59.0 lista, SIN desplegar** (27-ago-2026)

Rama `feat/temas-de-vendedor`, apilada sobre `feat/idioma-por-defecto-ingles`.
Es el requisito que el plan marcaba **antes** de encender la generación de
vídeos. No enciende nada: `CONTENT_STUDIO_ENABLED` sigue en `false`.

**El plan tenía mal el número y lo repetí dos veces sin medirlo.** No eran «10
de comprador contra 5 de vendedor»: había **7 temas, 6 de comprador y 1 de
vendedor**. Peor de lo escrito.

**Construido:**
- `Topic.audience` (`seller`/`buyer`/`both`), **declarado y no deducido** del
  brief: el equilibrio de la rotación es una decisión de negocio, y una
  decisión que solo vive en prosa no se puede probar.
- 5 temas de vendedor nuevos + 3 existentes reencuadrados a `both` (inspección,
  oferta→cierre, pulso de mercado): quien vende vive esos tres momentos igual
  que quien compra, y el brief solo miraba a un lado.
- Reparto: **6 vendedor, 3 los dos, 3 comprador** — 9 de 12 alcanzan a quien
  vende. Ningún tema de comprador borrado: traen alcance y un vendedor en
  Denver casi siempre compra después.
- `CONTENT_CTA_URL`, **vacía por defecto**, añadida al pie **antes** de
  `find_violations`. Lo que se publica tiene que haber pasado por el filtro; el
  texto del enlace no lo escribe el LLM.

**Verificación:** 1144 backend desde base recreada · 142 frontend · ruff y tsc
limpios. Dos mutaciones, cada una roja en su test y solo en el suyo.

**Falta del dueño para que la CTA sirva:** `denverhomestory.com` vivo y
`CONTENT_CTA_URL` puesta en el `.env`.

---

## Idioma por defecto — ✅ **v0.58.1 lista, SIN desplegar** (27-ago-2026)

Rama `feat/idioma-por-defecto-ingles`. Los clientes de este producto son **de
habla inglesa**; el español es solo el idioma en que el dueño da instrucciones.

**Producción ya escribía en inglés** y eso se verificó antes de tocar nada: la
fila de la agencia tiene `["en", "es"]` puesta a mano, `conversation.py` cae a
`["en", "es"]`, `followups.py` a `["en"]` y `services/i18n.py` documenta *"en
(English, the DEFAULT)"*. El correo en español de la prueba del `.ics` lo forzó
**mi arnés** con `language="es"`, no el sistema.

Lo que sí estaba al revés era el **default del modelo**, `["es", "en"]`: los dos
sitios que crean la fila lo hacen con un `AgentSettings()` desnudo
(`api/v1/settings.py:144`, `scripts/seed_demo.py:216`), así que **toda
organización nueva** —y esto se vende multi-tenant— habría empezado hablándoles
en español a clientes de habla inglesa. Sin migración: la columna no tiene
`server_default`, y un default de SQLAlchemy solo actúa al INSERTAR.

**Tests nuevos que fijan el comportamiento, no el literal**: una agencia recién
creada arranca en inglés, y un lead que nunca escribió se responde en inglés.
Mutación verificada: devolver el default pone **los dos** en rojo.

**Hallazgo que destapó mi propio cambio** (`test_models.py::test_agent_settings_singleton`):
ese test buscaba la fila por **`id == 1`**, una premisa muerta — hay una fila
por organización y la unicidad vive en `uq_agent_settings_org_id`; el propio
`api/v1/settings.py:143` lo dice en un comentario. Pasaba **por accidente**:
el test que creaba la fila de la org 1 se llevaba el id 1 de la secuencia. Mi
test consume un valor de esa secuencia antes, la fila pasó a id 2, y entonces
intentaba INSERTAR una segunda fila para la org 1 y moría en la restricción
única. No lo silencié: lo reclavé a `org_id`, que es la clave de verdad.

Verificación: **1135 backend desde base recreada** · 142 frontend · ruff y tsc
limpios. **No desplegado** — espera autorización.

---

## Citas `.ics` — ✅ **v0.58.0 EN PRODUCCIÓN** (27-ago-2026)

Rama `feat/citas-ics`, commit `f3495be`. `/api/v1/health` del dominio público
→ `0.58.0`, `llm_fallback:"ok"`, `captcha:"on"`. Sin migración.

**El eslabón que estaba roto**: las 4 visitas de producción llevan
`external_booking_id` = `calcom-sim-…`. `CALENDAR_SIMULATED=true`, así que el
asistente de voz confirmaba citas **en voz alta** y no se reservaba nada. Un
`.ics` no lee disponibilidad —eso sigue pendiente de Cal.com— pero pone la cita
en el calendario de las dos partes, que es lo que el producto prometía.

**Construido:**
- `services/icalendar.py`: RFC 5545 a mano. CRLF, plegado a **75 octetos** sin
  partir un carácter multibyte, escapado TEXT, UID estable por visita
  (`eko-visit-<id>@…`), `METHOD:REQUEST`/`CANCEL`. Rechaza un `datetime` naíf en
  vez de escribirlo como UTC.
- `services/visit_invite.py`: manda al lead y a la agencia por separado — un
  correo malo del lead no cuesta la copia de la agencia. **Nunca lanza**: la
  visita es el hecho, la invitación es el aviso.
- Cableado en **los dos** sitios que crean visitas: `api/v1/visits.py` (panel y
  landing) y `services/voice.py` (teléfono). Test AST que lo exige, con guarda
  sobre la guarda.
- `send_email` acepta adjuntos (base64 en el punto de envío); la rama simulada
  loguea **nombre y tamaño**, jamás el contenido.
- `CAPTURE_REQUIRE_EMAIL=true`: mientras el SMS esté caído (30034), un lead que
  solo deja teléfono no es alcanzable por ningún canal automático. Es un ajuste,
  no una constante: vuelve a `false` sin desplegar cuando el A2P entregue.
- `booking_contact_email` puesto en producción a `natalia.kanonerova@engelvoelkers.com`
  (estaba **vacío**: sin él esa copia no salía de ninguna manera).

**Verificación, medida contra el sistema vivo:**
- 1133 backend desde base recreada · 142 frontend · ruff y tsc limpios.
- Tres mutaciones verificadas (frontera multibyte del plegado, exigencia de
  email, cableado de `send_visit_invitation`): cada una pone en rojo **un** test,
  el correcto.
- Cita de prueba real contra producción, en transacción con **rollback**: ICS
  bien formado, 10:00 MDT = 16:00Z, DTEND +45 min, coma escapada en LOCATION,
  plegado con continuación. Resend devolvió id `3f1c8027-…`, y **Gmail pintó los
  botones Yes/No/Maybe** — un cliente de calendario real aceptó el evento.
  `visits` sigue en 4 filas y `leads` en 38: la prueba no dejó nada.

**Dos hallazgos de la verificación, los dos míos:**
1. `.env.example` quedó corrupto por una inserción con `sed`: partió el
   comentario del bloque SMS y dejó `SMS_SIMULATED=true (dev default), outbound…`
   como **línea de asignación** en un fichero que la gente copia a `.env`.
   Arreglado y barrido por **forma**: 0 líneas malformadas y 0 claves duplicadas
   en todo el fichero.
2. El arnés de prueba hardcodeaba `org_id=1` dentro de un `run_for_every_org`.
   **El RLS lo rechazó** al llegar a la org 2. Efecto colateral útil: hay **dos**
   organizaciones —`Robbie & Natalia` (activa, 38 leads) y `Demo` (trial, 0)— y
   `Demo` **no tiene fila en `agent_settings`**, así que una cita suya se queda
   sin copia a la agencia con un `log.warning`, sin reventar. Es el
   comportamiento correcto, pero no estaba escrito en ningún sitio hasta ahora.

**Sigue abierto y hay que decirlo:** las citas **siguen sin reservarse en
Cal.com** (`CALENDAR_SIMULATED=true`), así que las horas ofrecidas se generan
localmente y el sistema **puede ofrecer una hora en la que Natalia está
ocupada**. El `.ics` cierra el aviso, no la disponibilidad.

---

## Fase B (landing) — parcial ✅

Rama `feat/landing-denver-home-story`. Commits `7d2e35e`, `2023856`, `e8ab9bf`.

**Hallazgo que reduce la fase**: la landing **ya implementaba el diseño v4 casi
entero** (49 claves i18n). Lo que faltaba en la página viva estaba ausente por
**configuración**, no por código: `NEXT_PUBLIC_LANDING_ADDRESS`, `MARKETS`,
`PHONE`… vacías, y `lib/landing.ts` oculta la sección en vez de inventarse un
dato de un broker con licencia. Rellenarlas es del dueño y exige **rebuild**,
no reinicio.

**Construido:**
- Enrutado por host + canónicas + `robots:index:false` por defecto, **inerte
  hasta que `NEXT_PUBLIC_BRAND_URL`/`PANEL_URL` estén puestas**. Mutaciones
  verificadas: quitar un `ARG` → un solo test rojo, el correcto; quitar la
  guarda de inercia → rojo el caso a medio configurar.
- El guardián de cableado barría 3 ficheros a mano y no vio mis 2 variables
  nuevas. Ahora barre por forma `app/`, `components/`, `lib/`.
- `vitest.config.ts` con el alias `@/` (sin jsdom: solo resolución de rutas).
- Sección **«Where we work»** con las 3 tarjetas de mercado y sus imágenes,
  servidas desde `public/landing/` y no desde la CDN del diseño.
- `.gitignore` por forma (`.env.*` + `!.env.example`): `.env.pre-mudanza-20260827`
  con el token vivo estaba a un `git add -A` del repo. Historial limpio,
  verificado en los 8 commits.

**Checklist real**: tsc limpio · 142 tests verdes (10 ficheros) · `npm run build`
compila y la salida prerenderizada contiene la sección · `public/` no
gitignorado (si lo estuviera, las imágenes no llegarían al contenedor).
Backend sin tocar, así que su suite no aplica.

**🔴 CORRECCIÓN de una afirmación falsa de este plan**: decía que VAPI no estaba
configurado. **Las cuatro variables están puestas**, `VOICE_SIMULATED=false`, y
hay una conversación de voz real de **22 mensajes del 3-jun-2026**. Sin
verificar: si la cuenta VAPI sigue activa (exige la clave).

**Hueco asumido por decisión del dueño (27-ago)**: `CALENDAR_SIMULATED=true`, y
las dos herramientas del asistente de voz (`check_availability`, `book_visit`)
pasan por ahí. El asistente confirma citas **en voz alta** que no se reservan.
El dueño eligió publicar la landing primero y arreglar el calendario después.

**Pendiente del dueño**: rellenar las `NEXT_PUBLIC_LANDING_*`; decidir sobre la
frase `landing.how.answered.body`, que promete «horarios confirmados»; mover los
nameservers; rotar el `TWILIO_AUTH_TOKEN` (expuesto en `.bash_history` del ROG).

---

## Fase copias — producción tenía CERO copias de seguridad ✅

Rama `feat/copias-de-seguridad` (desde `feat/mudanza-vps`, porque es
consecuencia directa de la mudanza y se fusionarán juntas).

**El hallazgo, medido**: ni el ROG antes ni el VPS después. Timeshift **nunca**
cubrió los volúmenes de Docker — `/var/lib/docker/*` es una regla **built-in**
del `exclude.list` de cada snapshot, que `timeshift.json` no puede anular. El
único cron de copias del VPS era el de Black Volt. 38 leads y 72 mensajes de
clientes reales de un broker con licencia, sin una sola copia.

**Qué se construyó**: `deploy/backup-db.sh` (corre en el VPS, 04:15 UTC) y
`deploy/backup-pull.sh` (corre en el ROG, 04:45 local). **El ROG tira, el VPS no
empuja**: un push exige credenciales en el VPS que puedan escribir en el almacén
de copias, así que quien tome el VPS se lleva también sus copias. Además es la
única dirección que funciona (el VPS no alcanza al ROG por SSH).

**Checklist, con resultado real:**
- Copia tomada y **restaurada** en base desechable → **72 / 38 / 4 / 9**,
  idéntico a producción. ✅
- Guarda de suelo de bytes: dump de base vacía (820 B) → rechazado, **sin
  rotar**. ✅
- Guarda de `pg_restore -l`: **aislada** bajando el suelo a 1 byte → «lists only
  0 entries» → rechazado, sin rotar. ✅ (la primera guarda enmascaraba a la
  segunda; verificarlas por separado es lo que lo destapó)
- Con `KEEP=1`, la copia buena de enero **sobrevivió a los dos intentos**. ✅
- Copia en el ROG, verificada allí y **restaurada allí**. ✅
- Crons: VPS 6→7 entradas (Black Volt intacto); ROG 45→46, **insertada encima
  del marcador de BitTrader** (línea 12 vs marcador en 20). ✅

**Hallazgo dentro del hallazgo**: restaurar el dump en un clúster limpio daba
**36 errores, todos `role "eko_app" does not exist`**. El dump lleva las **49
entradas POLICY/ACL** —todo el aislamiento entre agencias— pero `pg_dump` es de
base, no de clúster, y los roles viven en `pg_dumpall`. Sin eso, una
restauración a las 3 de la mañana devuelve **todas las filas y ninguna
seguridad**, y `pg_restore` sale con código 0. Corregido: el script escribe
también `eko-roles-*.sql` (`--no-role-passwords`: nombres y atributos, **no**
hashes), el pull exige las dos mitades, y el runbook de restauración va en la
cabecera del script.

**Simulacro completo siguiendo ese runbook**: roles primero → **0 errores** de
restauración; y `eko_app` atado a la org 1 ve **38** leads, atado a la org 2 ve
**0**, y sin contexto ve **0**. El aislamiento vuelve vivo.

**Sin suite**: no se tocó código de app (solo `deploy/*.sh`), así que ruff/tsc/
pytest no aplican. La verificación es la de arriba, real y medida.

**Abierto**: el `.env` de producción no está respaldado en ningún sitio. Perder
el droplet pierde las claves de API. No se ha tocado: mover secretos es decisión
del dueño.

---

## Fase A — la casa: mudar el sistema al VPS (EN CURSO)

### A.0.2 — puertos atados a loopback

Rama `feat/mudanza-vps`. Único cambio de código de toda la Fase A.

`docker-compose.yml`: `"8011:8000"` → `"127.0.0.1:8011:8000"` y
`"3004:3000"` → `"127.0.0.1:3004:3000"`.

**Por qué**: Docker publica en `0.0.0.0` por defecto y escribe sus propias
reglas de iptables **por delante** del cortafuegos del host. En un portátil tras
el router de casa eso era invisible; en una máquina con IP pública es toda la
superficie. Las otras dos aplicaciones del VPS no publican ni un puerto.

**Checklist, resultado real:**

| # | Comprobación | Resultado |
|---|---|---|
| 1 | Suite backend desde base recreada | **1108 passed**, 0 fallos, 0 saltados |
| 1 | `npx vitest run` | **108 passed** (9 ficheros) |
| 2 | `ruff check app tests` · `npx tsc --noEmit` | limpios los dos |
| 3 | `docker build -f backend/Dockerfile` | compila |
| 4 | Cobertura del código nuevo | **no aplica, y se dice en vez de fingirlo**: el diff no añade ni una línea ejecutable — solo `docker-compose.yml` (18 líneas de comentario + 2 de puertos) |
| 5 | Secretos / endpoints internos en el diff | ninguno |
| 6 | Entradas validadas, sin `print`/`console.log` | no hay código nuevo que validar; sin restos de depuración |

**Verificado por el parser de Docker, no leyendo YAML** — los cuatro servicios
quedan en loopback (`db` y `redis` ya lo estaban antes):

```
backend    host_ip=127.0.0.1  published=8011  target=8000
db         host_ip=127.0.0.1  published=5434  target=5432
frontend   host_ip=127.0.0.1  published=3004  target=3000
redis      host_ip=127.0.0.1  published=6381  target=6379
```

**La regresión que había que descartar, descartada midiendo**: el túnel real del
ROG apunta a `http://127.0.0.1:3004` (`~/.cloudflared/eko-realtors-demo.yml`),
no a la IP de la LAN. El cambio no rompe producción. Lo que sí desaparece es
entrar por la IP de la LAN; `docs/install.md` documenta `localhost`, así que el
contrato publicado no cambia, y la salida está escrita en el propio compose
(un `docker-compose.override.yml` local en la máquina que lo necesite).

### Auditoría del diff — cuatro hallazgos, los cuatro míos

| Hallazgo | Clase | Estado |
|---|---|---|
| `CLAUDE.md:245-247` documentaba tres URLs por IP (`…:8011/docs`, health, `…:3004`) que el cambio convierte en «conexión rechazada». Y **`/docs` da 404 por el túnel** (medido), así que Swagger quedaría alcanzable solo desde una shell en la máquina | 🔴 bloqueante | ✅ corregido: URLs a `localhost` + el túnel SSH que las devuelve |
| **Este repo es un producto instalable.** `scripts/install.sh:257-260` y `docs/install.md:43-46` entregan cuatro URLs que en un VPS ya no se pueden abrir, y el cambio no ofrecía sustituto | 🔴 bloqueante | ✅ corregido: el instalador y el doc dan ahora la línea de túnel SSH |
| **El comentario que escribí describía algo que Compose no hace.** Decía que un `docker-compose.override.yml` plano devuelve el puerto. Medido: sin el tag `!override` Compose conserva la entrada base y el override **no cambia nada** | importante | ✅ corregido con la medición dentro del comentario |
| `.gitignore` no ignoraba `docker-compose.override.yml`, y mi comentario le decía al operador que lo creara. Si se commitea, republica `0.0.0.0` en **todas** las instalaciones al siguiente `git pull` — justo lo que el cambio evita. El propio `.gitignore` ya registra dos incidentes iguales | importante | ✅ ignorado, con el motivo escrito |

### A.0 — preparación del VPS ✅ (nada de producción tocado)

| Paso | Resultado |
|---|---|
| A.0.1 repo en el VPS | Por **bundle + scp**: el VPS no puede clonar de GitHub (`Permission denied (publickey)`) ni alcanzar al ROG por SSH. Es el patrón que este repo ya usa |
| A.0.3 `.env` | Copiado **por tubería, sin imprimirlo**. Verificado por forma: 69 claves, permisos 600, secretos críticos presentes. `OLLAMA_ENABLED=false` para el corte |
| — | `DATABASE_URL`/`REDIS_URL` apuntan a `db:5432` / `redis:` — sus **propios** contenedores, no los del ROG. Comprobado antes de arrancar nada |
| A.0.4 ensayo en vacío | Imágenes compilan · migraciones hasta la **043** · **18 tablas** · health `0.56.0` con `llm_fallback:"off"` · frontend `/login` **200** |
| — | `docker compose down -v`: los dos volúmenes borrados. **Zorros y Black Volt intactos**, sus 9 contenedores siguen corriendo |
| A.0.5 túnel | `eko-realtors-vps` (`d68e4a1d…`) creado, config escrita y **validada por `cloudflared` (OK)**. **NO arrancado y sin DNS**: solo corren los 2 túneles de los otros productos |

**El ensayo se ganó su sitio: encontró un fallo que solo aparece en un clon
limpio.** `a1be1e2` — `frontend/public/` está vacía y git no trackea
directorios vacíos, así que un checkout nuevo no la tiene; el Dockerfile la
copia sin condición. La build **solo funcionaba en la única máquina donde
alguien creó esa carpeta a mano en mayo**. Afecta también a terceros:
`scripts/install.sh` corre `docker compose build`. Arreglado con `mkdir -p` en
la etapa builder, para no servir un `.gitkeep` suelto desde la raíz del sitio.

### A.1 / A.2 / A.3 — CORTE EJECUTADO ✅ 27-ago-2026

**El sistema corre en el VPS.** `inmo-demo.ekoaiautomation.com` → `0.56.0`,
`llm_fallback:"ok"`, `/login` y `/contact` en 200.

| Verificación | Resultado |
|---|---|
| Datos íntegros | **72 mensajes, 38 leads, 4 visitas, 9 conversaciones, 2 orgs** — idénticos a la línea base tomada antes del corte. Alembic en `043` |
| Volúmenes | 64,6 MB y 4 KB en destino, coincidentes con el origen |
| Puertos desde fuera | `162.35.160.169:8011` y `:3004` **rechazados** |
| Webhook de voz sin firma | **403** (sigue armado) |
| Vigilantes | `monitor_state`: `fair_housing \| clean`, `llm_fallback \| ok` |
| Túnel viejo del ROG | `cloudflared-realtors-demo.service` parado y deshabilitado. **El túnel de ventas intacto**: `ekoaiautomation.com`, `app.` y `landing.` los tres en 200 |
| Zorros y Black Volt | intactos, sus 9 contenedores corriendo |

**El respaldo de LLM, por Tailscale.** Puente nuevo en el ROG
(`ollama-bridge-tailnet.service`) atado **solo** a `100.88.47.99` — verificado
que la LAN queda cerrada. El health pasó de `off` a **`ok`**, y esa transición
es la prueba de que funciona.

**El vigía cambió de casa (A.2).** Instalado en el ROG, credencial movida por
tubería (verificada por forma: prefijo `re_`, 36 caracteres), línea base limpia
tomada a mano antes de programarlo, cron `*/15` en el ROG y **quitado del VPS**.
Los otros 6 crons del VPS, intactos.

### Resuelto: quién levantó los contenedores del ROG tras el corte

Aparecieron corriendo otra vez a las `14:18:27Z` según el journal de Docker.
Descarté unidad systemd, timer, cron de root y el propio vigía (sus líneas de
`docker ps` están dentro del cuerpo de un correo, no se ejecutan). **Causa real:
otra sesión de Claude, «PCROG Cleaning», haciendo limpieza del ROG y levantando
servicios.** Avisada por mensaje directo de las dos cosas que no debe tocar: no
levantar `eko-realestate-*` (su base es la foto anterior al corte) y sobre todo
**no arrancar `cloudflared-realtors-demo.service`**, porque sirve el MISMO
hostname que el túnel del VPS y dos conectores repartirían el tráfico entre dos
bases de datos distintas.

**Mitigación, que se queda puesta igualmente** — el ROG lo tocan varias sesiones: en el `.env` del ROG quedan
`SMS_SIMULATED=true`, `EMAIL_SIMULATED=true`, `FOLLOWUPS_ENABLED=false`,
`DELIVERY_RETRY_ENABLED=false`, `ENRICHMENT_ENABLED=false`. Si algo lo resucita,
**no puede enviar nada real** — el riesgo era que sus bucles reenviaran SMS a
leads reales desde la foto vieja. Original en `.env.pre-mudanza-20260827`.

⚠️ **Para revertir hay que deshacer esa mordaza**: `cp .env.pre-mudanza-20260827 .env`
antes de levantar el ROG.

### Reversión (sigue disponible)

Los volúmenes del ROG **no se tocaron**. Volver es: restaurar su `.env`,
`cloudflared tunnel route dns --overwrite-dns eko-realtors-demo inmo-demo…`,
`systemctl enable --now cloudflared-realtors-demo`, y `docker compose up -d`.

### El corte, tal como se ejecutó

Es el paso en que producción cambia de máquina. Requiere autorización expresa.

**Orden**: `down` en el ROG (conserva volúmenes) → copiar
`eko-ai-realestate_postgres-data` (**64,6 MB**) y `_content-media` (**4 KB**)
por tubería → `up -d` en el VPS → repuntar el DNS con `--overwrite-dns` →
arrancar el túnel del VPS → verificar por el dominio público → quitar el
ingress de `inmo-demo` del ROG y reiniciar su `cloudflared` (⚠️ sirve también
los dominios de los productos de ventas: comprobarlos justo después).

**Reversión**: los volúmenes del ROG **no se tocan**. Volver es repuntar el DNS
al túnel viejo y `up -d` allí.

**Ventana**: minutos. Un SMS entrante durante el corte lo reintenta Twilio.

---

## Hallazgo del 27-ago: «el sistema hace las citas» no es cierto hoy

Medido contra producción, no recordado. `CALENDAR_SIMULATED` **no está en el
`.env`**, así que toma el `True` por defecto de `config.py:112`, y el contenedor
vivo lo confirma. En la base: **4 visitas, las 4 con `external_booking_id`
`calcom-sim-…`, cero reales.**

**Qué sí pasa**: la cita queda registrada en `visits` y se ve en el calendario
del panel. **Qué no pasa**: la reserva en Cal.com — sin invitación en el
calendario real de Natalia y sin confirmación de Cal.com al lead. Y las horas
ofrecidas se generan localmente, cruzadas solo contra nuestra propia tabla, así
que el sistema puede ofrecer una hora en la que ella está ocupada de verdad.

Origen probable: nació como demo pública — `deploy/cloudflared/config.example.yml:1,17`
todavía lo llama «PUBLIC DEMO» y exige todos los canales simulados — y el nombre
`inmo-demo` se quedó mientras el sistema pasaba a atender leads reales. Los
demás canales **sí** son reales: `EMAIL_SIMULATED=false`, `SMS_SIMULATED=false`,
`VOICE_SIMULATED=false`.

**Decisión del dueño, y va antes de mandar tráfico al embudo.**

---

## Hallazgos abiertos (no bloquean la Fase A)

| # | Hallazgo | Clase |
|---|---|---|
| 1 | `CALENDAR_SIMULATED=true` en producción — sin reservas reales (arriba) | importante, decisión del dueño |
| 2 | La mitad telefónica del embudo no funciona: VAPI sin configurar, así que el número no lo atiende el asistente. El webhook está sano (403 sin firma, medido) | importante |
| 3 | `LISTINGS_SIMULATED` → `true` por defecto: las propiedades son el conjunto de demo, no MLS. Conocido y fuera de alcance | menor |
| 4 | El VPS **no puede clonar de GitHub** (`Permission denied (publickey)`). Se usará bundle por `scp`, el patrón que este repo ya usa para el ROG. Añadir una llave de despliegue es acción del dueño | menor |
| 5 | `TWILIO_WEBHOOK_URL` y `NEXT_PUBLIC_CANONICAL_URL` llevan `inmo-demo` dentro. Si en la Fase B se retira ese nombre, el primero hay que cambiarlo **en la consola de Twilio** o los SMS entrantes dejan de llegar | importante |
| 6 | Black Volt en el ROG: contenedores vivos con el backend en bucle de reinicio, y la **misma huella de túnel en las dos máquinas** — si alguien arranca el del ROG, Cloudflare repartiría tráfico entre dos bases de datos. Es otro producto: solo con autorización expresa | importante |

## Decisiones tomadas y por qué

- **Puertos a loopback y no configurables.** Un ajuste que permita `0.0.0.0` es
  un ajuste que alguien pondrá en `0.0.0.0`. La salida documentada es un
  override local en la máquina concreta: deliberado, y no viaja con un `git pull`.
- **Túnel nuevo, no reutilizar `eko-realtors-demo`.** Dos conectores del mismo
  túnel hacen que Cloudflare reparta entre dos bases de datos. Es la mina que ya
  quedó armada en Black Volt.
- **`OLLAMA_ENABLED=false` en el VPS desde el primer minuto.** Copiar el `.env`
  tal cual haría que el monitor mandase avisos falsos desde el primer tick.

## Decisiones del dueño, 27-ago

- **Las citas se reservan de verdad en Cal.com.** Hace falta cuenta, clave, tipo
  de evento y `booking_contact_email` en Ajustes (hoy vacío).
- **El tercer respaldo de LLM se alcanza por Tailscale** (puente atado SOLO a la
  interfaz de la tailnet). Se enciende **después** del corte: el health pasando
  de `off` a `ok` es la prueba de que el puente funciona.
- **El embudo arranca solo con formulario.** El número no se anuncia en la web.
- **La landing sale del proyecto de Claude Design** «Natalia landing page
  mockups», fichero `Natalia Robbie Landing v4.dc.html`. Se conserva el
  formulario existente con su honeypot, captcha y consentimiento TCPA.

## Siguiente paso concreto

**Dos clics del dueño** (sección «Dominio y teléfono» arriba): apagar DNSSEC en
GoDaddy, y crear el TwiML Bin en Twilio. Ninguno de los dos se puede hacer por
API — está medido, no supuesto. Todo lo demás de esa fase lo ejecuto yo.

---

# ✅ v0.60.0 EN PRODUCCIÓN (27-ago-2026)

Desplegada y verificada por el dominio público: `/api/v1/health` → `0.60.0`,
migración `043` → **`044_message_internal`**, las 76 filas previas de `messages`
en `internal=false` y ninguna nula. Una cita real de prueba dejó las **dos**
filas (cliente + nota interna) con `external_id` reales y distintos de Resend, y
`internal AND external_id IS NULL` → 0. Datos de prueba borrados: 76 mensajes,
38 leads, 4 visitas — idénticos a antes. `zorros-*` y `blackvolt-*` intactos.

**Error mío en esa verificación, anotado para no repetirlo:** la prueba mandó
una segunda invitación a la dirección de Natalia, porque la copia de la agencia
sale a `booking_contact_email` aunque el lead lleve otro correo. La próxima
verificación de punta a punta reapunta ese campo antes, o se avisa primero.

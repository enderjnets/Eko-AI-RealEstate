# PROJECT STATUS

Estado de ejecución del plan `~/.claude/plans/si-haz-el-plan-jazzy-sifakis.md`
(**el embudo Denver Home Story**). Es un estado, no un diario: el historial de
v0.56.0 y anteriores vive en git y en el plan.

---

## 🔴 PENDIENTES ANTES DE ENCENDER LA PRODUCCIÓN DE VÍDEOS (30-ago-2026)

Nada de esto se enciende hasta que las cuatro estén hechas. Orden por lo que
desbloquea, no por esfuerzo.

| # | Qué | De quién | Estado |
|---|---|---|---|
| 1 | Línea de brokerage en Ajustes | dueño | ✅ **hecho** — `Engel & Völkers Aspen`, verificado en la base de producción |
| 2 | La voz del canal | dueño | ✅ **hecho** — `English_CalmWoman` a 1,06 con emoción, elegida entre cuatro variantes |
| 3 | Música de fondo | dueño | ✅ **hecho** — 4 pistas de Pixabay, licencia verificada, instaladas y recomprimidas |
| 4 | **Completar los perfiles de los tres canales** | dueño | 🔴 **PENDIENTE — bloquea el encendido** |
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

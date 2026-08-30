# CHANGELOG

All notable changes to **Eko AI Realtors**.

## [0.67.0] — 2026-08-30

### Añadido — el carril B: guion → vídeo narrado

- El borrador generado gana `scenes` (4-6 planos con `visual_prompt` y
  `on_screen_text`) y `narration` — migración **048**. **El vídeo se construye
  ANTES de la aprobación**: lo que una persona aprueba es el vídeo, no una
  descripción de él.
- **Fair Housing se aplica también a la imagen**: cada `visual_prompt` pasa el
  filtro de frases Y una denylist de descriptores de personas
  (`fair_housing.picture_violations`). Un fotograma lleno de un solo tipo de
  hogar dice quién es bienvenido sin una sola frase que nadie pueda editar.
- `services/lang_guard.py`: guarda de idioma **sobre el texto NARRADO**, no
  sobre el titular, y caza también la MEZCLA — que es lo que un modelo produce
  de verdad cuando sus instrucciones y su contexto no coinciden.
- Obrero: narración por MiniMax T2A (edge-tts de respaldo), imágenes por Kling
  → Pexels → tarjeta de marca, planos **cortados a la voz** con los tiempos de
  Whisper, y `worker/spoken.py` que convierte cifras en palabras («$450,000» →
  «four hundred and fifty thousand dollars»). Caché de imagen **en el punto de
  pago** y tope diario propio: ese paquete de Kling es un saldo compartido con
  otros dos proyectos.
- La declaración «Contains AI-generated visuals» va en el caption de las piezas
  generadas y **solo** en ellas: un clip que alguien filmó no es generado.

### Corregido — hallazgos de la auditoría de v0.66.0

- 🔴 **La música cortaba la narración por la mitad.** El comando emitía un
  SEGUNDO `-filter_complex`; ffmpeg se queda con el último, así que el grafo de
  vídeo desaparecía y `[0:a]` se consumía dos veces. Medido: vídeo de 6 s con
  audio de 2,5 / 3,5 / 3,0 s en ejecuciones sucesivas del mismo comando, con
  código de salida 0. Ahora es un solo grafo con `asplit`. El test que existía
  comprobaba una subcadena y no podía verlo; el nuevo renderiza y mide.
- 🔴 **Un obrero rezagado podía pisar un vídeo ya publicado** y borrar el
  fichero aprobado. `/result` y `/fail` exigen ahora que el trabajo esté
  reclamado y la pieza siga esperando vídeo — y se comprueba ANTES de gastar la
  subida.
- Un resultado ya no mete en la cola de aprobación una pieza con hallazgos
  pendientes (era una segunda puerta que se saltaba el filtro de la primera).
- Modelo de voz **por idioma**: `small.en` era inglés puro en un producto
  bilingüe.
- Los errores de ffmpeg llegaban VACÍOS a la persona: se leía `stdout` con los
  errores en `stderr`.
- Un trabajo FALLIDO ya no es una condena perpetua para el clip: se reintenta
  pasadas 24 h, así que un disco lleno una tarde no lo mata para siempre.
- Nada queda en el volumen cuando la entrega se rechaza.
- **Los tests del obrero no corrían en CI** — `testpaths` apuntaba solo a
  `backend/tests`.
- 🔴 **`violations=None` se guardaba como JSON `null`, no como SQL NULL**, así
  que `IS NULL` no casaba nunca y el barrido del carril B no encontraba trabajo.
  `message.py` ya llevaba `none_as_null=True`; el modelo de contenido no lo
  había heredado. La 048 normaliza las filas existentes.

## [0.66.0] — 2026-08-30

### Añadido — el obrero de render y los subtítulos

- Migración **046** `render_jobs` (RLS default-deny) y **047**
  `monitor_state.last_heartbeat_at`. El carril A deja de renderizar en el
  contenedor de la API y **encola** el trabajo para la máquina que tiene el
  equipo de vídeo; el camino local se conserva como respaldo
  (`RENDER_WORKER_ENABLED=false`), no es código muerto.
- `worker/`: paquete propio, sin importar nada de `backend/`. **Tira, nadie le
  empuja** — ningún puerto se abre en la máquina de render. Subtítulos con
  faster-whisper en **CPU** (la GPU de esa máquina es de otro proyecto),
  ensamblado 9:16 sin recorte, marca arriba a la derecha, brokerage y dominio
  quemados al final, y **verificación mirando un fotograma**: el vídeo se
  correlaciona contra la marca que debía llevar, porque en el proyecto vecino
  salió uno con la marca de otra empresa pasando todas las puertas.
- Router `/api/v1/internal/render-jobs` con token propio. **Token vacío = 503**,
  nunca abierto. El guard va en el constructor del router: FastAPI copia esa
  lista al registrar cada ruta, así que asignarla después no protege nada.
- Vigía del obrero: avisa **por cambio** y solo cuando hay trabajo esperando —
  un obrero ocioso con la cola vacía no es una avería.

### Corregido — hallazgos de la auditoría de v0.65.0

- 🔴 **Una pausa por cuota dejaba plataformas sin publicar para siempre.** El
  conjunto de «ya hechas» incluía las filas `PENDING`, así que la plataforma que
  un 429 liberaba se saltaba en cada tick siguiente y la pieza se quedaba en
  `PUBLISHING` sin nadie que la rescatara. Ahora `PENDING` es trabajo pendiente
  y su fila se reutiliza.
- **Una pieza fallada y vuelta a aprobar no podía publicarse nunca.** La
  segunda aprobación de una persona tiene que significar algo: las filas
  `FAILED` del intento anterior se liberan al empezar un episodio nuevo.
- 🔴 **Cualquier organización publicaba en los canales de la primera.**
  `BUFFER_CHANNEL_*` es un solo juego de ids para toda la instalación y el
  barrido corre para TODAS las organizaciones — y producción tiene dos (la real
  y una «Demo» en trial). Sin esto, una pieza aprobada en la demo se publicaba
  en los canales de Denver Home Story. `CONTENT_PUBLISH_ORG_ID` dice de quién
  son; sin él, con más de una organización, no se publica nada.
- El test de la pausa por cuota **no podía fallar**: comprobaba el estado
  intermedio y nunca el siguiente tick.

## [0.65.0] — 2026-08-30

### Añadido — la publicación a los canales (Buffer)

- `services/buffer_publisher.py`: una pieza APROBADA se publica en YouTube,
  TikTok e Instagram por Buffer. **Reclamar-luego-registrar por PUBLICACIÓN**:
  la fila de `content_publications` se escribe y se confirma ANTES de la
  llamada, así que una caída no puede confundirse con «nunca se intentó» y
  convertirse en un segundo post público. Una fila atascada en `PUBLISHING` no
  se reintenta sola: aflora en la consola para una persona.
- **La puerta se consulta al publicar, no al aprobar**: `ensure_publishable`
  relee la pieza bajo bloqueo (estado, línea de brokerage, filtro Fair Housing).
  `test_content_gate_is_absolute.py` ahora lo verifica por AST — la promesa que
  ese fichero llevaba escrita desde v0.52 y no podía cumplir sin un publicador.
- **Guarda de organización**: antes de publicar nada, el sistema pregunta a
  Buffer qué canales tiene la organización configurada y se niega si los ids no
  son suyos. Es el fallo exacto que publicó un vídeo en el canal de otra marca
  en el proyecto vecino.
- Ruta pública `GET /api/v1/public/content/{id}/media`: dirección **estable**
  (Buffer descarga al publicar y rechaza URLs firmadas o caducables) cuya puerta
  es el **estado** de la pieza. Un borrador, una pieza rechazada y una
  inexistente devuelven el mismo 404. Responde peticiones `Range`.
- `_content_publish_loop` + ajustes `BUFFER_*` y `CONTENT_PUBLISH_*`, todos
  apagados y simulados por defecto. `scripts/buffer_channels.py` lista los ids
  de canal sin imprimir el token.

### Corregido

- `BodySizeLimit` respondía `http.disconnect` a la segunda lectura del cuerpo, y
  Starlette escucha ahí la desconexión de **toda** respuesta en streaming: el
  resultado eran cabeceras correctas con **cero bytes**. Ahora delega en el
  servidor, que es quien sabe si el cliente se fue.

## [0.64.2] — 2026-08-28

### Corregido

- El zoom del parallax (1,154×) más el recorte centrado de `object-cover` se
  comían ~17 % de la parte alta del retrato del equipo — la frente de Robbie.
  El encuadre ancla ahora en `50% 12%` y el parallax baja a 0,10.

## [0.64.1] — 2026-08-28

### Añadido — el motor de efectos del diseño v4

- Portado el motor de `deploy-v4` de Claude Design (coreografía de scroll por
  atributos `data-*`): la casa del héroe sube y escala con el scroll y su vídeo
  se frota los primeros 30 % y luego corre libre; reveals con stagger; drift de
  títulos; parallax del retrato y del panel; carril de mercados arrastrable.
- `prefers-reduced-motion` deja la página estática correcta. NO se portó el
  truco de mesas de trabajo fijas del diseño (la página es responsive real) ni
  su CTA telefónico: el formulario real sigue siendo el punto de conversión.
- Vídeo del héroe comprimido a 4,8 MB con keyframes densos (el frotado fija
  `currentTime` constantemente).

## [0.64.0] — 2026-08-28

### Añadido — la landing de Denver Home Story

- La página pública pasa al diseño v4: héroe cinematográfico con vídeo/poster,
  sección «nosotros dos» con retrato, «cómo trabajamos», tres mercados y el
  formulario de consulta sobre panel oscuro. Cormorant Garamond auto-hospedada.
- **El formulario avisa a la agencia**: cada captura real manda un correo a
  `booking_contact_email` con nombre, teléfono, email, mensaje y atribución,
  registrado en el hilo como nota interna. Un duplicado no avisa dos veces y
  un fallo del aviso jamás rompe la captura.
- **Pausa de citas automáticas** (`BOOKING_OFFERS_PAUSED`): mientras las citas
  se cuadran en persona, el chat no ofrece huecos (instrucción de callback en
  su lugar) y las herramientas de voz prometen la llamada. El panel manual no
  cambia. Tres mutaciones verificadas en rojo.
- El formulario exige email también en el navegador y el 422 `email_required`
  tiene mensaje propio; el subtexto promete lo que el embudo cumple.

## [0.63.1] — 2026-08-28

### Corregido — antes de encender el calendario real

- **El idioma del asistente de Cal.com**: las confirmaciones y recordatorios al
  cliente iban cableados en español, contra la norma de que los clientes van en
  inglés.
- **Abrir la página ya no puede vaciar la oferta**: aprovisionar crea una agenda
  deliberadamente vacía, y una fila activa desde el nacimiento haría que el
  asistente prefiriera ese calendario vacío al de la agencia — cero horas
  ofrecidas porque alguien miró una página. Las filas nacen apagadas; **guardar
  horas es el interruptor**, y vaciarlas todas lo apaga.

## [0.63.0] — 2026-08-28

### Añadido — «Mi disponibilidad»: cada agente declara su horario

Hasta ahora el producto **no tenía forma de decir cuándo puede trabajar una
persona**, y no era una función que faltara sino un sustantivo: nada en el
esquema pertenecía a un agente, así que «la disponibilidad de Natalia» no se
podía ni escribir. Las horas que el asistente ofrecía salían de una lista fija
—10, 11, 14, 15 y 16— que nadie había elegido.

- **Página nueva, Disponibilidad.** Cada usuario entra con su Google y fija sus
  franjas por día y por **tipo de cita**: visita a propiedad, valoración de
  vivienda, llamada de consulta y jornada de puertas abiertas, cada uno con su
  duración y su margen de desplazamiento.
- **El asistente cita ese horario en los DOS carriles**, voz y mensaje. Convertir
  solo uno habría dejado al teléfono ofreciendo las horas reales del agente y al
  chat las de la agencia — dos respuestas distintas a la misma pregunta.
- **Quien quiere vender reserva una valoración**, no una visita de comprador.
- Cada cita registra **de qué tipo es y de quién es**, que es lo que permitirá
  que entre un segundo agente sin que se ofrezcan las horas del otro.

**Seguridad:** el correo del agente sale del token de sesión y de ningún otro
sitio — no hay parámetro ni campo donde nombrar a otra persona. La contraseña
compartida de oficina, que da acceso sin identidad, queda fuera de estas
páginas.

**Límite conocido, dicho en voz alta:** con una sola cuenta de Cal.com los
conflictos se leen de los calendarios conectados a esa cuenta. Mientras reserve
un solo agente no se nota; el día que reserve un segundo hará falta Cal.com de
pago.

## [0.62.0] — 2026-08-27

### Corregido — la cancelación no salía de nuestra base de datos

- **`cancel_visit` no avisaba a nadie.** `send_visit_invitation(cancelled=True)`
  y el `METHOD:CANCEL` de `icalendar.py` estaban escritos, comentados y **sin
  llamador**: los dos únicos usos eran reservas. La cita seguía en pie en el
  calendario del cliente y en el del agente.
- Y el flag **no estaba completo por dentro**: solo llegaba al `.ics` y al
  `method=` del MIME, así que el correo habría dicho *«Your visit is
  confirmed»* con un adjunto que la cancela. Textos de cancelación EN/ES.
- **`SEQUENCE`**: `build_visit_ics` lo aceptaba y nadie lo pasaba. Un CANCEL con
  `SEQUENCE:0` **puede ignorarse** (RFC 5546) y Outlook lo ignora.
- El aviso sale **después** del commit y su fallo **no** revierte la
  cancelación. `local_only` también avisa: significa «no llames al proveedor»,
  que es cuando más importa que lo sepa una persona.

### Corregido — el expediente de una llamada y el nombre de la cita

- `get_conversation_for_lead` no desempataba por `id`. Una llamada escribe su
  transcripción entera al colgar: **27 filas sobre 2 marcas de tiempo**, y
  Postgres las devolvía en cualquier orden.
- La cita lleva ya el nombre que dijo quien llamó (`visit.title`). `lead.name`
  **no** se toca: un nombre corregido a mano no lo pisa una transcripción.

## [0.61.0] — 2026-08-27

### Cambiado — la plataforma deja de asomar por las superficies del cliente

Regla del dueño: **Eko AI Realtors es la plataforma DETRÁS de
`denverhomestory.com`; su público no debe verla.**

- **La asistente telefónica es ahora «Clara»**, de Natalia y Robbie en Denver
  Home Story. Y si le preguntan qué es, **dice que es una IA sin evasivas**:
  hoy ninguna ley de Colorado lo exige (la SB 24-205 nunca entró en vigor; su
  sustituta llega el 1-ene-2027), pero quien reserva una visita creyendo hablar
  con una persona y luego se entera, reclama al broker con licencia.
- **`/about` sale del dominio de marca.** Esa página vende *esta plataforma* a
  inmobiliarias; servírsela a un vendedor de casa llegado de un vídeo era la
  peor página disponible ahí. Estaba en `PUBLIC_PATHS`.
- **El nombre de pantalla de inicio.** Los metadatos de Next se *mezclan*, no se
  reemplazan: la landing heredaba «Eko AI Realtors» del layout raíz.

### Corregido — dos trampas que muerden al configurar los dominios

- Un `Host` acabado en punto (`www.denverhomestory.com.`) es el **mismo nombre**
  para DNS y otra cadena para `===`: caía por todas las comparaciones y servía
  el panel interno bajo el dominio de marca. Normalizado en ambos lados.
- `BRAND_URL == PANEL_URL` producía **redirección infinita**. Ahora se trata
  como «sin configurar». La guarda deja además de comprobar las URLs:
  `hostOf("") === ""`, así que esas cláusulas eran código muerto con forma de
  comprobación.

## [0.60.0] — 2026-08-27

### Añadido — el expediente de la cita, y la atribución que ya se guardaba

- **La invitación de la cita entra en la conversación del lead.** Hasta ahora
  `visit_invite.py` llamaba a `send_email` directo: el correo comercialmente
  más importante del embudo no dejaba rastro en el panel.
- La copia que recibe la agencia se guarda como **nota interna**
  (`messages.internal`, migración 044). Está en el hilo del lead porque es su
  expediente, pero **nunca fue un mensaje para él**, y por eso la excluyen
  cuatro sitios: el barrido de reenvío (`delivery.py::_still_owed` — sin ese
  filtro, la nota con el nombre y el teléfono del propio lead le habría sido
  **entregada a él**), los dos constructores de historia del LLM, y el Inbox.
- **La regla del Inbox era la más sutil**: `reached_somebody()` decidía «quién
  habló el último». La nota interna alcanzaba a la agencia, no al lead, así que
  un lead con una pregunta sin responder salía del triaje **en silencio** al
  agendarle una visita. Peor en el lead solo-teléfono, donde esa nota es la
  única fila que se escribe.
- **El registro reutiliza el hilo ACTIVO más reciente del lead**, no crea uno
  de email. Crearlo lo convertía en «primario» (nace con `last_at` = ahora): el
  composer del panel saltaba a email para un lead que solo tiene teléfono
  —todo envío moría con `channel_identifier_mismatch`— y las sugerencias
  devolvían `empty_conversation`. Solo se crea el hilo de email si el lead no
  tiene ninguno Y tiene dirección; sin hilo y sin email, se omite con log.
- **El registro corre en su propia sesión de base de datos.** Un `rollback`
  sobre la sesión del llamador expira todos sus objetos, y el handler de
  reserva lee `visit` justo después: habría devuelto un **500 sobre una cita ya
  comiteada y con los correos ya enviados**, que es justo lo que el módulo
  promete que no puede pasar.
- **La atribución se puede leer por fin.** `utm_*`, `gclid`, `fbclid`,
  `landing_variant`, `tier` y `referrer` se capturan desde que existe la
  landing y no los devolvía ninguna API. Ahora salen en el lead, **filtrados
  por la misma lista blanca que los escribe** (importada, no copiada): `meta`
  lleva también enriquecimiento, marcadores internos y el `captured_at` del
  propio escritor, y volcarlo entero sería mandar a la interfaz un JSON libre
  de la base.
- Se devuelve el **primer toque**, que es el que `_record_attribution` se niega
  a sobrescribir a propósito: la pregunta es qué contenido encontró a esta
  persona, y acreditar el último envío acreditaría siempre al anuncio de
  retargeting. Los toques posteriores siguen guardados en
  `meta["attribution_later"]` y **no** se exponen todavía.
- 🔴 **Corregido antes de salir, y el fallo era mío**: la primera versión leía
  el primer nivel de `meta` cuando el escritor anida bajo `meta["attribution"]`,
  así que devolvía vacío **para todo lead real** — y sus tests fabricaban a mano
  la forma plana, de modo que pasaban contra un camino que no podía funcionar.
  Ahora todo test que toca la forma almacenada pasa por `capture_lead`.
- Siete mutaciones verificadas, una por guard.

## [0.59.0] — 2026-08-27

### Cambiado — la rotación de temas apunta al vendedor, y el pie lleva a la web

- **Medido, y el plan tenía mal el número**: no eran «10 de comprador contra 5
  de vendedor». `content_topics.py` tenía **7 temas: 6 de comprador y 1 de
  vendedor** (`first_week_selling`). Peor de lo que estaba escrito.
- `Topic` gana el campo **`audience`** (`seller` / `buyer` / `both`). Declarado
  y no deducido del brief: el equilibrio de la rotación es una decisión de
  negocio, y una decisión que solo vive en prosa no se puede probar.
- **Cinco temas de vendedor nuevos**: qué decide el valor de una casa hoy, qué
  arreglar antes de listar, lo que cuesta vender de verdad, por qué el precio
  alto sale caro, y vender y comprar a la vez. **Tres reencuadrados a `both`**
  —inspección, oferta→cierre y pulso de mercado— porque quien vende vive esos
  tres momentos igual que quien compra y el brief solo miraba a un lado.
- Reparto resultante: **6 vendedor, 3 los dos, 3 comprador** (9 de 12 alcanzan
  a quien vende). No se borró ningún tema de comprador: traen alcance, y un
  vendedor en Denver casi siempre compra después.
- **Llamada a la acción** `CONTENT_CTA_URL`, vacía por defecto. Se añade al pie
  **antes** de `find_violations`, no después: lo que se publica tiene que haber
  pasado por el filtro Fair Housing — publicar texto que la puerta no leyó es
  la forma exacta del defecto que se corrigió en v0.56.0. El texto del enlace
  no lo escribe el LLM: un modelo al que se le pide reproducir una URL acaba
  dejándose un carácter, y un enlace roto en un vídeo que costó cuota es una
  pérdida total silenciosa.
- Mutaciones verificadas: pasar tres temas de vendedor a comprador pone en rojo
  el test del equilibrio; quitar la CTA de antes del filtro pone en rojo el test
  que comprueba que la puerta ve el pie publicado. Una cada uno, la correcta.

## [0.58.1] — 2026-08-27

### Corregido — el idioma por defecto de una agencia nueva estaba al revés

- `models/agent_settings.py` creaba toda fila nueva con
  `languages = ["es", "en"]`. El campo es **ordenado**: `languages[0]` es el
  idioma en que se escribe a un lead que **nunca nos ha escrito** — justo el
  caso de una cita agendada desde el formulario o por teléfono, donde la
  invitación sale antes de que nadie teclee una palabra.
- **No afectaba a la agencia viva**, cuya fila se puso a mano con
  `["en", "es"]`, y por eso el defecto podía quedarse ahí: solo alcanza a una
  organización creada después, y este producto se vende multi-tenant. Los dos
  sitios que crean la fila lo hacen con un `AgentSettings()` desnudo
  (`api/v1/settings.py:144` y `scripts/seed_demo.py:216`), así que se llevaban
  el defecto entero.
- Contradecía además al resto del código: `conversation.py` cae a
  `["en", "es"]`, `followups.py` a `["en"]`, y `services/i18n.py` documenta
  *"en (English, the DEFAULT)"*. El modelo era el único que decía lo contrario.
- **Sin migración y sin riesgo para los datos vivos**: la columna no tiene
  `server_default` (baseline de la fase 1), y un default de SQLAlchemy solo
  actúa al INSERTAR — ninguna fila existente se reescribe.
- Tests nuevos que fijan el **comportamiento**, no el literal: una agencia
  recién creada arranca en inglés, y un lead que nunca escribió se responde en
  inglés. Mutación verificada: devolver el default a `["es", "en"]` pone los
  **dos** en rojo.

## [0.58.0] — 2026-08-27

### Añadido — invitaciones de calendario (.ics), y las citas dejan de ser mentira

- Medido en producción: **las 4 visitas llevan `external_booking_id`
  `calcom-sim-…`**. `CALENDAR_SIMULATED` está en true, así que `create_booking`
  inventa un id y no reserva nada. El panel mostraba la cita y el asistente de
  voz se lo decía al que llamaba **en voz alta**.
- `services/icalendar.py` construye el VEVENT a mano. Las cuatro cosas que
  fallan en un `.ics` y ninguna falla ruidosamente: **CRLF** (Outlook y Apple
  rechazan el fichero sin él), **plegado a 75 OCTETOS** sin partir un carácter
  multibyte, **escapado** (una coma sin escapar corta la dirección), y **UTC de
  verdad** — un naive se **rechaza** en vez de suponerlo, que es el fallo de
  seis horas que este repo ya pagó.
- Se envía al lead y a la agencia, con adjunto `text/calendar; method=REQUEST`.
  La copia de la agencia lleva **quién, teléfono, correo y qué pidió**.
- El camino del lead **consulta la baja** (`may_send_automated`): lo cazó el
  barrido AST del repo, y tenía razón — una invitación a un lead es un mensaje
  a un lead. La copia interna a la agencia no pasa por ahí porque no lo es.
- Nunca rompe una reserva: la visita es el hecho, la invitación es el aviso.

### Cambiado — el formulario público exige email mientras el SMS esté caído

- Twilio acepta el SMS (201) y la operadora lo tira: **error 30034**, el número
  no está registrado en A2P 10DLC. Un lead que solo deja teléfono no es
  alcanzable por ningún canal automático. `CAPTURE_REQUIRE_EMAIL` (ajuste, no
  constante) lo exige; vuelve a false cuando el SMS entregue.

## [0.57.0] — 2026-08-27

### Añadido — copias de seguridad, que no existían

- Ni el ROG antes ni el VPS después tenían copia de la base de datos. Timeshift
  **nunca** cubrió los volúmenes de Docker: `/var/lib/docker/*` es una regla
  **built-in** del `exclude.list` de cada snapshot que `timeshift.json` no puede
  anular. 38 leads y 72 mensajes de clientes reales, sin una sola copia.
- `deploy/backup-db.sh` (VPS, 04:15 UTC) y `deploy/backup-pull.sh` (ROG, 04:45).
  **El ROG tira, el VPS no empuja**: un push exigiría credenciales en el VPS
  capaces de borrar el propio almacén de copias.
- Dos guardas antes de rotar, verificadas por separado. Y el hallazgo dentro del
  hallazgo: restaurar en un clúster limpio daba **36 errores, todos
  `role "eko_app" does not exist`** — el dump lleva las 49 entradas POLICY/ACL
  pero `pg_dump` es de base y los roles son de clúster. Sin ellos la
  restauración devuelve todas las filas y **ninguna seguridad**, con
  `pg_restore` saliendo con código 0. Se dumpean también los roles.

### Añadido — la sección de mercados de la página pública

- Las tres tarjetas con foto (Aspen y Snowmass, Roaring Fork Valley, Denver
  Metro): la única parte del diseño v4 que nunca se construyó. Imágenes servidas
  desde `public/landing/`, no desde la CDN de la herramienta de diseño.

### Cambiado — la credencial de envío ya no es la que valida las firmas

- `TWILIO_AUTH_TOKEN` autenticaba lo que enviamos **y** validaba la firma de lo
  que recibimos. Una fuga entregaba las dos cosas y rotarlo rompía las dos
  mitades. Ahora el envío usa una API Key (`TWILIO_API_KEY_SID` +
  `TWILIO_API_KEY_SECRET`) y el auth token se queda **solo** para la firma, que
  es lo único que Twilio no permite hacer de otra forma. Con las dos vacías no
  cambia nada.

### Añadido — enrutado por nombre de host, inerte hasta que exista el dominio

- `middleware.ts` + canónicas + `robots: index:false` por defecto, para que
  `www.denverhomestory.com` sirva la marca y `realtors.ekoaiautomation.com` el
  panel. **No es un `robots.txt`**: Cloudflare antepone su `Allow: /` y Google
  se queda con la regla menos restrictiva.
- Todo desactivado mientras `NEXT_PUBLIC_BRAND_URL`/`PANEL_URL` estén vacías.

### Corregido

- `.gitignore` ignoraba los secretos **por nombre**; los respaldos de `.env`
  vuelven siempre con otro nombre. Ahora por forma (`.env.*` + `!.env.example`).
  Nunca se commiteó un valor real, verificado en los 8 commits que tocan la
  cadena.

## [0.56.0] — 2026-08-26

### Añadido — el filtro Fair Housing llega al carril que habla con leads

- `find_violations` no se llamaba en **ningún** punto del camino que responde a
  leads reales: sus tres consumidores eran del carril de vídeo. Ahora corre
  sobre el texto final que sale por SMS, email y WhatsApp — **después** del pie
  de broker, que se reproduce verbatim por obligación legal y era por donde una
  frase prohibida entraría sin que nadie la mirase.
- **Registra y avisa, no bloquea** (decisión del dueño): el lead recibe su
  respuesta sin retraso y sin una segunda llamada al LLM en el camino caliente.
- **Su techo, dicho por escrito**: caza frases literales, no paráfrasis. Medido
  contra el módulo real: `"It's a safe neighborhood with good schools"` → 2
  hallazgos; `"You'll love how safe this area feels for raising kids"` → **0**.
  Es un suelo, no un techo, y el comentario del código lo dice con el
  contraejemplo delante.
- Vigilante propio (`fair_housing_watch`) con ventana rodante de 24 h, no día
  natural UTC: un corte a medianoche daba por comunicada una avería no entregada
  y abría una ventana muda hasta el primer tick del día siguiente.

### Corregido — una zona horaria pegada archivaba las citas seis horas antes

- `" America/Denver"` con un espacio delante guardaba una visita de las 10:00 a
  las 04:00 hora de Denver, respondía **201** y dejaba la cadena mala al lado.
- **Cuatro sitios, no uno.** El primer barrido buscó la forma del `except` que
  yo acababa de escribir en vez de la pregunta que importaba, y encontró uno.
  Los otros tres estaban escritos distinto: el asistente telefónico, el GET de
  huecos libres y el carril de texto que ofrece horas a un lead por SMS.
- **`ZoneInfo` lanza tres familias de excepción**, no dos. El primer guard cogía
  dos, así que una zona de 300 caracteres —que siempre había sido un 422 limpio
  de `max_length`— pasaba a **500**. Ese conocimiento vive ahora en un módulo
  que comparten sus llamadores. (Una auditoría contó **cinco**, no cuatro:
  `conversation.py:_office_hours_note` seguía con su `ZoneInfo` a mano. Su
  comportamiento ya era correcto; la cifra de esta frase no lo era.)
- Con la zona de la agencia inservible **no se ofrecen horas**, en vez de
  ofrecerlas en UTC: una hora equivocada es peor que ninguna.

### Corregido — el aviso de tamaño llega antes de gastar la subida

- **`CONTENT_UPLOAD_MAX_MB` baja de 500 a 95**, en `config.py`, `.env.example` y
  `docker-compose.yml` a la vez. El túnel se rinde sobre los 100 MB, así que un
  tope de 500 era una promesa que la infraestructura no cumplía. 95 y no 99
  porque ~100 es donde se **observó** que rompe, no una cifra documentada: un
  tope al borde de un acantilado medido falla de forma intermitente en vez de
  limpia. El coste es real y va dicho: un clip de 96 MB que ayer pasaba, hoy se
  rechaza.

- **El navegador mira `file.size` antes de abrir la petición**, y la página dice
  el tope antes de que se elija el fichero. Antes no lo miraba en ninguna parte.

- **Qué capa responde, corregido tras una auditoría.** El primer intento afirmó
  que al bajar el tope respondería la ruta con su mensaje. No: cualquier cliente
  que declare `Content-Length` —toda subida de navegador— lo corta el middleware
  `BodySizeLimit` de `main.py`, y el mensaje de la ruta sigue siendo
  inalcanzable para él. El 413 del middleware lleva ahora `limit_mb`, y el panel
  lo convierte en la misma frase traducida que el aviso del cliente, en vez del
  token interno `body_too_large`. La comprobación de la ruta **no** sobra: es la
  única guarda contra un cuerpo troceado que no declara longitud.

- **Deuda anotada, no arreglada:** un clip de 4K de más de 95 MB sigue sin poder
  subirse. La salida real es subida por trozos, y es otra versión.

## [0.55.1] — 2026-08-26

### Corregido — el tamaño de subida que anunciábamos no era el real

- **Decíamos «hasta 500 MB» y el límite real es ~100 MB.** `CONTENT_UPLOAD_MAX_MB`
  vale 500 y el backend lo respeta, pero el panel se sirve por un túnel de
  Cloudflare que corta el cuerpo de la petición **en el borde**, antes de que
  llegue a nosotros. Medido contra producción el 26-ago-2026:

  ```
   99 MB -> HTTP 401  (respondió nuestro backend: pasó)
  120 MB -> HTTP 413  (respondió Cloudflare: cortado)
  ```

  Lo detectó una auditoría como sospecha («verifícalo contra tu plan, no lo leí
  de una fuente») y se comprobó midiendo. Corregido en las notas de v0.52.0 y
  v0.55.0, que es donde la cifra estaba publicada al cliente.

- **Pendiente cuando se escribió esto, resuelto después** (ver «No publicado»):
  el navegador no comprobaba el tamaño antes de subir, así que un clip de 4K
  subía ~100 MB para recibir una página HTML en vez de una frase.

## [0.55.0] — 2026-08-26

### Añadido — el Estudio de Contenido deja de estar escondido

- **Página `/content` propia y entrada «Contenido» en el menú**, también en el
  tab-bar del móvil: el clip se graba y se sube desde un teléfono. Antes la cola
  vivía al fondo de «Hoy», bajo la consola de llamadas — construida, funcionando
  y en la práctica invisible.
- **Subida de clips desde el móvil con barra de progreso.** `XMLHttpRequest` y
  no `fetch`, porque `fetch` no puede reportar progreso de subida en ningún
  navegador y un vídeo de cientos de MB sin progreso parece una página colgada.
  Cuerpo crudo en streaming a disco. Que los bytes llegan intactos lo ata
  `test_upload_stores_the_clip_and_serves_it_back`, que compara el fichero
  servido con el subido. **Límite real: ~100 MB**, no los 500 que el ajuste valía entonces (95 desde la 0.56.0) de
  `CONTENT_UPLOAD_MAX_MB` — ver v0.55.1.
- **`GET /api/v1/content/status`**: booleanos y conteos, sin valores de
  configuración. El vacío pasa a decir POR QUÉ está vacío, y una pestaña vacía
  en un estudio con trabajo señala dónde está ese trabajo en vez de culpar a la
  configuración.
- **`render_error` visible por fin.** El render lo escribía desde la v0.52 y
  ninguna ruta lo devolvía. Las palabras de ffmpeg se quedan en el log: la
  tarjeta muestra un mensaje escrito para una persona.

### Corregido

- **`brokerage_line` no tenía puerta de entrada.** El campo existía en el modelo
  y dos puertas lo exigían, pero `SettingsPatch` lo rechazaba con 400 y no había
  campo en Ajustes: la única forma de ponerlo era un `UPDATE` a mano.
- **Un apóstrofo mataba todos los clips en cola, para siempre.** `text='...'`
  con `'` escapado como `\'` rompía el grafo de filtros, y un render rechazado
  estampa `rendered_at` sin que nada lo reinicie. El texto del operador pasa a
  `textfile=`, que no tiene micro-lenguaje. «O'Brien Realty» y
  «Smith & Jones, Realty, Inc.» renderizan.
- **`booking_contact_email` se podía escribir y no se guardaba nunca.** Salía
  «Guardado ✓» y el valor desaparecía de la pantalla. Sin él, un lead que solo
  dejó teléfono no se puede agendar.
- El endpoint de estado filtra por organización explícitamente, y se niega
  ruidosamente si no hay ninguna atada.

## [0.54.4] — 2026-08-25

### Corregido — un aviso que no salió daba la avería por comunicada

Una revisión adversarial de Codex encontró el **mismo defecto en las dos capas**
de vigilancia de v0.54.3: se consumaba la transición de estado aunque el email
no hubiera salido. Un tropiezo del transporte en el momento equivocado retiraba
la avería y la siguiente comprobación veía "sin cambio": **detectada y luego
olvidada para siempre**, que es exactamente el fallo que un vigilante existe
para impedir, reproducido dentro del vigilante.

**Capa 1 — `services/llm_monitor.py` + migración 042.** Ver y decir pasan a ser
dos hechos: `monitor_state.state` es la última lectura (avanza siempre; es lo
que publica `/api/v1/health`) y `alerted_state` es lo último que el operador
recibió confirmado. Un envío **rechazado** ya no lo avanza, así que la avería
sigue pendiente y se reintenta. Misma regla para `last_seen_fallback_at`, que es
la única señal aquí que describe daño consumado y no riesgo: un mensaje
rechazado no puede borrar la prueba de que un cliente real recibió la línea de
espera.

**La excepción, dicha en voz alta:** si el canal **no está configurado**
(sin `OPS_ALERT_FROM`, sin destinatarios o sin clave), los dos avanzan sin que
salga ningún correo. No es un descuido: ningún número de reintentos llega a
nadie hasta que un humano edite el `.env`, y mantener el hueco abierto dejaría
el cutoff del barrido congelado, recontando una ventana sin límite en cada
organización cada cinco minutos. Queda en el log y en `/api/v1/health`, y en el
caso del barrido la prueba sigue en `messages.llm_provider`.

**Capa 2 — `deploy/heartbeat.sh`.** `send_alert` pasa de booleano a tres
desenlaces: entregado, el intento falló (reintentar) y no se puede entregar en
absoluto (canal sin configurar → consumir, porque ningún número de intentos
llega a nadie hasta que un humano edite el fichero). El fichero de estado se escribe
en el **primero y el tercero**; el segundo —el intento que falló— es el único
que **no** lo escribe, que es exactamente lo que hace posible el reintento.

### El reintento tiene techo, y esa es la mitad difícil

Dos auditorías independientes encontraron que la primera versión de este arreglo
cambiaba un fallo por otro peor: el contador diario solo subía con éxito, así
que el presupuesto nunca cerraba y cada tick reintentaba — 288 al día en la capa
1, 96 en la capa 2. Y como **un mensaje que el proveedor aceptó pero cuya
respuesta expiró se lee aquí como fallo**, esos reintentos serían duplicados
reales contra la misma cuota que responde a los leads: el vigilante tumbando el
producto que vigila. Ahora se cobra el **intento**, no la entrega. Un reintento
acotado puede retrasar un aviso un día; uno sin acotar no puede existir.

El backfill de la migración también estaba mal por la misma clase de error: daba
por comunicada toda fila existente, sobre la premisa —falsa— de que v0.54.3 solo
escribía `state` tras intentar avisar. Esa asignación estaba fuera de todo
condicional. Solo se rellenan las filas sanas; cualquier otra queda NULL, que
bajo las reglas nuevas es una deuda y se entrega en el siguiente tick.

### Añadido — el vigía externo tenía cero pruebas

`deploy/heartbeat.sh` corre por cron en otra máquina, así que nada en la suite
lo tocaba. Ahora hay **12 tests**, y **11 lo ejecutan de verdad como subproceso** contra un
proveedor de correo simulado: ninguno manda un email. El doceavo es una
afirmación sobre el fuente — que la clave no aparezca en el `argv` del `curl` —
porque comprobarlo en caliente exigiría leer la tabla de procesos y eso no es
portable entre macOS y CI. Ese sí se verificó a mano contra un envío en vuelo. `RESEND_URL` es
overridable justo para eso — la rama de éxito decide si una avería cuenta como
comunicada, y la única otra forma de probarla es escribirle a una persona real
en cada ejecución.

### Seguridad

La clave de Resend viajaba en el `argv` de `curl`, donde `/proc/<pid>/cmdline`
es legible por cualquier usuario local: el `chmod 600` del fichero de entorno no
servía de nada. Ahora va por stdin (`--config -`) y el cuerpo por un fichero
`0600`, no por una línea de comandos que nombra hosts y contenedores internos.
Verificado leyendo el `argv` de un envío en vuelo.

### Límites, dichos en voz alta

Cobrar intentos puede dejar mudo al vigía tras un bache del proveedor, y el
peor caso es más largo de lo que parece: el presupuesto se indexa por **día
UTC**, no por ventana móvil, así que tres intentos quemados poco después de las
00:00 UTC dejan mudo **hasta ~23 h**. Es el intercambio consciente frente al
bucle sin techo, y no es peor que antes (donde el aviso se perdía del todo).
Cierre pendiente: un techo **horario** para intentos, reservando el diario para
entregas.

997 backend + 90 frontend en verde; ruff, tsc, shellcheck y `bash -n` limpios.
Mutaciones verificadas en las dos capas.

## [0.54.3] — 2026-08-25

### Añadido — la vigilancia, en dos capas y con sus límites dichos

v0.54.2 puso `llm_fallback` en `/health` y ahí se quedó: **una foto del arranque
que nadie consultaba**. Una medición que nadie lee es la misma forma de error
que un flag que nadie comprueba. Tres puntos ciegos, verificados antes de tocar
código:

1. Se sondeaba una vez en el lifespan. Si Ollama moría a las 3 de la mañana,
   `/health` seguía diciendo `ok` hasta el siguiente reinicio.
2. **No existía ningún canal de aviso.** `PLATFORM_ADMIN_EMAILS` era solo una
   lista de identidad; nada le escribía.
3. Un mensaje sellado `provider='fallback'` —un cliente real que recibió la
   línea de espera— solo se veía abriendo esa conversación, una por una.

**Capa 1, dentro (`services/llm_monitor.py`).** Un cuarto worker re-mide cada
`LLM_MONITOR_INTERVAL_SECONDS` (300 por defecto) y barre la base en busca de
respuestas enlatadas nuevas, vía `run_for_every_org` — un worker sin org vería
cero filas bajo RLS default-deny, para siempre y en silencio. **Cero cambios en
el camino de respuesta al lead**: el bucle observa la base de datos, no se mete
en el hot path.

**Aviso por CAMBIO de estado, nunca por reloj**, y con el comando que lo arregla
en el cuerpo. Un correo al romperse, uno al recuperarse. Tope duro de 3 al día:
comparte la cuota de Resend con las respuestas a clientes, y un aviso de nivel
cada 5 minutos (288/día) agotaría el free tier y **tumbaría el producto que
vigila**.

**Canal propio (`services/ops_alert.py`), no `send_email()`.** Aquel resuelve la
identidad *de la organización actuante*; un worker no tiene org, y un aviso al
operador no es tráfico de inquilino. Confundirlos es el patrón que ya hizo que
la agencia B respondiera desde la dirección de la A.

**Capa 2, fuera (`deploy/heartbeat.sh`).** Un proceso no puede avisar de su
propia muerte. Cron cada 15 min en `ender-vps` contra el endpoint público, por
Resend directo y nunca a través del ROG. **Debounce de dos fallos consecutivos**:
cada despliegue reinicia el backend, y un vigía que avisa en cada despliegue es
un vigía al que se deja de creer.

**Tabla `monitor_state`** (migración 041): compartida, **sin `org_id` y sin RLS
a propósito**, como `properties` y `sync_state` — la salud de la instalación no
pertenece a ninguna agencia. Persistida y no en memoria porque un backend en
crash-loop mandaría un correo por reinicio.

Mutación verificada: quitar la comparación `previous != status` pone en rojo
`test_second_tick_in_the_same_state_says_nothing`. 977 backend + 90 frontend.

### Límites, dichos en voz alta

Las dos capas comparten transporte: **si Resend cae o se queda sin cuota,
enmudecen a la vez.** Y no se vigilan activamente Kimi ni MiniMax: cada sondeo
gastaría cuota de suscripción, así que el vigilante causaría el agotamiento que
busca. Se observan gratis desde el tráfico real — y lo que hace tolerable ese
hueco es que el eslabón local está ahora probadamente sano.

## [0.54.2] — 2026-08-24

### Corregido — el tercer eslabón de la cadena de LLM no existía

La cadena es Kimi → MiniMax → Ollama local. El tercero llevaba **doce semanas
declarado y muerto**, por **dos averías independientes** — cualquiera de ellas
bastaba, y arreglar solo una habría dejado el fallback igual de inútil con
aspecto de arreglado:

- **Red.** Ollama escucha solo en `127.0.0.1`, pero el backend lo busca en el
  gateway del puente de Docker (`172.20.0.1`): `Connection refused` desde el
  contenedor, `200` desde el host. Arreglado con un proxy `socat` en el host
  (`ollama-bridge.service`) atado **exclusivamente** a esa interfaz. Ollama no
  se reconfigura ni se reinicia: no tiene autenticación, y este host está en una
  WiFi doméstica y en una tailnet con `ufw` inactivo, así que `OLLAMA_HOST=0.0.0.0`
  habría publicado una API abierta en las dos redes.
- **Modelo.** `OLLAMA_MODEL=gemma3:4b` no estaba descargado (`/api/show` → 404).
  Descargado; es además el único candidato que cabe en la VRAM libre.

No es hipotético: el **1-jun-2026** Kimi devolvió 403 y MiniMax 429 en el mismo
minuto, y ese Ollama respondió **10 conversaciones reales** (`llm_provider='ollama'`
en `messages`). Hoy no habría podido. MiniMax aquí es plan de suscripción, así
que el 429 es el modo de fallo normal, no un accidente.

Nota: el lead nunca se quedó sin respuesta — `conversation.py` captura
`LLMUnavailable` y devuelve un acuse bilingüe sellado `provider="fallback"`. El
daño era de **calidad**: una línea de espera en vez de una respuesta.

### Añadido — que un proveedor declarado tenga que demostrarlo

`OLLAMA_ENABLED=true` era una declaración de intenciones que no afirmaba nada
sobre el mundo, y por eso las dos averías sobrevivieron tres meses.

- `check_fallback_provider()` comprueba **las dos** cosas: que el servidor
  responde **y** que `OLLAMA_MODEL` está realmente ahí. Una sonda de solo-puerto
  habría cazado la primera avería y declarado sana la segunda.
- Se ejecuta al arrancar (con `log.error` accionable, sin bloquear el arranque)
  y su resultado se publica en `GET /api/v1/health` como `llm_fallback`:
  `ok` | `unreachable` | `model-missing` | `off`. Mismo precedente que el campo
  `captcha`, y por el mismo motivo: el fallo es invisible desde fuera.
- Test de mutación: borrar la comprobación del nombre del modelo pone en rojo
  `test_probe_reports_model_missing_when_server_answers_without_it`.

## [0.54.1] — 2026-08-20

### Corregido — la duodécima ronda de auditoría (auditor independiente)

Primera auditoría del Estudio de Contenido entero. Dos huecos reales, los dos
**latentes** — el publicador aún no existe, así que ninguno era visible hoy;
cerrarlos antes de que exista es exactamente para lo que se audita. Y por
primera vez en doce rondas, **los arreglos de la ronda anterior volvieron
limpios**.

- **La vigilancia del futuro publicador se fiaba del nombre.** Solo examinaba
  funciones llamadas publish_*/upload_*: un publicador llamado de otra forma
  habría entrado sin pasar por la puerta de aprobación, con todo en verde — el
  mismo defecto de filtro-por-nombre que la ronda once quitó del control de
  bajas, sentado en la puerta de contenido. Ahora clasifica por lo que la
  función hace, y cada función que toca la red debe estar declarada o exenta
  con motivo.
- **Una agencia podía referenciar la pieza de otra.** La clave foránea solo
  comprobaba que la pieza existiera — y esa comprobación no pasa por el
  aislamiento entre agencias. Reproducido: la agencia B insertó un registro de
  publicación apuntando a una pieza de la agencia A que no puede ni leer, y con
  ello habría bloqueado para siempre que A registrara su propia publicación en
  esa plataforma. Ahora la base de datos misma exige que publicación y pieza
  pertenezcan a la misma agencia.
- El filtro de vivienda justa aprende dos frases más ("kid-free",
  "child-free") y la reparación de contadores fija sus dos bordes exactos en
  pruebas: una fila futura no pudo tener retenciones (0) y una de hoy
  exactamente una.

## [0.54.0] — 2026-08-20

### Nuevo — el clip del móvil sale listo para publicar

El primer carril de render del Estudio de Contenido. Un clip grabado con el
teléfono se convierte solo en un vídeo vertical publicable — y si no puede,
dice por qué en la propia cola, no en un registro que nadie lee.

- **Vertical sin recortar el encuadre.** El clip se ajusta a 1080×1920 sobre un
  fondo desenfocado de sí mismo: el agente encuadró el plano, no nosotros.
- **La identificación de la brokerage va QUEMADA en el vídeo.** Colorado exige
  que la publicidad identifique la brokerage; unos píxeles grabados sobreviven
  a los recortes, silencios y re-codificaciones de cada plataforma — un pie de
  texto no. Sin línea de brokerage en Ajustes, los clips esperan con el motivo
  visible y se renderizan solos en cuanto se rellena.
- **La puerta de calidad mide estructura, nunca estética**: que haya vídeo, que
  la duración sea trabajable, que el audio del original siga en el resultado.
  Lo aprendido al lado: las puertas que miden cómo "se ve" un vídeo rechazan
  trabajo correcto que no entienden — para eso está la persona que aprueba.
- **El resultado se verifica contra el archivo, no contra el comando.** Un
  render que devolvió éxito pero produjo otra cosa es un render fallido.
- Un clip corrupto falla visible en su fila y no bloquea a los demás.

## [0.53.1] — 2026-08-20

### Corregido — la undécima ronda de auditoría (auditor independiente)

- **La reparación del contador que la propia corrección envenenó.** La 0.51.2
  separó el contador de la quincena de permiso, y su relleno inicial copió el
  total contaminado por errores: un cliente retenido UNA vez que atravesó una
  avería llegaba con el contador a 14, su segunda retención real se convertía
  en la rendición número quince, y la secuencia entera moría dos días después
  de la visita — el mismo defecto que esa versión arreglaba, resucitado por su
  propia migración. La reparación acota el contador a los días realmente
  transcurridos (las retenciones son como mucho una al día): una fila retenida
  con honestidad conserva su cuenta exacta y una envenenada recupera la
  quincena que se le debe. **Y esta vez el relleno tiene pruebas que lo
  ejecutan contra datos**, que es exactamente lo que faltó la primera vez.
- **Un error pasajero ya no indulta un mensaje rancio.** El reintento por error
  dejaba una marca que contaba como "alguien decidió aplazar esto", así que
  tras una caída larga el gemelo con un error de hace días se enviaba 30 horas
  tarde mientras el limpio se cancelaba. La marca de un error compra su hora de
  reintento y nada más.
- **El contador de errores mide un episodio, no una vida.** No se reiniciaba
  nunca, así que una fila que sobrevivió averías durante semanas moría al
  primer tropiezo de un día por lo demás sano.
- **La vigilancia de canales de envío ya no se fía del nombre.** Solo
  examinaba funciones llamadas send_*: un canal nuevo llamado de otra forma
  (notify..., place_call...) entraba con cero control de bajas y todo en
  verde. Ahora clasifica por lo que la función HACE, no por cómo se llama, y
  las tres formas de fuga encontradas en tres rondas distintas quedan cazadas.

## [0.53.0] — 2026-08-20

### Nuevo — el Estudio de Contenido escribe borradores solo

La generación diaria, con las dos puertas automáticas por delante de la humana.
**Sigue sin publicar nada**: lo generado termina, como máximo, en la cola de
aprobación de la consola.

- **Un borrador de vídeo al día por defecto (máximo 3), apagado de fábrica.**
  Encenderlo es una decisión por instalación (`CONTENT_STUDIO_ENABLED`), y el
  tope diario acota la factura de IA desde el primer día.
- **Temas de Denver que no necesitan permisos de nadie**: qué compra un
  presupuesto hoy, la inspección, de la oferta al cierre, el depósito de
  seriedad, preaprobación, la primera semana de venta, cómo leer el mercado.
  Sin fichas de propiedades (eso requiere el feed MLS y derechos de imagen).
  Los temas rotan y el idioma alterna entre los que trabaje la agencia.
- **El filtro de vivienda justa corrige a la máquina antes que a nadie.** Si el
  borrador sale con frases prohibidas, se le pide UNA reescritura nombrando las
  frases; si reincide, se queda en Borradores con las frases señaladas para que
  una persona lo edite. Un borrador marcado nunca entra solo en la cola.
- **La salida del modelo se trata como entrada hostil**: se valida contra un
  esquema y, si no es un borrador, se descarta con registro — nunca tumba el
  ciclo, porque un ciclo caído es también el borrador de mañana.

## [0.52.0] — 2026-08-20

### Nuevo — Estudio de Contenido: el carril y la puerta

La base del estudio de vídeo corto para agentes. **Todavía no genera ni publica
nada**: esta versión construye, a propósito y primero, la puerta que hace
imposible publicar sin una persona.

- **Cola de aprobación en la consola.** Pestaña "Contenido": borradores,
  pendientes de aprobar, aprobados y rechazados, con reproductor para clips,
  edición en línea y los dos botones que lo resuelven. En inglés y español.
- **Nada se publica sin una persona.** El estado APROBADO solo puede ponerlo
  alguien desde la consola, y queda registrado quién y cuándo. Editar una pieza
  aprobada la devuelve a la cola: lo aprobado era el texto anterior.
- **Filtro de vivienda justa (Fair Housing), determinista y en dos idiomas.**
  Más de 90 frases que la ley no permite en publicidad de vivienda —
  "perfect for families", "barrio seguro", "good schools" — se detectan al
  escribir, al enviar a aprobación y OTRA VEZ al publicar. Un borrador con
  frases marcadas no llega solo a la cola: se queda en borradores con las
  frases señaladas para que una persona las corrija.
- **Sin identificación de brokerage no se publica.** Colorado exige que la
  publicidad identifique la brokerage; el campo existe ahora en Ajustes y la
  puerta se niega mientras esté vacío.
- **Clips desde el móvil.** Subida de vídeo en streaming (el ajuste decía 500 MB entonces; son 95 desde la 0.56.0;
  el límite real por el sitio es ~100 MB — ver v0.55.1) que
  queda como borrador; el archivo se sirve solo autenticado y dentro de la
  frontera de cada agencia.

### Interno

- Tablas `content_pieces` y `content_publications` (migraciones 035–037) con
  aislamiento por agencia verificado en ambos sentidos y por mutación.
- Máquina de estados cerrada: toda transición no declarada es un error, y un
  barrido del árbol garantiza que nadie escribe un estado por fuera.
- `PUBLISH_PRIMITIVES` está vacío y una comprobación lo obliga a ser honesto:
  el primer publicador que llegue sin declararse pone la suite en rojo.

## [0.51.2] — 2026-08-19

### Corregido — la décima ronda de auditoría (auditor independiente)

- **Una hora de errores ya no mata una secuencia entera.** Un contador servía
  para tres cosas a la vez: los días que llevamos esperando permiso para
  escribir a un cliente, los fallos al elegir canal, y los intentos de envío.
  Solo el primero debe agotar la quincena de reintentos, pero cualquiera de los
  tres la gastaba — y la rama de error, además, no dejaba marca de "reintentar
  luego", así que el mensaje volvía a vencer a los cinco minutos. Trece pasadas
  de una avería de una hora agotaban trece días de margen; dos pasadas normales
  después la secuencia se cerraba, y desde la 0.51.0 se cierra **entera**. Un
  cliente que visitó una propiedad el día 3 no recibía **ninguno** de los tres
  mensajes, y la secuencia moría el día 5. Ahora la quincena tiene su propio
  contador y **solo una espera de permiso puede gastarla**; un error espera una
  hora y se cuenta aparte.
- **El recuento de la pasada volvía a mentir**, ahora al alza: un mensaje
  retenido al principio del lote y cerrado después por su secuencia se contaba
  dos veces. Cuatro resultados para tres mensajes.
- **Una secuencia sin visita ya no alcanza a los demás clientes.** El cierre en
  cadena buscaba "los demás mensajes de esta visita"; en un seguimiento de
  llamada, que no tiene visita, eso significaba **todos los seguimientos de
  llamada de la organización**. Un cliente quedándose sin margen habría cerrado
  los recordatorios de llamada de toda la cartera. La protección existía; lo que
  no existía era nada que avisara si alguien la quitaba.
- **Dos formas de enviar se escapaban del control de bajas.** La comprobación
  que vigila que ningún canal salga del sistema de opt-out no reconocía una de
  las maneras habituales de mandar una petición HTTP, ni miraba fuera de una
  carpeta concreta — justo donde va a vivir el canal de voz. Las dos quedan
  cubiertas.

## [0.51.1] — 2026-08-19

### Corregido — la novena ronda de auditoría

Tres fallos en los arreglos de la 0.51.0, encontrados borrando cada arreglo y
comprobando si algo se ponía en rojo. Ninguno cambia lo que usted recibe; los
tres afectan a lo que podemos garantizarle sobre lo que ya está en marcha.

- **Un mensaje ya descartado podía seguir acumulando reintentos.** Al cerrar una
  secuencia entera, los mensajes que caían con ella volvían a pasar por las
  reglas de envío en la misma pasada y quedaban marcados como "reintentar
  mañana" pese a estar cerrados. Un registro que se contradice a sí mismo, y es
  el que lee la consola.
- **El recuento de la pasada mentía.** Al cerrar una secuencia de tres mensajes
  informaba de uno.
- **El plazo de 30 días no estaba anclado a nada.** Se podía cambiar sin que
  ninguna comprobación se enterara — lo verificamos poniéndolo en 114 días y
  todo siguió en verde. Ahora está fijado al número que le prometemos aquí: si
  alguien lo mueve, algo se pone en rojo y esta entrada tiene que actualizarse.

## [0.51.0] — 2026-08-19

### Corregido — la octava ronda de auditoría

- **La secuencia de seguimiento ya no se muere a plazos.** Cuando pasan catorce
  días sin que ningún canal tenga permiso, el sistema se rinde con ese mensaje.
  Hasta ahora se rendía **solo con ese**: el siguiente de la secuencia quedaba
  liberado y empezaba su propia quincena, y el tercero la suya. Tres relojes en
  fila superan el límite de antigüedad, así que el mensaje de los 7 días se
  cancelaba sin enviarse — y si el permiso llegaba tarde, el cliente recibía un
  único "¿qué tal la visita?" un mes después de la visita, con los dos mensajes
  anteriores nunca enviados. La secuencia tiene un solo destino y ahora se cierra
  entera a la vez.
- **El límite de antigüedad se calcula, ya no se escribe a mano.** Estaba fijado
  en 30 días, un número elegido que no guardaba ninguna relación con la quincena
  de reintentos que tiene que dejar pasar; por eso cancelaba trabajo que todavía
  estaba en curso. Ahora se deriva de esa quincena. **El plazo real no cambia:
  siguen siendo 30 días.** Lo que cambia es que subir los reintentos mueve el
  límite con ellos en vez de reintroducir el fallo en silencio.
- **Un mensaje ya resuelto no se vuelve a procesar en la misma pasada.** El
  barrido recargaba cada fila de memoria sin comprobar que siguiera pendiente,
  así que una decisión tomada sobre un mensaje al principio del lote podía
  deshacerse sobre ese mismo mensaje al final.

### Corregido — dos comprobaciones que no comprobaban nada

Ninguna de las dos afecta a lo que usted ve; las dos afectan a lo que podemos
prometerle sobre lo que ya está en marcha.

- La regla de orden publicada en la v0.50.0 **no tenía ninguna prueba que la
  respaldara**: se podía borrar entera y todo seguía en verde. La prueba que
  debía cubrirla se detenía en una regla anterior sin llegar nunca a ella. Ya
  está cubierta, y verificada borrándola: ahora se pone en rojo.
- La comprobación que vigila que ningún canal de envío se escape del control de
  bajas **aceptaba cualquier cosa** por cómo estaba escrita. Ahora compara la
  lista real contra la declarada, nombre a nombre.

## [0.50.1] — 2026-08-16

### Corregido — los tres menores de la séptima ronda

- **El contador se marcaba antes de que la base de datos lo confirmara.** En el
  handler de selección de canal, `counted` se ponía antes del commit: si ese
  commit fallaba, el handler exterior deshacía el incremento —así que el límite
  de rendición era inalcanzable por esa vía— mientras `counted` silenciaba el
  recuento de fallos y la fila volvía a PENDING. El número afirmaba un
  desenlace que la base de datos no tenía. Ahora se cuenta después del commit.
- **La consola no decía cuándo se volverá a intentar.** Desde que el
  aplazamiento tiene columna propia, `scheduled_for` se queda en la fecha para
  la que era el mensaje —correcto y más útil—, pero el asesor veía "retenido, 7
  intentos, vencía hace 7 días" sin saber cuándo lo intentará el sistema. Añadido
  `next_attempt_at`.
- **El canario por módulo comprobaba que hubiera *alguno*, no cuántos**, así que
  pasaba si un módulo bajaba de dos emisores a uno — el mismo adelgazamiento que
  el umbral global permitía.

## [0.50.0] — 2026-08-16

### Corregido — séptima ronda de auditoría

La ronda confirmó que el cambio estructural cerró lo suyo (tres visitas el mismo
día: 9 encoladas, 9 entregadas, 0 canceladas) y encontró que **no lo terminé**.

- **El arreglo del orden no se ejecutaba nunca, y el changelog ya lo prometía.**
  Puse la cadencia como segundo criterio de ordenación, detrás de la fecha — y
  las fechas **no empatan**: una retención estampa "mañana + el desfase del
  tick" sobre una fila ya vencida mientras su hermana conserva su hora exacta.
  El desempate nunca llegaba a consultarse. Reproducido al ritmo real de
  producción. Ahora es una **invariante**, no un truco de ordenación: un mensaje
  post-visita espera mientras siga pendiente otro anterior **de la misma
  visita**. Ninguna fase de reloj puede con eso.
- **La agenda se arregló en el filtro y no en la proyección.** Seleccionaba y
  ordenaba por la fecha efectiva y luego devolvía la columna cruda, así que un
  seguimiento aplazado se pintaba semanas en el pasado, antes del propio suelo
  del endpoint. Arreglar una consulta en su WHERE y no en su SELECT la deja a
  medias y con aspecto de estar bien.
- **El defecto de "una columna, dos significados" se había mudado a
  `attempts`.** Lo quité de `scheduled_for` y añadí `attempts == 0` a la regla
  de antigüedad, que le daba un cuarto significado ("¿alguien tocó esto?")
  encima de los tres que ya tiene. Además exentaba para siempre a cualquier fila
  que hubiera tenido **un** fallo transitorio: un aviso de cuatro meses volvía a
  salir. Migración **033** hace explícitos los aplazamientos anteriores a la 032
  y el conjunto sobra.
- **Nada acotaba lo tarde que podía llegar un mensaje aplazado por el tope.**
  Se drena uno por lead y día, así que un comprador con quince visitas recibía
  "hay pisos nuevos" seis semanas después. Ahora hay un techo absoluto de 30
  días — escribible solo porque `scheduled_for` ya es honesto.
- **Migración 034: el índice que la 032 decía tener, no lo tenía.** Postgres no
  puede usar un índice de ninguna de las dos columnas para un predicado sobre
  `COALESCE(a, b)`; medido con 50.000 filas, el barrido recorría **todas** las
  PENDING, unas 10× más lento y creciendo con la cola. Índice de expresión
  parcial, y fuera el que no usaba nadie.

## [0.49.1] — 2026-08-16

### Corregido — los tres residuos de la sexta ronda, y dos tests que mentían

- **El orden de la cadencia era una convención tipográfica.** El desempate era
  `id`, e `id` coincidía con la cadencia solo porque `enqueue_for_visit` recorre
  `_POST_VISIT_OFFSETS` en el orden en que ese diccionario está *escrito*.
  Reordenar tres líneas —una edición que pasa cualquier revisión— invertía lo
  que recibe el cliente. Ahora el orden se deriva de los propios offsets.
  **El test que escribí para esto pasaba sin probar nada**: cada fila tomaba su
  `datetime.now()` y difería en microsegundos, así que el primer criterio ya
  desempataba. Con las marcas igualadas se puso rojo y mostró el fallo real.
- **El canario del nuevo barrido estaba un punto por debajo de la cuenta real**
  (exigía 3 emisores habiendo 4), así que el renombrado que existe para atrapar
  seguía pasándolo. Ahora cada canal —`sms`, `whatsapp`, `email`— responde por
  sí mismo. Verificado por mutación.
- **Un test prometía más de lo que comprueba**: la invariante de la ventana solo
  acota la ruta de las filas que nadie ha tocado; a las retenidas las acota el
  contador de rendición y la ráfaga la impide el tope por barrido. Nombre y
  docstring dicen ahora exactamente eso.

## [0.49.0] — 2026-08-16

### Cambiado — una columna nueva que cierra una clase entera de fallos

Migración **032** (aditiva y reversible): `follow_ups.postponed_until`.

La sexta ronda de auditoría no solo encontró ocho cosas — encontró **la causa
que llevaba seis rondas generando parches**. `scheduled_for` significaba dos
cosas a la vez: *cuándo era este mensaje* y *cuándo volver a mirar*. La
retención y el tope por barrido sobrescribían la segunda encima de la primera, y
de ahí salían síntomas que parecían no tener relación:

- la regla de antigüedad no podía distinguir "nadie ha mirado esto en un mes" de
  "aplazado ayer a propósito", así que necesitaba una holgura **adivinada** a
  partir de constantes — dimensionada para una visita, cancelaba en silencio el
  "¿qué tal fue?" de un lead con **tres visitas el mismo día** (8 mensajes de 9);
- la consola no podía distinguir una fila aplazada de una que simplemente aún no
  toca, así que el filtro que la mostraba **inundaba** la lista de retenidos con
  todas las reservas futuras del sistema, enterrando las retenciones reales.

Con dos significados en dos columnas, los dos desaparecen: `scheduled_for` no se
sobrescribe nunca más, la holgura adivinada **se elimina entera**, y el filtro de
la consola es exacto (`postponed_until IS NOT NULL`).

### Corregido — el resto de la sexta ronda

- **El seguimiento de llamada no tenía límite de antigüedad**: la regla estaba
  condicionada a los tipos derivados de visita, y el aviso de llamada se añadió
  después. Uno programado hace cuatro meses salía en el primer barrido de vuelta,
  preguntando si algo había cambiado desde una conversación que nadie recuerda.
- **El handler exterior inventaba un `FAILED`**: lo ponía también para
  excepciones que ningún handler interno había visto (un fallo transitorio en la
  consulta del lead o de la visita). `FAILED` es terminal, así que **un parpadeo
  de conexión cancelaba para siempre** el aviso de ese lead — lo contrario de lo
  que la ruta de retención promete. Ahora solo restaura un estado que alguien
  eligió de verdad.
- **Una fila podía contarse como saltada y fallida a la vez.**
- La agenda del calendario y el orden del barrido leen ahora la fecha efectiva
  (`COALESCE(postponed_until, scheduled_for)`), así que una fila retenida no
  desaparece del calendario ni aparece en el pasado.

## [0.48.2] — 2026-08-16

### Corregido — quinta ronda de auditoría independiente (sobre v0.48.0/0.48.1)

Quinta ronda, y tampoco limpia — pero con un matiz nuevo: **las dos regresiones
son dos arreglos del mismo commit chocando entre sí**, no con código viejo.
Ninguno de los dos está mal por separado.

- **REGRESIÓN (v0.48.0): el mensaje "¿qué tal fue la visita?" se cancelaba en el
  escenario para el que se escribió el arreglo.** El límite absoluto dejaba
  1 h 1 min de holgura sobre la rendición de la retención, y el tope de un
  mensaje por barrido gasta **un día entero** de esa holgura por cada mensaje
  aplazado. Con el consentimiento llegando el día 14, el lead recibía el de 7
  días y el de 72 h, y el de 24 h quedaba `cancelled`, nunca enviado.
  El límite cuenta ahora también los días que el tope puede consumir.
- **REGRESIÓN (v0.48.0): el orden de entrega era un empate puro, y salía al
  revés.** Cada retención escribe el mismo `now + 1 día` en todas las filas
  vencidas, así que tras la primera retención común las tres comparten
  `scheduled_for` y el `ORDER BY` no discrimina: al cliente le llegaba "hay
  pisos nuevos como el que viste" primero y "¿qué tal fue la visita?" dos días
  después. Ahora se desempata por `id`, que es el orden en que se insertan y por
  tanto la cadencia. Era además la causa próxima del punto anterior: la fila con
  el margen más ajustado se servía la última.
- **Mi test de la invariante tenía el defecto que describe su propio
  docstring**: comprobaba `_POST_VISIT_GRACE` (24 h) cuando la ventana que
  decide si una fila sigue siendo enviable es `_SEND_STALE_AFTER` (25 h).
- **El contador de fallos sumaba dos veces** cuando la recuperación interna
  lanzaba hacia el handler exterior, y el rollback de ese handler descartaba el
  estado FAILED que el interno acababa de escribir, dejando la fila PENDING para
  que el siguiente ciclo la reenviara. Ambas cosas cerradas.
- **Una fila aplazada por el tope no aparecía en ninguna pantalla**: la lista de
  retenidos de la consola filtra por `attempts > 0` y el tope aplaza sin tocar
  el contador.
- **El barrido de primitivas no tenía canario propio.** Un barrido que no
  recorre nada pasa, y este fichero existe precisamente porque eso ya ocurrió
  aquí. Ahora comprueba cuántos ficheros recorre y cuántos emisores considera.

## [0.48.1] — 2026-08-16

### Corregido — los tres residuos que la cuarta ronda dejó señalados

- **Un comentario afirmaba la invariante equivocada.** Decía que la ventana de
  gracia era "el hueco más pequeño de la cadencia" cuando es el *offset* más
  pequeño (24 h; el hueco menor es 48 h). Las dos son seguras hoy, así que la
  prosa seguiría siendo cierta mientras la propiedad que dice garantizar se
  rompía — bastaba añadir un cuarto mensaje a menos de 24 h de su vecino. Ahora
  hay un test que lo comprueba contra los valores reales en vez de un comentario.
- **El test de completitud de primitivas tenía cuatro salidas.** `glob` no veía
  subpaquetes, `tree.body` no veía métodos de una clase cliente, `AsyncFunctionDef`
  no veía ayudantes síncronos, y buscar solo `post` no ve al SDK de Twilio, que
  envía con `messages.create`. Ampliado en las cuatro direcciones.
- **Verificado, no supuesto**: las dos rutas que reservan en Cal.com —el panel y
  el agente de voz— comprueban el opt-out antes de reservar (`visits.py:287`,
  `voice.py:353`). Importa porque Cal.com envía correos al asistente, así que
  reservar es contactar.

## [0.48.0] — 2026-08-16

### Rendimiento — la bandeja deja de cargar entidades que no usa

`gather_inbox` con 10.000 leads: **10,0 s → 0,17 s** (mismo script, mismo
protocolo; en régimen estable, y con 5.000 leads 0,08 s). Es lo que pollea el
badge del nav.

Lo importante es **dónde estaba el coste**, porque no era donde el plan decía ni
donde yo supuse. Perfilando: 6,2 s en cargar los 10.000 objetos `Lead`, 3,6 s +
3,1 s en las dos consultas de mensajes, y **0,07 s de ensamblado en Python**.
Mi hipótesis fue que el problema era planificar una cláusula `IN` con 10.000
literales: **falsa**. La subconsulta que probé lo empeoró a 18,3 s y `= ANY(array)`
no cambió nada. La medición del auditor lo cerró: el filtro cuesta ~20 ms, y
`load_only` tampoco ayuda — el coste es que SQLAlchemy construya diez mil
objetos instrumentados con su identity map. Se seleccionan las nueve columnas
que alguien lee de verdad, y ya está.

Caveat honesto: las filas del banco de pruebas son sintéticas y sin campos
largos, así que la proporción es el hallazgo, no los milisegundos exactos.

### Corregido — cuarta ronda de auditoría independiente (sobre v0.47.8)

Cuarta ronda seguida en la que el arreglo anterior rompe a su vecino.

- **REGRESIÓN (v0.47.8): usar `attempts == 0` como discriminador cambió
  "la secuencia se descarta" por "la secuencia sale de golpe, 38 días tarde".**
  Un contador dice si alguien tocó la fila, nunca **cuándo**; y exentar a todas
  las tocadas dejaba que un apagón largo liberase las tres a la vez. Verificado
  ejecutando: con v0.47.7 salían 0 mensajes, con v0.47.8 salían 3. Ahora el
  retraso se acota en absoluto desde la fecha de la visita a la que el mensaje
  se refiere, dejando transcurrir antes toda la ventana legítima de retención.
- **Añadido un tope que no depende de acertar con las fechas**: como mucho **un
  mensaje post-visita por lead y por barrido**. Cubre además un defecto
  pre-existente que ninguna de las dos ventanas de gracia podía ver — la
  retención empuja todas las filas vencidas al mismo "mañana", así que quince
  días de espera colapsan la cadencia 24h/72h/7d en un solo tick y la llegada
  del consentimiento las dispara juntas.
- **REGRESIÓN (v0.47.8): puse el arreglo de la hora inexistente en uno de los
  dos resolutores.** `voice.py` tiene el suyo y seguía convirtiendo las 02:30
  del cambio de horario en una cita real a las 03:30 — con las dos horas
  resolviendo al mismo instante, que es justo el choque que el commit decía
  arreglar. Es el defecto característico de este repo cometido dentro del
  arreglo de ese mismo defecto.
- **El `try` anidado no lograba su objetivo en el fallo para el que se escribió**:
  la recuperación corre sobre la misma sesión que acaba de fallar, así que con
  la sesión rota también falla, la excepción escapa del bucle y el siguiente
  ciclo reenvía. El cuerpo por elemento tiene ahora un `except` de verdad.
- Eliminada una salida temprana duplicada que quedó inalcanzable en v0.47.8.

## [0.47.8] — 2026-08-16

### Corregido — tercera ronda de auditoría independiente (sobre v0.47.7)

Tercera ronda seguida en la que **el arreglo de la anterior rompe a su vecino**.
Esta vez el propio informe lo dice: "esta es exactamente la forma de las dos
rondas previas".

- **REGRESIÓN (v0.47.7): un apagón de 25 h cancelaba para siempre toda secuencia
  retenida.** El corte por antigüedad que añadí para evitar la ráfaga se ejecuta
  **antes** de la rama de retención, y juzgaba por `scheduled_for` — que la
  propia retención mueve un día cada vez. Con el worker caído algo más de un
  día, cada seguimiento en espera de consentimiento se cancelaba, tirando hasta
  13 de los 14 días de gracia que la retención existe para dar. El
  discriminador correcto no es la fecha sino si **alguien tocó la fila**: un
  apagón es precisamente el caso en que `attempts` sigue en 0.
- **Las dos ventanas de gracia usaban la misma constante contra relojes
  distintos.** Una visita registrada 47 h 59 m tarde conservaba su mensaje por
  un minuto en la creación, y el siguiente ciclo lo cancelaba: justo el mensaje
  que la lógica de creación se había esforzado en salvar. El corte al enviar
  tiene ahora una hora de holgura.
- **El tercer handler no hacía rollback y sus dos hermanos sí.** Si el envío
  falla con un error de base de datos —y el envío escribe a través de la misma
  sesión—, se perdían la fila del mensaje y el estado FAILED mientras el
  seguimiento quedaba PENDING: el siguiente ciclo lo componía y **lo enviaba de
  nuevo**, un SMS duplicado con la exposición que eso conlleva. Ahora registra
  FAILED y renuncia al reintento: enviar dos veces es el peor resultado.
- **Una hora que no existe se guardaba como otra.** En el cambio de horario de
  primavera las 02:30 no existen en Denver, y `replace(tzinfo=...)` no lanza
  error: se convertían silenciosamente en una cita real a las 03:30, y 02:30 y
  03:30 resolvían al mismo instante — con lo que el guard de doble-reserva
  recién añadido leía dos peticiones distintas como un choque. Ahora se rechaza
  con 400. La hora ambigua del cambio de otoño se resuelve al primer paso,
  de forma determinista y documentada.
- **La lista de primitivas de envío no estaba garantizada.** Todo el barrido de
  opt-out depende de que `SENDING_PRIMITIVES` esté completa, y nada lo
  aseguraba: añadir MMS, voz o push habría hecho que el barrido siguiera
  informando "limpio" sobre código que nunca miró — en silencio, porque una
  entrada que falta **quita** trabajo en vez de añadir un fallo. Es el defecto
  original de este fichero subido un nivel. Ahora se afirma lo inverso: todo
  `async def send_*` de `app/services` que haga un POST debe estar declarado.
  Verificado por mutación (renombrar a `send_mms` pone el test en rojo).
- La consulta añadida en v0.47.7 se ejecutaba antes de la salida temprana de
  bandeja vacía.

## [0.47.7] — 2026-08-16

### Corregido — segunda ronda de auditoría independiente (sobre v0.47.6)

Otra vez el mismo patrón, y esta vez lo vi venir: **el arreglo de la ronda
anterior rompió a sus vecinos**. Encontrado por el auditor y reproducido de
forma independiente con una sonda propia y un control limpio.

- **REGRESIÓN (v0.47.6): el `rollback` que evitaba que la tanda muriera se
  llevaba por delante el trabajo de los elementos anteriores.** Las ramas de
  saltar, cancelar y retener no comitean —dependían del commit final—, así que
  cuando un elemento posterior fallaba, un `SKIPPED` terminal volvía a
  `PENDING` y, lo serio, un seguimiento retenido perdía **su contador y su
  aplazamiento de un día**: no avanzaba nunca hacia rendirse y se quedaba a la
  cabeza de la cola en cada ciclo. Exactamente la inanición que el rollback
  venía a evitar, trasladada a los vecinos.
  Ahora cada elemento persiste su resultado en un `finally`, así que las diez
  salidas anticipadas del bucle quedan cubiertas por construcción — que es la
  clase de cosa que este repo olvida justo en una de ellas.
- **REGRESIÓN (v0.47.6): un envío recién fallido se volvía invisible.** Mi
  ranking sacaba la fila fallida de **todos** los campos, no solo del criterio:
  la bandeja mostraba el mensaje anterior, `last_message_at` se congelaba en su
  hora y el lead se caía de la ventana de actividad reciente. Ahora hay dos
  consultas con dos propósitos: la de **mostrar** devuelve el mensaje más
  nuevo, fallos incluidos; la de **decidir si se debe respuesta** mira el más
  nuevo que llegó a alguien.
- **La gemela de `leads.py` seguía discrepando.** Ya compartía la regla de los
  envíos fallidos, pero ignoraba `inbox_handled_at`, así que las dos pantallas
  seguían contradiciéndose para cualquier lead ya atendido — mientras su
  docstring afirmaba reflejarlas. Ahora implementa las dos mitades.
- **Un corte del worker devolvía la ráfaga por la puerta de atrás.** La ventana
  de gracia solo protegía la *creación*: con el worker caído una semana, los
  tres mensajes post-visita vencían solos y el primer ciclo de vuelta los
  mandaba juntos. La misma regla se aplica ahora también al enviar.
- **El barrido de opt-out se evadía con `getattr`.** `getattr(lead,
  "opted_out_at")` no es ni `ast.Attribute` ni `ast.keyword`, así que el
  detector decía "no comprueba" para una función que sí comprueba. Cerrado y
  con test.

## [0.47.6] — 2026-08-16

### Corregido — hallazgos de la auditoría independiente sobre v0.47.5

Cuatro defectos reales, los tres primeros confirmados ejecutándolos. Dos son
regresiones **mías**, introducidas por los arreglos de v0.47.5.

- **REGRESIÓN (v0.47.5, en producción): un lead desaparecía de la bandeja
  entera.** Mi filtro de outbounds fallidos quitaba filas de un `DISTINCT ON`, y
  `gather_inbox` construye su conjunto de leads con las claves de esa consulta
  (`inbox.py:150`). Un lead cuyo único mensaje es un primer contacto fallido
  —importado de discovery, o tecleado a mano— perdía **todas** sus filas y
  desaparecía de la bandeja: de todas las pestañas, no solo de Pendientes.
  Exactamente el daño que el arreglo pretendía evitar, invertido y peor.
  Ahora la fila se **degrada en el orden**, no se elimina.
- **La gemela en la lista de leads no se actualizó.** `_needs_response_map`
  (`leads.py:221`) hacía la misma consulta sin la regla nueva, y su propio
  docstring decía "Mirrors the inbox's `needs_response`" — ya no. Las dos
  pantallas se contradecían sobre el mismo lead. Ahora comparten una única
  expresión, `inbox.reached_somebody()`.
- **REGRESIÓN (v0.47.5): mi `try` por elemento no hacía rollback**, así que un
  error de base de datos —la clase de fallo que el propio comentario nombra—
  dejaba la transacción abortada, la siguiente iteración moría fuera de todo
  handler, y el contador de rendición se escribía en la transacción condenada y
  se perdía: la fila mala se quedaba PENDING, la primera por `scheduled_for`, y
  **mataba de hambre toda la cola de seguimientos de ese inquilino** en cada
  ciclo, en silencio. Mi test usaba `RuntimeError`, que nunca toca la sesión, así
  que pasaba sin cubrirlo. Ahora hay rollback, relectura de la fila y commit del
  contador — y el bucle itera por **id**, porque un rollback expira los objetos
  ORM y hasta leer `fu.id` después dispara una carga síncrona que revienta.
- **El acuse de re-alta no se reintentaba.** El mismo handler cubría STOP y
  START. Para STOP no reintentar es correcto; para START es al revés: la persona
  lo ha pedido, ha consentido por definición, y se quedaba creyendo que se había
  vuelto a suscribir al silencio.

### Corregido — estabilidad de la suite

- **`test_webhook_e2e.py` fallaba al azar** (medido por el auditor: 1-2 de cada
  10 ejecuciones). Construía teléfonos con letras (`34666E2E` + sufijo hex en
  mayúsculas) y comprobaba que lo guardado coincidía con lo enviado, pero el
  canonicalizador de identificadores reescribe algunos de esos valores. Sufijos
  solo de dígitos.
- **`test_shared_resources.py` solo podía correr en un portátil.** Tres URLs con
  host, puerto y contraseña fijos (`localhost:5434`): verde en local y en CI
  —donde Postgres está en 5432— ni siquiera conectaba. Lo encontró el primer CI
  sobre estos commits. Ahora deriva del `DATABASE_URL` configurado.

### Corregido

- **Una hora sin zona anulaba la comprobación de solapamiento.** `book_slot`
  aceptaba un `start_time` naive y lo pasaba tal cual; comparar un naive con las
  horas con zona que ya están en la agenda da simplemente `False` —sin error—,
  así que el guard de doble reserva se ejecutaba, no encontraba nada y confirmaba
  dos visitas en la misma media hora (**verificado**: 201 en lugar de 409).
  `create_manual_event` sí resolvía el reloj de pared contra la zona de la
  oficina desde siempre; la ruta hermana no. Extraído a `_resolve_wall_clock` y
  usado por las dos.
  Nota: en modo simulado el valor acababa guardándose bien porque el Cal.com
  simulado localiza con `timezone_name`. Contra un Cal.com real se envía
  `start_time.isoformat()`, que sin zona va **sin offset** y queda a
  interpretación del proveedor; no hay cuenta viva para verificar ese extremo.
- **Una visita retro-fechada disparaba la secuencia entera de golpe.** El guard
  de "solo si sigue en el futuro" existía para el recordatorio y no para los tres
  post-visita, así que una visita con fecha pasada —una que se registra después
  de hacerla, un año mal tecleado, una fecha que el agente de voz oyó mal— los
  programaba los tres ya vencidos y el siguiente barrido mandaba "¿qué tal fue?",
  el recordatorio y "hay pisos nuevos" con segundos de diferencia.
  **Corregido con ventana de gracia, no con "solo futuro"**: la primera versión
  de este arreglo tiraba también el mensaje de una visita de hace exactamente
  24 h, que es justo cuando debe salir. Un test existente lo señaló. Ahora se
  admite **un** mensaje vencido, por menos que el hueco más pequeño de la
  cadencia — lo que hace imposible que sobrevivan dos, que es la ráfaga.
- **El barrido de opt-out se podía satisfacer con un docstring.** El detector
  hacía `"opted_out_at" in ast.dump(node)`, y `ast.dump` incluye las cadenas de
  texto: un docstring o un log que mencionara el campo certificaba a esa función
  como cuidadosa para siempre — cuanto mejor documentabas por qué tu emisor era
  seguro, más seguro era que el barrido dejara de mirarlo. Ahora exige un acceso
  real al atributo. Y las exenciones pasan de nombre suelto a `ruta::función`,
  porque un nombre suelto eximía a esa función **en todos los módulos**. El
  detector tiene ahora su propio test con dos funciones escritas para engañarlo.
  Barrido actual: 71 funciones alcanzan un envío, 0 sin guard, 5 exenciones.
- **El changelog prometía algo que el producto bloquea.** La entrada de STOP
  decía que los mensajes del lead siguen llegando "para que le contestes en
  persona", pero el compositor devuelve 409 a quien se dio de baja — que es lo
  correcto. Reescrita: llegan a la bandeja, el lead queda marcado, y llamar es
  otro consentimiento y decisión del asesor.

## [0.47.5] — 2026-08-16

### Corregido

- **Un envío fallido dejaba de existir.** `send_human_message` marcaba el mensaje
  `FAILED` y nada más: `next_attempt_at` quedaba en NULL, que no casa con ninguna
  rama de la consulta del barrido de reintentos, así que la respuesta del asesor
  se quedaba en la base de datos para siempre. La ruta automática siempre estuvo
  encolada; la humana nunca. Ahora pasa por `schedule_retry`.
- **El barrido de reintentos ignoraba el opt-out de los mensajes humanos.** El
  lead solo se cargaba `if message.sender == MessageSender.AGENT`, así que para
  un mensaje escrito por una persona `lead` era `None` y *ni* la puerta de
  consentimiento *ni* el bloque de opt-out llegaban a evaluarse: un mensaje
  encolado antes de que alguien respondiera STOP se entregaba igualmente después.
  El lead se carga siempre; la distinción por remitente vive ahora en la puerta
  de consentimiento, que es la que trata de envíos automáticos.
- **Un error transitorio reenviaba seguimientos ya entregados.** La elección de
  canal quedaba fuera de todo `try` por elemento y la tanda tenía un único commit
  al final, así que una excepción tiraba las filas que decían "ya enviado" y el
  siguiente ciclo los mandaba otra vez, con exposición TCPA por mensaje. Ahora se
  hace commit tras cada despacho y un lead ilegible cuesta un seguimiento, no la
  tanda.
- **Un intento fallido contaba como respuesta en la bandeja.** La fila OUTBOUND
  fallida pasaba a ser el mensaje más reciente del lead, así que `needs_response`
  se apagaba y quien seguía esperando desaparecía de Pendientes.
- **El compositor limpiaba la caja aunque no se hubiera enviado.** Ya leía
  `outbound_status` el backend pero el frontend no lo miraba; ahora avisa de que
  quedó en cola.

## [0.47.4] — 2026-08-16

### Corregido

- **Dos clientes ya no pueden reservar la misma media hora.** Al ofrecer huecos
  se consultaba la agenda ocupada; al **reservar** no se consultaba nunca. No
  era una carrera: la segunda petición podía llegar un minuto después, ver el
  mismo calendario libre, y las dos personas recibían confirmación para la
  misma hora — con el agente citado en dos casas a la vez y alguien esperando
  en una puerta a la que no va nadie. Vale también para los eventos manuales,
  que es donde el agente bloquea sus propios compromisos.

## [0.47.1] — 2026-08-15

### Corregido

- **La baja se pega ahora a la persona, no al número escrito.** `+17205558217`
  y `720-555-8217` son el mismo teléfono y eran dos contactos distintos, así que
  un STOP guardado contra uno no decía nada del otro: bastaba con volver a dar
  de alta a alguien copiando el número de tus notas con otro formato para que el
  sistema le escribiera. Sin mala intención — un guion basta. El normalizador ya
  existía para esto; esta ruta no lo usaba.
- **El aviso de la ficha decía lo contrario de lo que hace el sistema.** Ponía
  "puedes escribirle personalmente", que dejó de ser cierto en 0.47.0. Y si lo
  intentabas, el compositor mostraba el error crudo de la API en inglés dentro
  de un panel en español. Ambas cosas corregidas.

## [0.47.0] — 2026-08-14

### Corregido

- **Nadie recibe un mensaje después de pedir que paremos, tampoco escrito a
  mano.** Todas las rutas automáticas ya lo respetaban —el barrido de
  seguimientos, el reintento de envío, la puerta de despacho, la reserva de
  visitas—. La única que no era **la del agente escribiendo en el panel**, que
  es justo la que más se usa con un cliente que se ha quedado callado, y a veces
  se ha callado porque pidió la baja. Medido antes de arreglarlo: un contacto
  que escribió STOP recibía el mensaje, con HTTP 200 y todo. Ahora sale un 409
  explicando por qué y **no se escribe nada**. Llamarle por teléfono es un
  consentimiento distinto y una decisión que no toma este sistema.

## [0.46.4] – [0.46.14] — 2026-08-14

Una sola línea de trabajo, diecinueve rondas de auditoría adversarial sobre
ella. Sin funciones nuevas: es lo que hacía falta para que 0.45.0 fuese cierto.
Cada versión intermedia está en `git log --oneline v0.46.3..v0.46.14` con su
razonamiento completo; esto es lo que cambió para quien usa el producto.

### Corregido

- **Un mensaje entrante ya no se pierde por un dato con mala forma.** Un valor
  demasiado largo o inesperado —de un mensaje, de una llamada de voz o del feed
  de propiedades— tumbaba la escritura que lo guardaba, y en las rutas de
  entrada esa escritura era **la misma transacción que guardaba lo que dijo el
  cliente**. Como el proveedor reenvía lo mismo, cada reintento fallaba igual y
  el mensaje se perdía del todo. Ahora se ajusta antes de llegar, y lo que no se
  puede leer se descarta con aviso en vez de adivinarse.
- **Dos personas distintas ya no pueden acabar siendo el mismo contacto.** Un
  identificador demasiado largo se recortaba, así que dos direcciones iguales al
  principio se resolvían al mismo lead. Ahora conserva una cabeza legible más un
  resumen criptográfico: cabe, es estable, y dos personas siguen siendo dos.
- **Una visita agendada ya no puede quedar fuera del CRM.** La reserva se crea
  primero en Cal.com, así que un fallo al registrarla dejaba una cita real en el
  calendario del agente que la aplicación no podía ni listar ni cancelar. Si la
  referencia que devuelve el calendario no se puede guardar, la reserva **se
  deshace**: no se puede recortar (una referencia acortada no identifica ninguna
  cita) ni ignorar (quedaría una cita real e invisible).
- **Un rango de presupuesto al revés es imposible** (`CHECK` en Postgres,
  migración 030): no emparejaba con ninguna casa y la página lo contaba como
  "no hay nada disponible" en vez de "esta ficha está rota".
- **`"450k"` valía 450 y `"450,000"` valía 450.** La lectura de cifras estaba
  escrita para formato europeo en una correduría de Colorado, y al arreglarla se
  perdieron los sufijos. Ambos casos salían positivos, en rango y no invertidos:
  invisibles para todos los controles.
- **Un anuncio con un dato mal formado ya no atasca el feed MLS entero.** La
  página se escribe en una sola sentencia con su cursor, así que un registro
  malo hacía que cada ejecución posterior volviera a pedir la misma página y
  fallara igual, para siempre.
- Un código postal solo se guarda si el campo **es** un código postal. Adivinarlo
  a partir de texto libre guardaba números de portal o de parcela como si fueran
  el código, en silencio.

## [0.46.3] — 2026-08-14

### Corregido

- **Ningún texto puede volver a costar un mensaje.** Nueve rondas encontraron
  este mismo fallo campo a campo: primero `urgency`, luego `zone`, luego el
  nombre en un constructor **dos líneas debajo** de otro que acababa de
  arreglar, luego el asunto de un correo. Cada arreglo era correcto y cada uno
  cubría el campo que yo estaba mirando. Ahora el recorte vive en el modelo
  (`@validates`), así que vale para toda escritura del ORM — incluidas las que
  nadie ha escrito todavía— y un test **recorre la tabla** y falla si aparece
  una columna nueva sin cubrir. Postgres no recorta: rechaza, y en estas rutas
  el rechazo tira la transacción que guardaba lo que dijo el cliente.
- **Una redelivery de VAPI ya no deshace la corrección del agente.** Al pasar la
  ruta de voz por `merge_budget` cambié sin querer su semántica: pasó de
  «rellena huecos» a «un rango completo manda». Como esa función corre en cada
  entrega, incluidas las repetidas, el agente corregía 100k-900k a 300k-400k,
  VAPI reenviaba la misma llamada y su corrección desaparecía sin rastro.
- `"450kk"` y `"450 mil millones"` se descartan en vez de salir mil o un millón
  por debajo.

## [0.46.2] — 2026-08-14

Lo mismo que 0.46.1, en la ruta que no había visitado.

### Corregido

- **Una llamada de voz con datos imposibles ya no borra su propia
  transcripción.** El agente de voz devuelve `structuredData` —su lectura de lo
  que dijo la persona por teléfono— y se aplicaba con `int(float(val))` como
  única defensa, dentro de la transacción que guarda la transcripción. De siete
  cargas hostiles, seis destruían la transacción y la séptima reventaba con
  `OverflowError` sin que nadie lo capturase. Es exactamente el fallo de 0.46.1
  en la ruta a la que el arreglo no llegó.
- **`"450k"` valía 450.** Al arreglar el separador de miles quité las letras, y
  con ellas los sufijos: `450k`→450, `1.2M`→1.2, y `"entre 300k y 500k"`→300500,
  un número **inventado** juntando dos. Positivos, en rango y no invertidos, o
  sea invisibles para todo lo demás. Ahora se leen los sufijos y un texto con
  dos números se descarta en vez de adivinar.
- **`NaN` ya no puede llegar a la base.** Pasa cualquier comparación (`nan < 0`
  es falso, y `nan > máximo` también), Postgres lo guarda tan tranquilo, y luego
  cualquier comparación contra él **lanza** — dentro de la transacción del
  mensaje. Entraba porque `json.loads` acepta `NaN` a secas.
- **Textos recortados a lo que cabe.** `urgency` son 40 caracteres y un agente
  de voz contesta "as soon as possible, ideally within the next thirty days",
  que son 52. Postgres no recorta: rechaza.

Todo esto vive ahora en `app/services/lead_fields.py`, un único sitio para las
dos rutas, porque el error que este código lleva repitiendo es poner el guarda
en el camino que uno está mirando.

## [0.46.1] — 2026-08-14

Corrección de una regresión que introduje en 0.46.0, y de las graves.

### Corregido

- **Un mensaje entrante ya no se pierde por un presupuesto imposible.** Las
  restricciones de 0.46.0 cerraron un problema silencioso, pero el clasificador
  lee texto libre con un modelo de lenguaje y no tenía límites: una extracción
  negativa llegaba a la restricción, la restricción abortaba la transacción, y
  esa transacción era la que guardaba **el mensaje del cliente**. Como el mismo
  mensaje se reintenta igual, los reintentos del proveedor fallaban idénticos y
  el mensaje se perdía del todo. Ahora un valor que la base no admitiría se
  descarta antes —en el validador y otra vez en el punto de escritura— y se
  pierde un campo en vez de una conversación.
- **`"450,000"` valía 450.** La conversión de números estaba escrita para
  formato europeo (`1.200.000,50`) y esta es una instalación en Colorado. El
  resultado era positivo, en rango y no invertido, así que pasaba todos los
  controles: el cliente quedaba emparejado con casas mil veces más baratas de
  lo que pidió. Ahora se detectan las dos convenciones.
- **Un mínimo viejo ya no bloquea para siempre el rango que el cliente acaba de
  decir.** El arreglo de la ronda anterior descartaba las dos mitades si el
  resultado quedaba al revés; con un mínimo obsoleto de 500 000, un cliente que
  dijera "entre 100 y 300" no se guardaba nunca, repitiéndolo las veces que
  fuera. Un rango completo en un mensaje es el cliente diciendo su presupuesto,
  y manda.
- La consola ya no puede listar el mismo seguimiento dos veces.

## [0.46.0] — 2026-08-14

Seis rondas de auditoría adversarial sobre la consola de llamada. No hay
funciones nuevas: es lo que hacía falta para que lo de 0.45.0 sea cierto.

### Corregido

- **Un rango de presupuesto al revés ya no es posible.** Tres rondas seguidas
  encontraron el mismo defecto en una ruta distinta cada vez —la consola, el
  editar, el alta— y una cuarta lo escribía desde lo que el modelo de lenguaje
  extrae de la conversación, sin comprobar nada y para siempre. Eso ya no es un
  descuido de una ruta: es una regla guardada en el sitio equivocado. Ahora está
  en la base de datos (`ck_leads_budget_not_inverted`, `ck_leads_budget_non_negative`,
  migración 030), donde vale para todo el que escriba, incluido el que aún no se
  ha escrito. Importa porque un rango invertido no empareja con ninguna casa y
  `/matches` lo cuenta como «no hay nada», no como «esta ficha está rota».
- **La página del mal día ya no se queda en blanco el mal día.** La lista de
  retenidos mezcla consentimientos pendientes y envíos fallidos en una sola
  página. Una caída del proveedor marca cientos de fallos de golpe, todos más
  nuevos que la retención que espera desde ayer, así que se quedaba con todos
  los huecos. Cada tipo tiene ahora su cupo, y `limit` vuelve a significar lo
  que dice.
- **Una visita no se reserva antes de comprobar que la casa existe.** En la ruta
  de Cal.com la reserva se creaba antes de guardar la fila, así que un anuncio
  retirado por el MLS entre que se pinta la tarjeta y se pulsa el botón dejaba
  al cliente con una invitación real de una visita que el CRM nunca registró.
- **Reservar desde una propiedad propuesta ya refresca la lista de visitas**, y
  dos refrescos simultáneos no se pisan. La lista quedándose vacía es lo que
  hace que alguien reserve otra vez, y una segunda reserva es una segunda
  invitación real en el correo del cliente.

## [0.45.0] — 2026-08-14

La consola de llamada. Natalia y Robbie ya tienen llamadas; lo que aprendían en
ellas moría en una libreta, y esa libreta es la razón de que el emparejador de
propiedades, el scoring y el nurture —todos construidos— no giraran.

### Añadido

- **Panel de registro de llamada** en cada ficha de contacto. Toques, no
  escritura, con presupuesto de **un minuto**: si marcar cuesta más, no se
  marca, y el dato que llegue es peor que ninguno. Lo que se registra va **al
  `Lead`**, que es de donde ya leen `match_properties_for_lead` y
  `compute_lead_score`.
- **Guardar ejecuta, no archiva.** Cada resultado dispara una única acción:
  programar el seguimiento, o cancelar todo lo pendiente cuando la persona dice
  que ya tiene agente o pide que no la contacten.
- **Consentimiento verbal registrable**: si lo pidió en la llamada, queda
  escrito con fecha y quién lo marcó. De una sola escritura — el primer
  registro es el que se mostró o se habló.
- **Página `/console` — Hoy**: llamadas y correos por hacer, seguimientos
  **retenidos por falta de consentimiento** (antes solo visibles en los logs) y
  calientes sin tocar. Un lead no aparece dos veces.
- **Nuevos: `call_logs`** (con RLS y GRANT explícito), `leads.preferred_channel`,
  `visits.property_id`, `follow_ups.call_log_id` + `UNIQUE(call_log_id, kind)`.
  Migración 029, aditiva y reversible.
- **`enqueue_after_call()`** — los cuatro tipos de seguimiento existentes
  colgaban de una visita, así que el caso más común tras una llamada
  (interesado, todavía no) no tenía forma de seguirse.

### Decisión de cumplimiento

**Solo SMS tiene emisor automático.** El correo y la llamada se atienden a mano
desde la lista de Hoy, y eso está escrito en el código:

- No hay proveedor de voz, y una llamada automática a un móvil es exactamente
  lo que castiga TCPA.
- `services/email.py` no manda cabecera de baja ni dirección postal, y
  `optout.py` no reconoce el correo: correo comercial automático sin baja
  operativa es una violación de CAN-SPAM.

Ofrecer un canal que el sistema no puede honrar es el patrón del campo de
perfil muerto que este repositorio ya ha pagado cuatro veces. Mejor decir en
voz alta cuáles dos son manuales.

**La preferencia estrecha, nunca abre**: reordena los canales permitidos y
jamás salta la retención por falta de consentimiento ni el opt-out.

### Corregido

- Los seguimientos sin emisor automático se excluyen **en SQL**, no en el
  bucle: permanentemente pendientes y siempre los más antiguos, habrían ocupado
  la cabeza de cada lote y matado de hambre a los que sí se pueden enviar.

## [0.44.0] — 2026-08-13

Primera cara pública del producto: la landing de la agencia, en la raíz del
dominio. Portada del diseño aprobado en Claude Design, con las correcciones que
un anuncio de una inmobiliaria con licencia necesita para poder publicarse.

### Añadido

- **Landing pública en `/`** — tipografía editorial (Instrument Serif/Sans,
  autoalojadas en el build; sin peticiones a terceros), paleta cálida propia
  con prefijo `ln-` que no puede tocar ni un píxel del panel, y versiones
  completas en inglés y español con el selector de idioma de siempre.
- **Formulario de asesoría de 15 minutos** que entra por el **mismo camino de
  captura que `/contact`**: mismo endpoint, mismo honeypot, mismo Turnstile y
  la misma casilla de consentimiento TCPA, cuyo texto se guarda exactamente
  como se mostró. El diseño original no traía casilla; sin ella no se puede
  escribir a nadie por SMS.
- **Todo dato factual sale de la configuración** (`NEXT_PUBLIC_LANDING_*`):
  nombres, brokerage, dirección, teléfonos, años de oficio y testimonios. Lo
  que no está configurado **no se muestra** — su sección desaparece entera. Un
  teléfono o un testimonio inventados en el anuncio de una inmobiliaria no son
  un marcador de posición, son publicidad engañosa.
- **Test que impide repetir el fallo de la v0.43.0**: comprueba que cada
  variable de la landing está documentada en `.env.example`, declarada como
  `ARG` **y** como `ENV` en el Dockerfile, y pasada por `docker-compose`.
  Faltando cualquiera de las cuatro, Next la incrusta vacía en el build y la
  página sale en blanco mientras el `.env` parece correcto.

### Cambiado

- **La raíz `/` ya no redirige al panel.** Es la landing. El personal entra por
  `/login`, que sigue llevando a `/leads`; hay un enlace discreto en el pie.
- El `landing_variant` de atribución marca los leads que llegan por esta página,
  para poder comparar de dónde vienen los que sí agendan.

## [0.43.0] — 2026-08-12

Al planear cómo activar Turnstile resultó que no estaba apagado: estaba **mal
cableado y fallando abierto**. Y no era un caso aislado.

### Corregido
- **18 ajustes documentados que el contenedor no podía leer nunca.**
  `docker-compose.yml` enumera ~60 variables a mano y faltaban dieciocho:
  `TURNSTILE_SECRET` (el captcha aceptaba todo sin verificar, indistinguible por
  fuera de uno que funciona), **todo el bloque de Cal.com** (el calendario de
  producción era simulado y no se podía cambiar), `CORS_ORIGINS`,
  `DEFAULT_TIMEZONE` — el ajuste del bug de horario que arreglamos hace dos
  versiones, inconfigurable — y `LOG_LEVEL`, que el ROG tenía puesto y se
  ignoraba. `RESO_PAGE_SIZE` además divergió cuando un fix llamado *"align RESO
  replication with the real MLS Grid contract"* subió el default en el código y
  no tocó compose: la alineación nunca llegó a una instalación real.
- **`test_compose_env.py`**: falla si un ajuste documentado no se pasa, si un
  default de compose contradice al código, o si un secreto recibe un valor por
  defecto en vez de impedir el arranque. Escribiendo el bloque me equivoqué en
  dos defaults **de memoria** y el test los cazó antes del commit.
- **Turnstile activable de verdad**: `/api/v1/health` dice ahora
  `captcha: on|off`, el `remoteip` deja de mandar la IP Docker del frontend
  cuando no hay cabecera de proxy, hay tests de la llamada real —incluido el
  **fallo cerrado** por red, que estaba escrito y nadie probaba—, el instalador
  pregunta por las dos claves, y `docs/` explica el procedimiento y **el orden**
  (la clave pública primero: al revés se pierden todos los leads).
- **WhatsApp explícitamente deshabilitado** (`WHATSAPP_ENABLED=false`). El
  ajuste anterior era una trampa: `WHATSAPP_SIMULATED` controla el envío **y**
  la verificación HMAC de entrada, así que obedecer la regla vieja habría
  devuelto 403 a todo lo entrante hasta que Meta desactivara la suscripción. El
  arranque se niega ahora en esa combinación, un canal deshabilitado responde
  404 en vez de crear leads, y el aviso permanente se limita a instalaciones que
  usen el canal.

### Cambio visible
`APP_NAME`: el `.env` del ROG pide "Eko AI Inmobiliario" y llevaba tiempo
ignorado. Ahora toma efecto (solo en `/api/v1/health` y la raíz).

526 tests (eran 507). 13 mutaciones, 13 muertas.

## [0.42.4] — 2026-08-11

Ronda 6 de auditoría adversarial, la más productiva: siete defectos, dos
críticos y ambos introducidos por los arreglos de la ronda 5.

### Corregido
- **Reabrí un agujero y borré el test que lo cazaba**: el consentimiento se
  podía plantar en cualquier lead llegado por email, porque su identificador
  **es** la dirección. Restaurado y con su test.
- **Un desconocido podía destruir un consentimiento genuino**: permitir
  refrescarlo sonaba bien ("uno genuino cura uno falso") pero funciona igual al
  revés, y el registro genuino es la única prueba del broker. Se escribe una vez.
- **El guard de "visita ya pasada" estaba en la rama muerta**, así que el
  recordatorio salía igual días después de la visita.
- **Un nombre de contacto en blanco atascaba el worker**: `" ".split()[0]`
  lanzaba IndexError fuera del `try` por fila, el lote nunca commiteaba y el
  proveedor recibía el mismo SMS en cada ciclo sin registrar ninguno.
- **`baja` y `alta` fuera de las palabras clave**: "¿planta baja o alta?" es de
  lo más común que pregunta una agente bilingüe. Y con ellas cambió el texto de
  confirmación, que decía "Responde ALTA" — ahora hay un test que lee las
  palabras que el mensaje nombra y exige que funcionen.
- Un STOP repetido borraba la fecha de la **primera** baja.
- La cola de reintentos descartaba también el mensaje **escrito a mano** por la
  agente, que es justo el que sí puede enviarse.
- Dos leads que comparten dirección podían fusionarse sin test que lo impidiera.

504 tests. 47 mutaciones, 47 muertas.

## [0.42.3] — 2026-08-11

Rondas 5 y 6 de auditoría adversarial. Tres defectos más, dos introducidos por
los arreglos de la ronda anterior.

### Corregido
- **"Sí" levantaba la baja.** `yes`, `si` y `sí` estaban en las palabras de
  alta, y son la palabra suelta más común que envía una persona: quien se había
  dado de baja y respondía "Sí" a cualquier cosa se resuscribía solo. CTIA
  exige START y UNSTOP; no exige palabras de asentimiento, y leer asentimiento
  como reconsentimiento es exactamente al revés.
- **Un recordatorio "tu visita es mañana" llegaba días DESPUÉS de la visita**:
  la retención diaria convertía un mensaje suprimido en uno equivocado.
- **La guarda de consentimiento preguntaba mal**: "¿se ha alcanzado a este lead
  por otro canal?" — un lead **importado** responde que no, porque las filas de
  una exportación de contactos no tienen ninguna conversación. Ahora pregunta si
  **este formulario creó** el lead.
- El recordatorio previo ya no se dispara para una visita marcada COMPLETED.
- El plazo de gracia de una retención se cuenta en retenciones, no desde
  `created_at`: un seguimiento de 7 días **nace** una semana antes de vencer.

494 tests. 40 mutaciones, 40 muertas.

## [0.42.2] — 2026-08-11

Rondas 4 y 5 de auditoría adversarial, esta vez apuntando a **los arreglos** de
la ronda anterior en vez de al código original. Encontraron cuatro defectos
vivos; dos permitían que un mensaje automático llegara a quien había dicho STOP.

### Corregido
- **La revocación duraba exactamente un turno.** La intercepción cazaba el
  mensaje que *contenía* la palabra, y nada cazaba el siguiente: el lead decía
  STOP, recibía la confirmación, escribía cualquier cosa al día siguiente y el
  modelo le contestaba. Ahora su mensaje se guarda y llega a la bandeja, pero
  responde una persona.
- **La cola de reintentos entregaba lo que ya estaba encolado** cuando llegó la
  baja. La puerta ahora también está en el punto de despacho.
- **El plantado de consentimiento solo estaba medio cerrado**: fallaba para todo
  lead cuyo identificador *es* un email. El consentimiento solo puede
  registrarlo un envío que **creó** el lead, o uno sobre un lead creado por este
  mismo formulario y nunca alcanzado por otro canal.
- **"Retenido por consentimiento" significaba "cancelado"** en silencio:
  `SKIPPED` es terminal. Ahora se reintenta a diario y se abandona a los 14 días.
- Mi propio tope de cuerpo **rompía la importación de ficheros** (25 MB
  documentados), dejaba el 413 **fuera de CORS** y respondía dos veces en
  cuerpos troceados.
- El techo global se cobraba **después** de resolver el tenant, así que rotar la
  cabecera de IP permitía consultas ilimitadas a la base.
- `cancelar` y `eliminar` dejan de ser palabras de baja: `CANCEL` es del estándar
  CTIA y se queda, pero sus cognados en español no los exige nadie y son lo que
  un cliente bilingüe escribe sobre **una visita**.
- Los teclados de móvil sustituyen comillas y puntos suspensivos: `stop…` y
  `“STOP”` ahora se reconocen.
- El panel **muestra** al lead dado de baja, y la insignia dice "Dado de baja"
  en vez de "AI agent active", que afirmaba algo falso.

489 tests (eran 477). 35 mutaciones, 35 muertas.

## [0.42.1] — 2026-08-11

Dos auditorías independientes sobre v0.42.0. Entre las dos, seis defectos — y el
peor no estaba en el código nuevo, sino en la frase que el código nuevo guarda
como registro legal.

### Corregido
- **STOP no hacía nada, y además invertía la puerta.** El texto del formulario
  promete en los dos idiomas "responde STOP para darte de baja". Como
  `may_send_automated` cuenta cualquier mensaje entrante como contacto iniciado
  por el consumidor, y STOP **es** un mensaje entrante, enviarlo pasaba un lead
  correctamente bloqueado a **enviable**. Ahora: columnas
  `opted_out_at/_channel/_keyword`, reconocimiento por palabra clave (no por
  LLM), la puerta lo consulta **primero** y suprime **todos** los canales
  automáticos incluido el email (más amplio de lo que exige la ley, a
  propósito: "para" significa para, y el agente puede seguir escribiendo a
  mano), una sola confirmación sin llamar al modelo, y `ALTA`/`START` para
  volver.
- **Dar de baja a una agencia metía sus leads en otra.** Una clave de
  formulario que no casaba con ninguna ruta caía al fallback de un solo tenant.
- **Se podía plantar consentimiento en un lead ajeno** conociendo su email.
- **El honeypot respondía antes del límite** y no había tope de cuerpo: 43 MB
  aceptados y parseados. Ahora 256 KB, medidos en ASGI.
- **El techo global se gastaba antes del captcha**, así que 60 peticiones sin
  token dejaban a toda la plataforma sin captación 10 minutos.
- **Turnstile no se podía activar**: no existía el widget, así que poner la
  clave rompía el formulario. Widget añadido y clave pública cableada al build.
- El 422 distinguía claves vivas de muertas (oráculo de enumeración).
- Un seguimiento se descartaba en vez de reencaminarse al canal que el lead sí
  había iniciado.

474 tests (eran 454). 28 mutaciones, 28 muertas.

## [0.42.0] — 2026-08-11

**La puerta de entrada para tráfico frío.** Hasta ahora un desconocido que veía
un vídeo no tenía forma de entrar al sistema: todos los canales exigen que ya
tenga el teléfono o el email de la agencia. `POST /api/v1/public/leads` y la
página `/contact` son esa puerta, y además guardan **de qué vídeo vino cada
lead**, que es lo que permite preguntar cuáles de N vídeos produjeron una cita
en vez de mirar visitas.

### Añadido
- `POST /api/v1/public/leads` — sin autenticación, con honeypot, límite de
  5/IP/10 min y **techo global de 60/10 min**, y Turnstile opcional y
  fail-closed (`TURNSTILE_SECRET`).
- Página pública `/contact` con captura de UTM, casilla de consentimiento y
  honeypot. La casilla **envía el mismo texto que muestra**.
- Canal `web` en `channel_routes`: la clave del formulario decide la agencia,
  con la misma tabla que decide de quién es un SMS entrante. Fallback de un
  solo tenant, así que una instalación con una agencia no configura nada.
- Migración `027_lead_consent`: `consent_at`, `consent_text`, `consent_ip`,
  `consent_user_agent`. Cuatro columnas y no una marca de tiempo, porque TCPA
  exige poder demostrar **a qué** consintió la persona.
- `may_send_automated()` — el worker de seguimiento no envía SMS ni WhatsApp
  automáticos a quien no consintió por escrito ni nos escribió él primero por
  ese canal. El email no pasa por la puerta (CAN-SPAM, no TCPA).
- `docs/public-capture-form.md`.

### Corregido
- El compositor del dashboard **y** el worker de seguimiento elegían la
  conversación activa más reciente de cualquier canal y se la daban al
  despachador. Para un lead de formulario ésa es la de canal `web`, por la que
  no se puede enviar nada: el botón de responder fallaba y cada seguimiento
  quedaba marcado FAILED. Ahora eligen un canal que pueda alcanzar al lead.
- El Inbox etiquetaba **"SMS pending"** a cualquier canal desconocido, así que
  un lead de formulario aparecía como si hubiera enviado un SMS.
- Los leads capturados se quedaban con score 0 y se hundían al fondo de una
  bandeja ordenada por prioridad.
- El patrón de canal de la API de plataforma era una regex escrita a mano que
  duplicaba `CHANNELS`, de modo que un canal nuevo nacía imposible de crear.

### Límites conocidos
- Esta ruta **no** ejecuta el clasificador LLM: una llamada de pago detrás de
  un POST abierto es una factura que puede disparar cualquiera. Los leads web
  llegan sin `intent`/`zone` y el matching de propiedades no dispara para ellos
  hasta que alguien los rellene.
- Sin auto-respuesta: `web` no está en `SENDABLE_CHANNELS`.

454 tests (eran 416). 17 mutaciones lanzadas, 17 muertas.

## [0.41.2] — 2026-08-09

El tag `v0.41.1` apuntaba al árbol que todavía tenía el bug que ese mismo
release decía cerrar: desplegar desde el tag habría instalado la versión
equivocada. De ahí este número.

**La versión vivía en cuatro sitios y tres estaban rancios.** `install.sh`
escribía `APP_VERSION=0.12.0` en el `.env` que genera, así que una instalación
limpia de v0.41.1 habría servido `{"version":"0.12.0"}` mientras el frontend
decía otra cosa. `docker-compose.yml` traía una segunda copia (`0.39.2`) y
`.env.example` una tercera. Subirlas habría arreglado hoy y roto el siguiente
release igual: ahora la versión sale solo de `backend/app/config.py`.

**El esquema de la API seguía servido con la documentación cerrada.**
`docs_url` estaba condicionado a `DEBUG` y `openapi_url` no, así que
`/openapi.json` devolvía 200 en el host de producción con `DEBUG=false` — el
inventario completo de rutas y modelos que esa puerta existe para no dar.

**Dieciocho ajustes no estaban documentados** en `.env.example`, incluida toda
la pila de voz: quien encendiera las llamadas no tenía forma de saber cómo se
llamaban las claves. Y al documentarlos, tres de los valores los escribí de
memoria en vez de leerlos del código — un host de Ollama que no resuelve en
Linux, un modelo que nadie descarga y la mitad del timeout que el código
permite. Cada uno rompe una instalación nueva de forma que parece un proveedor
caído. Ahora hay un test que compara cada valor del ejemplo con el default real
y exige que ningún ajuste falte.

## [0.41.1] — 2026-08-09

Abrir el panel en la dirección de red local del ROG pintaba un botón de Google
que solo podía terminar en la pantalla "Access blocked" de Google. No había
nada roto: **Google rechaza direcciones IP** como origen en clientes de tipo
Web, así que ese origen no puede ofrecer Google por mucho que se toque la
consola — y la instalación ya tenía un dominio registrado que llega a ella. Lo
que faltaba era que la página lo dijera. Ahora lo dice, y también para Apple,
que tiene la misma restricción y se quedó fallando en silencio en el primer
intento de este arreglo.

**La marca `Secure` de la cookie de sesión ya no sale de `APP_ENV`.** Una
variable de entorno no puede ver cómo llegó una petición, así que forzaba una
sola respuesta para una instalación a la que se entra de dos maneras: por TLS
en su dominio y por http plano en la LAN. Marcada como producción, el navegador
se negaba a guardar la cookie en la LAN y allí no había sesión posible; marcada
como desarrollo, la cookie viajaba sin marcar en el dominio, que sí tiene TLS.
Esa era la razón de que producción siguiera en `development`. Decidiéndolo por
petición desaparece el dilema: **`APP_ENV=production` ya está activo, `/docs`
cerrado, y la LAN sigue funcionando.**

Detalles del camino, porque los encontró la auditoría y no yo:

- `Origin` se usaba como prueba de TLS viniera de quien viniera. La respuesta de
  Google es un POST cross-site que trae `Origin: https://accounts.google.com`,
  lo que no dice nada de cómo llegó el navegador: en una instalación de
  desarrollo por http marcaba la cookie `Secure`, Safari la descartaba, y el
  usuario volvía al login sin ningún error. Ahora solo cuenta el mismo sitio.
- El argumento `request` era opcional con un valor por defecto estricto, así
  que tres sitios de llamada se olvidaron de pasarlo y emitían una cookie que el
  navegador descartaba — un login que responde 200 y falla en la siguiente
  petición. Ahora es obligatorio.
- `NEXT_PUBLIC_API_URL=http://localhost:8000` era configuración muerta que
  nadie lee, y me costó tiempo real durante la verificación del despliegue
  creyendo que el panel apuntaba a la máquina del usuario.
- El instalador nunca escribía la URL canónica, así que el mensaje nuevo habría
  salido sin dirección justo en las instalaciones creadas con él.

## [0.41.0] — 2026-08-09

Rondas 22 a 29. Las rondas 23 y siguientes dejaron de mirar el aislamiento
entre agencias —veintidós rondas ya lo habían recorrido— y miraron si el
producto funciona. Encontraron cosas peores.

**Ningún lead llegado por WhatsApp podía reservar una visita.** Cal.com exige
un email del asistente. Los leads se identifican por `phone` en todos los
canales, y la dirección se derivaba como "el teléfono, si lleva una arroba" —
cierto solo para los leads de email. Contra una cuenta real de Cal.com, toda
reserva por WhatsApp, SMS o voz fallaba: el panel mostraba 503 y quien llamaba
oía "tengo problemas con el calendario". Invisible fuera de producción porque
`CALENDAR_SIMULATED` corta antes de la llamada HTTP.

**Una caída de los LLM no respondía nada.** El webhook contesta 200 igual, así
que el proveedor no reintenta: un lead que escribía a las 11 de la noche
recibía silencio, y nada en el panel lo decía.

**Una respuesta que fallaba al enviarse se perdía.** Cada adaptador de canal es
un único POST. Un 503 de Meta o un 429 de Twilio marcaban el mensaje como
fallido y ahí terminaba: no había reintento ni barrido alguno. Ahora hay uno,
por organización, que espacia los intentos y se rinde en voz alta.

**Una propiedad llegaba al lead sin acreditar a nadie.** Colorado exige nombrar
al corredor listante allí donde una propiedad llega a un consumidor, y el
nombre solo vivía en `raw`, que ninguna respuesta de la API exponía. En el chat
había una línea de cortesía, pero en el *prompt*: una obligación de licencia
dependiendo de que un modelo decidiera repetirla. La lógica se reescribió
cinco veces —una de ellas invertida, acreditando solo cuando ya estaba
acreditado— hasta quedar en tres señales precisas: el título, la dirección o el
precio de esa propiedad.

**Un sync filtrado por ciudad ocultaba el resto del feed, para siempre.** El
filtro se aplica de nuestro lado, así que la corrida veía todos los registros e
importaba unos pocos — y luego adelantaba el cursor compartido más allá de
todos. Un solo `POST /properties/sync?city=Denver` volvía invisible cada
propiedad de Boulder modificada en esa ventana, incluidas las que acababan de
entrar bajo contrato.

Además: cancelar una visita devolvía 500 y la dejaba agendada; la voz reservaba
una hora ya ocupada en vez de ofrecer otra; los huecos se ofrecían por lead, no
por agencia; el arranque se niega si RLS no se aplica con más de una agencia;
los logs ya no son una lista de leads; `docker-compose.yml` ya no trae la
contraseña del rol de RLS; la misma persona por WhatsApp y por email es un solo
lead; y los ajustes que el cliente rellena —horario, saludo, zona horaria—
por fin cambian lo que el agente dice.

Hueco conocido: **no hay rate limiting**. El gasto en bloque está tras
`require_platform_admin`; el coste de LLM por conversación no tiene cuota por
organización.

## [0.40.0] — 2026-08-08

Rondas 14 a 21. Ocho rondas, todas DO-NOT-SHIP, y en casi todas el defecto lo
había introducido el arreglo de la ronda anterior.

**Nadie le había dado calendario propio a las agencias.** SMS, WhatsApp, email
y voz se reformaron para tener identidad por organización; el calendario no, y
ni `channel_routes` ni `agent_settings` tenían dónde ponerlo. Así que la reserva
de la agencia B escribía nombre, email y teléfono de su cliente como asistente
en el Cal.com del operador —donde lo ven los realtors de otra agencia— y sus
reservas tapaban la disponibilidad de la agencia A. Sin atacante y sin
configuración rara: lo hacía la primera reserva real. Invisible en desarrollo
porque `CALENDAR_SIMULATED` corta antes de la llamada HTTP.

El guard que lo impide se escribió mal **tres veces**: la primera solo cubría
instalaciones nuevas (todo piloto que se actualiza ya tiene `CALCOM_API_KEY` en
su `.env`); la segunda preguntaba si había *alguna* credencial, y la global lo
es; la tercera, si existía la fila, y una fila con solo el event type es forma
legal de onboarding. La pregunta correcta —¿la credencial viene de ESTA
agencia?— tardó tres intentos en enunciarse.

**El parser de email, otra vez, y la misma lección.** Quitar los miembros de un
grupo RFC 5322 con nombre impedía *añadir* una dirección y regalaba el poder de
*eliminar* la legítima: `undisclosed:<destinatario real>;, leads@agenciab.test`
borraba al destinatario honesto, la regla de "dos agencias nombradas, rehúsa"
veía un solo dueño, y el lead entraba en la agencia B. Ahora un grupo en
cualquier parte invalida la cabecera entera. Más al fondo: la clave de enrutado
salía de `to`/`cc`, que **escribe quien envía**; cuando el proveedor incluye
sobre, manda el sobre.

**Lo que se paga una vez para toda la instalación, ahora es del operador.**
`/properties/sync` (la licencia de REcolorado) y las cinco rutas de
`/discovery` (Outscraper, Yelp, SerpApi y el presupuesto de LLM) estaban tras
`require_auth`: cualquier miembro de cualquier agencia podía agotar el crédito
del que dependen las respuestas de todas las demás. El frontend oculta esos
controles en vez de dejar que el inquilino descubra un 403.

**El arranque se niega** si RLS no se está aplicando y hay más de una agencia
—antes lo registraba en el log y servía tráfico igual— y también si el número
de agencias no se puede leer, que era la forma silenciosa de desactivar las dos
comprobaciones a la vez.

**Los logs eran una lista de leads.** Volcados de payload entrante, salida del
LLM citando ficheros subidos y números de teléfono, en claro, en un stream que
comparten todas las agencias y que el operador puede exportar. Claves en vez de
valores, longitudes en vez de contenido, últimos cuatro dígitos en vez del
número.

Además: cancelar una visita devolvía 500 y la dejaba agendada cuando el
calendario no estaba configurado (el realtor conduce igual hasta la casa);
`docker-compose.yml` traía por defecto la contraseña del rol de RLS, publicada
en el repositorio, y ahora exige ambas variables; la disponibilidad cargaba en
memoria todas las visitas históricas de la agencia en cada consulta; y los
huecos se desduplicaban por lead, así que dos leads distintos recibían la misma
media hora y ambas reservas prosperaban.

Hueco conocido y documentado: **no hay rate limiting**. El gasto en bloque está
cerrado, pero el coste de LLM por conversación no tiene cuota por organización.
Medirlo por `org_id` es requisito previo a facturarlo.

## [0.39.2] — 2026-08-08

Rondas 12 y 13. Ambas devolvieron DO-NOT-SHIP, y las dos veces el defecto lo
había introducido el arreglo anterior.

**El guard de la ronda 11 leía la columna equivocada.** Preguntaba por
`credential_ref` cuando la pregunta es "¿autenticó esta agencia el mensaje?", y
eso vive en `inbound_secret_ref`. Quedaba inerte justo en la configuración que
más importa —agencia con su propia app de Meta que aún responde por la cuenta
compartida— y rechazaba de más en el caso espejo, tirando leads legítimos.

**La identidad se resolvía por `rows[0]`, ignorando el destino.** Una agencia con
dos números en un canal (solo `(canal, destino)` es único) verificaba el segundo
con el secreto del primero: la firma falla, 403, y el lead se pierde sin rastro.

**El rol de RLS conservaba la contraseña publicada.** La migración 015 lo crea con
`IF NOT EXISTS`, así que pasar `APP_DB_PASSWORD` al contenedor no rotaba nada: la
024 emite el `ALTER ROLE`.

Además: el rechazo por destino ambiguo ya no responde 503 antes de que el
handler pueda rehusar (eso hacía inalcanzable el 200 y filtraba 503-vs-403 a un
atacante sin autenticar); un `tool-calls` sin ruta devuelve la forma que VAPI
sabe leer, en vez de dejar la llamada muda; `DATABASE_URL_BYPASS` llega al
contenedor; y una variable borrada del `.env` después de guardar la ruta ya no
rompe los envíos de esa agencia.

---

## [0.39.1] — 2026-08-08

Cuatro auditorías independientes más (rondas 8–11) sobre lo que la 0.39.0 dejó.
Todas devolvieron DO-NOT-SHIP, y en tres de ellas el defecto lo había
introducido el arreglo de la ronda anterior.

**La clave que firmaba el claim de operador se derivaba de la contraseña de la
agencia.** Quitar `superuser=True` del login por contraseña no servía de nada
mientras el token se firmara con `sha256("eko-auth::" + DASHBOARD_PASSWORD)`:
quien tuviera esa contraseña —la comparte la oficina con quien coge el
teléfono— podía derivar la clave y firmarse el claim, y de paso cualquier `org`.
Ahora `AUTH_SECRET` es obligatoria, mínimo 32 caracteres, y el arranque se niega
sin ella en vez de responder 500 a cada petición con el healthcheck en verde.

**Los tres savepoints hacían flush antes de abrirse.** `begin_nested()`
materializa lo pendiente **antes** de emitir el `SAVEPOINT`, así que el `db.add`
que iba delante corría en la transacción externa: la violación escapaba, la
transacción quedaba inservible y el `commit()` posterior daba
`PendingRollbackError` — un 500 que el proveedor reintenta, perdiendo el lead.
Exactamente lo que la 0.39.0 decía haber arreglado. Diez rondas leyeron por
encima porque el único test del patrón escribía **dentro** del savepoint
mientras el código escribía fuera.

**Un mensaje firmado con el secreto global se archivaba en una agencia
concreta.** Con una sola agencia enrutable, un destino sin mapear caía en ella
— aunque quien firmó fuera el operador y no la agencia. Ahora se rehúsa si esa
agencia usa su propia cuenta de proveedor.

**Dos agencias podían apuntar a la misma credencial**, lo que dejaba a una
firmar mensajes dentro del buzón de la otra. El validador afirmaba impedirlo en
un comentario y no lo comprobaba.

Además: las rutas de plataforma exigen `AUTH_ENABLED`, lista de operadores no
vacía y que el email del token **siga** en ella; `POST /platform/routes` valida
las referencias igual que el PATCH; la denylist se calcula de los campos de
`Settings` en vez de siete nombres a mano; `DELETE /platform/members` no puede
dejar una agencia sin admin (salvo `?force=true`); y los rechazos permanentes de
webhook responden 200 en WhatsApp, email y voz — Meta desactiva un endpoint que
falla, y eso tumbaría el canal para **todos** los inquilinos.

Operación: `APP_DB_PASSWORD` y `APP_DB_ROLE` ya llegan al contenedor (la
migración crea ahí el rol, y sin ellas el rol que guarda la frontera entre
inquilinos nacía con la contraseña publicada en el repo), y el dedup de la
migración 022 funciona aunque el rol no sea superusuario.

---

## [0.39.0] — 2026-08-08

Séptima ronda de auditoría. Tres auditores independientes resolvieron las cinco
sospechas que quedaron abiertas y encontraron doce defectos que ninguna ronda
anterior vio. Todos corregidos, y cada arreglo revertido uno a uno para
comprobar que su test se pone en rojo.

### Cada agencia responde desde su propio número (C3)

El bloqueante que arrastrábamos. La entrada se enrutaba por destino desde hacía
varias rondas, pero la **salida** tenía una sola identidad por canal: un número
de Twilio, un id de WhatsApp, un remitente de Resend. El lead de la agencia B
recibía la respuesta desde el número de la agencia A, contestaba a ese número, y
el resto de su conversación se escribía en el inquilino de A. Sin adversario ni
error de configuración: funcionaba así.

`channel_routes` gana columnas de identidad que guardan el **nombre** de una
variable de entorno, nunca el secreto: las claves siguen en `.env` y la base
solo guarda el mapeo. `PATCH /platform/routes/{id}/identity` las configura y
rechaza nombres que no estén realmente definidos. Una referencia rota **falla en
vez de caer al global** — un fallback silencioso significaría que una errata
envía las respuestas de B desde el número de A, que es el bug original de vuelta.

Nada cambia para la instalación de un solo cliente: sin fila de ruta, se usa
exactamente la configuración de `.env` de siempre.

### Dejamos de perder leads cuando llegan dos mensajes a la vez

Cuatro webhooks simultáneos contra un inquilino nuevo dejaban **un** lead de
cuatro. Los cuatro competían por crear la misma fila `agent_settings`, uno
ganaba, y el `IntegrityError` de los otros destruía una transacción que ya
contenía su lead, su conversación y su mensaje. El manejador lo leía como
duplicado y devolvía **200**, así que el proveedor nunca reintentaba y el log
decía "idempotent skip".

Los cuatro webhooks ahora devuelven 5xx cuando algo falla de verdad. Migración
022: una conversación activa por lead y canal, que el modelo llevaba
documentando sin que nada lo hiciera cumplir.

### Enrutado por todos los destinos, no por el primero

Un lead que escribe a la agencia B con copia a la agencia A tenía todo su hilo
archivado en A, porque se tomaba la primera dirección de `to`. Y en voz, VAPI
manda unas veces el número E.164 y otras el id opaco, así que una ruta mapeada
por número daba **503 a mitad de llamada** en las tool-calls: el asistente no
podía agendar visitas mientras el transcript sí se guardaba bien.

### Acceso de plataforma, que era inalcanzable

El claim `su` solo lo emitía el login por contraseña compartida, y la propia
documentación recomienda ponerle una cadena aleatoria que nadie sabe en los
despliegues con Google. En esa configuración era **imposible dar de alta una
segunda agencia**. `PLATFORM_ADMIN_EMAILS` nombra a los operadores reales.

También: un email permitido por dominio sin fila en `allowed_users` entraba como
miembro de la agencia 1; la org demo (pública) era enrutable; suspender la org 1
encerraba al operador fuera de la ruta que lo deshace; `AUTH_ENABLED=false` con
dos agencias servía la primera a todo el mundo; e invitar como `viewer` daba
permisos de escritura en silencio.

---

## [0.38.0] — 2026-08-07

### Inbound messages are attributed by destination

`channel_routes` maps a destination — Twilio number, WhatsApp
`phone_number_id`, mailbox — to an organization, managed at
`/api/v1/platform/routes`. Before this, every webhook defaulted to the first
organization: a second agency's leads and their entire conversation transcript
were written into the first agency's dashboard, while the real recipient saw
nothing and their follow-ups never fired.

`webhook_org_or_refuse` is the single decision point, deliberately independent
of `AUTH_ENABLED` — routing it through the request resolver meant that with
auth off (the dev and single-customer default) an unmapped destination silently
resolved to the first organization, which is the misfiling the mechanism exists
to stop.

Uniqueness is global per channel, unlike `leads.phone` which is per-org: a
number belongs to exactly one agency, and two claiming it is the ambiguity the
table prevents. Destinations are normalised on write and lookup, since Twilio
sends `+1555…`, a form post may arrive as `1555…`, and an address in mixed case.

SMS, WhatsApp and email are wired. Voice was wired one commit later; its
extractor is still **unverified against a live VAPI account** — there is none —
so it yields nothing on any shape it does not recognise, which makes the caller
fall back or refuse rather than guess an agency.

### Platform operator routes (Fase 2)

Create and suspend tenants, and enter one explicitly. Impersonation is recorded
in `user_activity` *before* the session cookie is issued, so the trail survives
a response that never arrives. Gated by `require_platform_admin`, not
`require_admin` — the latter authorises the admin of *some* organization, and
every client agency has one.

### Fixed

- A suspended or deleted organization kept full read and write access; only its
  background sweeps stopped. Status is now checked per request.
- `/health` had a database round-trip in front of it and hung during an outage —
  the one endpoint whose job is to answer then.
- `TenantMiddleware`'s own 403 and 503 responses skipped CORS, so a browser saw
  an opaque network error instead of a status the dashboard could act on.

## [0.37.0] — 2026-08-06

### Multi-tenant: one installation, many client agencies

The product stops being one deploy per agency and becomes the mother system.
Each client is an `Organization`; `properties` and `sync_state` stay shared
because there is a single REcolorado feed behind one Software Vendor account.

Isolation is enforced by Postgres, not by application discipline:

- `FORCE ROW LEVEL SECURITY` on all nine tenant tables — without FORCE the table
  owner ignores policies silently.
- The request path connects as `eko_app`, a role without `BYPASSRLS`
  (`DATABASE_URL_APP`). Postgres superusers bypass RLS even with FORCE, so
  connecting as the owner would leave every isolation test green while isolating
  nothing. `DATABASE_URL` remains for migrations, login and the workers.
- Default-deny: an unset org resolves to `NULL`, and `org_id = NULL` is never
  true, so a forgotten scope returns zero rows instead of everyone's.
- `WITH CHECK` alongside `USING`, since `USING` alone still permits writing into
  another organization.

`TenantMiddleware` is raw ASGI rather than `@app.middleware("http")`: Starlette's
`BaseHTTPMiddleware` runs the endpoint in a separate anyio task, so a ContextVar
set before `call_next` never reaches it.

`test_tenant_isolation.py` is verified by mutation — five of its seven cases fail
when the app is pointed at a superuser, so it detects the failure mode instead of
asserting that a policy exists.

### Fixed

- The WhatsApp webhook's error handler referenced `parsed.wa_message_id`, which
  does not exist on `ParsedMessage`. It only ran when the try block raised, so it
  had never fired — and when it did, it masked the real exception.

## [0.36.0] — 2026-07-31

### REcolorado / MLS Grid replication aligned with the official docs

With MLS Grid access granted, the adapter written against assumptions in `6b6bc1e`
was verified against the API v2 docs + Best Practices Guide. Confirmed correct:
`OriginatingSystemName=recolorado`, the 11 `StandardStatus` values, the unquoted
OData date literal, and the 15-minute cadence. Fixed:

- **`City` removed from `$filter`** — MLS Grid exposes a fixed set of searchable
  fields and `City` is not among them, so the request errored out. City narrowing
  is now client-side, while the replication cursor keeps tracking the greatest
  `ModificationTimestamp` *received* (per MLS Grid's rule for partial storage);
  tracking only stored records would re-pull the discarded window forever.
- **`$orderby` removed** — not a supported segment, and we send `$expand=Media`
  where the docs explicitly reject it. The feed already arrives ordered.
- **Request pacing** (`RESO_MIN_REQUEST_INTERVAL_SECONDS=0.5`) to respect the hard
  2 req/s ceiling; exceeding MLS Grid's limits suspends the token. `$top` raised to
  1000 (the cap when `$expand` is used) and clamped, cutting request count 5×.
- **Rentals were classified as sales** — the lease signal is in `PropertyType`
  (`Residential Lease`), not `PropertySubType`. Rent leads were being matched
  against for-sale listings and vice versa.
- **Millisecond precision** in the OData cursor literal; MLS Grid stamps to the
  millisecond and truncating re-scanned a full second every run.
- `Accept-Encoding: gzip,deflate` sent explicitly (required); dropped the
  always-null `ListingURL` mapping.

### Replication health is now visible

`GET /api/v1/properties/sync-status` returns the cursor, last run, counts and
`last_error` for the feed. With the background worker doing the backfill
unattended, a failure otherwise only surfaced in the logs.

> Displaying real REcolorado listings still requires local media copies, the
> `MlgCanUse` (IDX) gate, and stripping the `REC` prefix — tracked separately.

## [0.34.1] — 2026-06-05

### Version history now follows the selected language

- The version-history modal was always shown in Spanish, even with English selected.
  Every changelog entry in `lib/version.ts` is now bilingual (`{ en, es }`) and
  `VersionButton` renders `title`/`changes` in the active UI language.

## [0.34.0] — 2026-06-04

### Admin: change demo access to Member + per-user engagement stats

- **Change access level**: admins can switch a demo registration from view-only to
  **Member** (read+write) via a per-row dropdown in Settings. `PATCH /api/v1/team/accounts/{id}`
  updates `Account.role`; `login/account` then mints a member session.
- **Per-user stats** (Google/Apple **and** demo accounts): each Settings row has a 📊 toggle
  showing logins, total actions, active days, last seen, most-used sections (mini-bars),
  device/browser, and IP — to understand users and improve the system.
- **Lightweight tracking**: a middleware upserts one `UserActivity` row per session-email on
  each authenticated request to a tracked section; login endpoints bump login_count. The
  shared office password (no email) isn't tracked. Stats are admin-only.
- Backend: `user_activity` table (Alembic `013`), `services/activity.py`, the middleware,
  `GET /api/v1/team/activity`. IP + device only (no geolocation).

## [0.33.0] — 2026-06-04

### Admin: registered-users view (Google/Apple + view-only demo signups)

- **Settings** now shows a **"Demo registrations (view-only)"** panel listing everyone who
  self-registered via the public form — name, email, phone, company, location, registration
  date — for sales follow-up. Admins can delete a registration (e.g. test accounts).
- Google/Apple access is still managed in the **"Team & access (Google/Apple)"** panel (the
  allow-list). Both sit together in Settings, admin-only.
- Backend: `GET /api/v1/team/accounts` + `DELETE /api/v1/team/accounts/{id}` (admin-gated,
  on the existing `require_admin` team router). Reuses the `accounts` table — no migration.

## [0.32.1] — 2026-06-04

### Fix: the "Create account" (register) link did nothing

- The `AuthGuard` only exempted `/login`, so navigating to `/register` while
  unauthenticated (on the AUTH_ENABLED demo) bounced straight back to `/login` —
  the link appeared to do nothing. `/register` is now a public route in the guard,
  so the registration page opens. `components/ui/AuthGuard.tsx`.

## [0.32.0] — 2026-06-04

### Self-registration → read-only ("viewer") demo accounts

- **New `/register` page**: anyone can sign up with name, email, phone, company,
  address, state, country + password. Registration auto-signs them in.
- These are **read-only "viewer" accounts** — they can browse the whole dashboard
  but cannot mutate anything. Intended to showcase the system to prospective clients.
- **Read-only enforced server-side**: `require_auth` rejects any non-GET request
  from a viewer with 403 (single choke-point for the whole data API). Passwords are
  hashed with stdlib PBKDF2 (no new dep). New `accounts` table (Alembic `012`).
- **UI**: a "view-only" banner + the create/edit controls hide for viewers
  (Add lead, Composer reply, book/cancel visit, calendar Add event, lead quick
  actions). `/login` gains an email+password sign-in for these accounts alongside
  the office password and Google/Apple.
- Endpoints: `POST /api/v1/auth/register`, `POST /api/v1/auth/login/account`. New
  role `viewer` in the session token.

## [0.31.1] — 2026-06-03

### Calendar: clicking an appointment opens the lead

- Calendar items (in both the Agenda list and the Month grid) are now clickable —
  a visit or follow-up navigates straight to the lead's page (`/leads/{id}`).
  Lead-less manual events are not clickable. `components/calendar/CalendarView.tsx`.

## [0.31.0] — 2026-06-02

### New Calendar tab: agenda + month grid + manual events

- New **Calendar** nav tab aggregating, in the office timezone: all lead **visits**,
  **manual events**, and **pending system follow-ups** — one place to see everything
  the system schedules.
- Two views (toggle): **Agenda** (list grouped by day — Today/Tomorrow/date) and
  **Month** (month grid with each day's items).
- **Add event** creates a manual calendar entry (title, date/time, duration, notes)
  that doesn't need a lead. The naive wall-clock is localized to the office timezone.
- Backend: `Visit.lead_id` is now **nullable** + `Visit.title` (Alembic `011`).
  New `GET /api/v1/visits` (all, optional from/to), `POST /api/v1/visits` (manual
  event, `provider=manual`, no Cal.com round-trip), `GET /api/v1/visits/agenda`
  (visits + PENDING follow-ups unified). `VisitOut` gains `lead_id?`/`title`.

## [0.30.0] — 2026-06-02

### Office timezone: visits booked in local time (not UTC) + a Settings preference

- **Bug**: the voice agent treated a spoken "2 PM" as 2 PM **UTC**, so the visit
  landed at 8 AM Denver. Booking now interprets the spoken wall-clock time in the
  **office timezone** and stores it correctly (2 PM Denver → 20:00 UTC). `_parse_dt`
  localizes the wall-clock to the office tz; `book_visit` + manual `book_slot` load
  the office tz from settings; the assistant prompt now passes a tz-less local time.
- **New Settings preference — Timezone**: auto-detected from the browser on first
  load (one-time persist), changeable anytime. Drives how the agent interprets
  spoken times and how all visits are displayed.
- Visits now render in the office timezone **with the tz abbreviation** (e.g.
  "2:00 PM MDT"), consistent regardless of the viewer's location.
- `AgentSettings.timezone` (Alembic `010`, default UTC); `tzdata` added to
  requirements (python-slim has no system zoneinfo). `GET/PUT /settings` validate
  the IANA name.

## [0.29.1] — 2026-06-02

### Friendly "lead not found" state (no more raw red API error)

- Opening a lead that no longer exists (e.g. an old link to a lead that was merged
  or removed) showed a raw red `API 404: Lead not found` box. It now renders a clean
  "Lead not found" empty state — with a hint that it may have been merged/removed and
  a **Back to leads** link. Real (non-404) errors still show the error box.
- `components/leads/LeadDetail.tsx` distinguishes 404 from other errors; i18n
  `lead.notFoundHint` (EN+ES).

## [0.29.0] — 2026-06-02

### Inbox: "new + pending" badge count + quick-access dropdown menu

- The nav **Inbox badge** now counts **`needs_attention`** = awaiting our reply **OR**
  a fresh (<24h) untriaged conversation (e.g. a just-finished voice call where the
  agent spoke last). So a new call shows up immediately, without old leads inflating
  the number.
- Clicking the Inbox badge opens a **dropdown**: a **"Go to inbox"** header (general
  section) and below it direct links to each new/pending communication (channel icon
  🗣️/✉️/💬 + name + preview) that jump straight to `/leads/{id}`.
- **Opening a lead** marks it reviewed → clears it from the badge, *unless* it's still
  awaiting our reply (that clears on reply or explicit "handled").
- Backend: `services/inbox.py` computes `needs_attention` (`NEW_ACTIVITY_WINDOW_HOURS=24`);
  `GET /inbox` gains a `filter=attention` + `attention_count`; `GET /inbox/count` gains
  `attention`. `pending` is unchanged for back-compat.

## [0.28.1] — 2026-06-02

### Fix voice: a call lands on ONE lead (transcript + visit + extracted fields)

- **Split-lead bug**: a single call produced two leads — the **visit** went to the
  number the caller *dictated* (`book_visit` arg) while the **transcript** went to the
  real **caller id** (end-of-call report). Fix: `book_visit` now keys the lead on the
  **caller id** (same identifier the end-of-call ingest uses) and keeps the dictated
  number as a callback note → visit + transcript land on the same lead.
- **Structured-data bug**: VAPI returned `structuredData` in a **nested** auto-shape
  (`customer_info` / `property_inquiry`) that wasn't mapped → the lead had no
  intent/zone/budget. Fix: `_flatten_voice_structured` normalizes both the flat and
  nested shapes; `scripts/setup_vapi.sh` now sets an **explicit** `structuredDataPlan.schema`
  so future calls return a deterministic flat shape.

## [0.28.0] — 2026-06-02

### Phase 13 · Voice agent (VAPI) — calls that qualify leads and book visits

- **New VOICE channel.** The agent answers calls via VAPI (female English 11labs
  voice + Claude Sonnet 4.5 as the realtime brain). It qualifies the caller
  (buy/rent/valuation, zone, budget, timeline) and can **book a visit during the
  call** through a tool-call into the Cal.com booking service (Phase 5).
- **End-of-call ingest.** When the call ends, VAPI POSTs an `end-of-call-report`
  to `POST /api/v1/webhooks/voice`; we ingest the full transcript into the lead's
  timeline as `channel="voice"` (turns as Messages), apply the extracted fields,
  and rescore — same lead pipeline as SMS/email. No LLM call on ingest (the
  conversation already happened live). Idempotent per `call_id`.
- `services/voice.py`: `verify_vapi_secret` (shared `x-vapi-secret`),
  `parse_end_of_call_report`, and `handle_tool_call` (`check_availability` /
  `book_visit`). `conversation.py::ingest_voice_call` upserts the lead and stores
  the transcript. Voice stays OUT of `SENDABLE_CHANNELS` (no outbound text).
- `VOICE_SIMULATED=true` by default (dev + the public demo need no VAPI account;
  the webhook accepts unsigned requests). Outbound calling (the agent calling
  leads) is deferred to a future phase. Setup: `docs/setup-vapi.md`.
- Tests: `test_voice_service.py` (secret/parse/tool-calls) +
  `test_voice_webhook_e2e.py` (end-of-call → lead+conversation+messages+score,
  idempotency, tool-call book_visit → Visit).

## [0.27.1] — 2026-06-01

### More robust email threading: full References chain

- The agent's reply now sets the `References` header to the **full chain** (thread
  root … the lead's message), not just `In-Reply-To` to the parent — so Gmail/
  Outlook reliably nest the reply inside the conversation instead of starting a new
  thread.
- `services/email.py::send_email` takes a `references` arg; `conversation.py` builds
  the chain from `thread_id` (root) + `external_id` (inbound message) and passes it.

## [0.27.0] — 2026-06-01

### Inbound email: fetch real body + Message-ID (Received Emails API) → correct threading

- **Root cause of "replies as a new email instead of threading"**: Resend's
  `email.received` webhook is **metadata-only** (no body/headers), so inbound
  messages were stored with empty content and without the real RFC822 Message-ID
  — so the agent's reply couldn't be threaded.
- **Fix**: the webhook handler now calls `GET /emails/inbound/{id}` (Received
  Emails API) to fetch the **full** email — `text`, RFC822 `message_id`, and
  `references`/`in_reply_to` — and passes that to the orchestrator. The agent now
  reads the real message and its reply carries correct `In-Reply-To`/`References`
  → Gmail threads it into the conversation.
- `services/email.py`: new `fetch_inbound_email(id)` + `_strip_quoted_reply()`
  (drops quoted "On … wrote:" / ">" history so the agent sees only the new
  message). The SIMULATED path (tests) skips the fetch (body already present).
- Note: external delivery (Gmail→Resend) was working all along — the emails were
  in the Received Emails API; we just weren't pulling their content into the backend.

## [0.26.1] — 2026-06-01

### Email self-loop guard: the agent never replies to itself

- **Security fix**: an inbound email whose sender is **our own sending address**
  (`noreply@<domain>`) is now ignored. Without it, a reply/bounce addressed back
  to `noreply@` re-entered via the inbound webhook and the agent answered itself
  in an infinite loop (burning LLM calls + sending emails). Found during inbound
  testing.
- `services/conversation.py`: guard at the top of `handle_inbound_message` — if
  `channel=email` and the sender equals the `RESEND_FROM` address, it returns
  `ignored_self_loop` without creating a lead or replying. +1 test.

## [0.26.0] — 2026-06-01

### Agent language: English by default, mirroring the lead's language (or the one they ask for)

- Outbound agent communications now default to **English**. If the lead writes in
  another supported language (es/en) the agent mirrors it; if the lead explicitly
  asks for another language, the agent switches to it.
- `services/i18n.py`: `DEFAULT_LANGUAGE` changed `es → en` (used when the language
  can't be detected / the text is ambiguous). The steering line now allows an
  explicit override ("UNLESS the client asks for another language").
- `services/conversation.py`: the default supported-language order is now
  `["en", "es"]` (reply + suggestions), so an unsupported detected language falls
  back to English. Previously the default was Spanish.
- i18n tests +3 (English default, English-first mirroring, explicit-request override).

## [0.25.0] — 2026-06-01

### Local Gemma (Google) LLM fallback via Ollama — the agent replies even when paid quotas are exhausted

- **Root cause**: the agent stopped replying to leads because **both** paid LLM
  providers ran out of quota (Kimi: "usage limit for this billing cycle";
  MiniMax: "usage limit exceeded"). Not an email or code bug.
- **Fix**: added a third LLM provider — **Gemma** (Google's open model) running
  **locally on Ollama** on the ROG — as a free final fallback. Order is
  Kimi → MiniMax → local Gemma. Paid providers still go first (quality); when
  both fail, local Gemma guarantees the lead gets an answer at no cost.
- `services/llm.py`: new `ollama` provider speaking Ollama's native `/api/chat`
  (with `format=json` for the classifier), separate from the Anthropic protocol
  used by Kimi/MiniMax. Gated by `OLLAMA_ENABLED`. +1 test.
- Config: `OLLAMA_ENABLED` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL` /
  `OLLAMA_TIMEOUT_SECONDS` in config.py + docker-compose. The ROG demo uses
  `gemma3:4b` (fits the RTX 3070 8GB).

## [0.24.1] — 2026-05-31

### Fix: Add Lead budget accepts "600k"/"1.2M" + readable validation errors

- **Bug**: typing the budget as `600k` / `800k` in Add Lead sent the raw string to
  the backend → `422 Input should be a valid decimal`, and the error was dumped
  as raw JSON in the modal.
- **Fix**: the budget is now normalized client-side — accepts `600k`, `1.2M`,
  `600,000`, `$850000` and converts to a number before sending (k=×1,000,
  M=×1,000,000). If a field is non-numeric, a clear inline message is shown
  instead of sending garbage.
- **Fix**: `errorDetail` (lib/api.ts) now formats FastAPI validation errors
  (when `detail` is an array) as readable `field: message` text instead of
  dumping raw JSON (which could also crash React if rendered as an object).

## [0.24.0] — 2026-05-31

### Power layer on Properties (search + type chips + sort) and Analytics (weekly trend)

Continues the Claude Design desktop pass — the same "intuitive yet powerful"
layer, now on Properties and Analytics. Frontend-only; no backend changes.

- **Properties → CRM-style explorer**: live search (zone / address / title /
  type) with a `/` shortcut; filter chips by property type (derived from the
  loaded listings); a max-price filter; a toggleable Newest ↔ Price sort; an
  "N of M active" counter; and an empty state with clear-filters. The Sync MLS
  button stays.
- **Analytics → real weekly trend**: ▲/▼ deltas computed from the existing
  `leads_per_day` series — a new "New this week" stat card (sum of the last 7
  days) with a % delta vs. the previous 7 days, and the per-day chart now
  highlights the current week (bright bars) vs. the prior week (dimmed). No
  invented metrics — a trend only shows where there is real time-series data.
- Full EN + ES i18n. Everything stays responsive; mobile and the rest of the
  dashboard are untouched.

## [0.23.0] — 2026-05-29

### More powerful desktop: CRM-style Leads + Lead detail with quick actions & "Why this score"

Implements the desktop design handed off from Claude Design — make the realtor
feel the system is intuitive yet powerful. (Mobile shipped in v0.22.0; this is
the desktop layer.) Everything stays responsive; the mobile experience is intact.

- **Leads is now a CRM-style explorer** (`LeadsExplorer`, replacing
  `FilterBar` + `LeadsTable`): live search (name / zone / contact / intent /
  type) with a `/` keyboard shortcut; smart filter chips (All · 🔥 Hot ·
  Pending reply · New · Qualified · Visiting · Won); a toggleable Priority ↔
  Recent sort (server-side) with a live "N of M" counter; richer rows (red→amber
  accent bar on hot leads, amber "waiting for reply" dot, hover chevron); and an
  empty state with a clear-filters action.
- **Backend**: `GET /leads` now returns `needs_response` per lead (last message
  inbound = waiting on us), via a grouped query scoped to the page (no N+1, same
  pattern as the inbox). Powers the "Pending reply" chip and the row dot. +1 test.
- **Lead detail quick-action bar**: Reply (focuses the composer) · Call (`tel:`
  for phone leads) · Book visit (scrolls to the visits section) · Mark won
  (`PATCH status=won`). Plus a **"Why this score"** card that visualizes the real
  `score_breakdown` (Intent / Budget / Engagement / Urgency / Zone / Type /
  Recency / Visit) with gradient bars.
- **Global polish**: accessible `:focus-visible` ring + a dark scrollbar that
  matches the noir console.
- Full EN + ES i18n for the new strings.

## [0.22.1] — 2026-05-29

### Fix: "Sign in with Google" works on mobile (popup → redirect)

On a phone, tapping "Sign in with Google" opened a new tab to
`accounts.google.com/gsi/transform` that stayed **blank**. Mobile browsers open
the GIS popup as a separate tab, so the credential never returns to the original
tab. (Desktop worked; the Google Console config was correct; v0.22.0 did not
cause it — it surfaced on first mobile use.)

- The button now uses `ux_mode="redirect"` + `login_uri` → Google does a
  full-page navigation (no popup) and POSTs the ID token to the backend. Works
  identically on mobile and desktop.
- New `POST /api/v1/auth/login/google/callback`: verifies Google's
  double-submit CSRF token (`g_csrf_token` body == cookie), validates the ID
  token + allow-list (reusing the existing helpers), sets the session cookie,
  and 303-redirects into `/leads`. Failures bounce to
  `/login?error=google_failed|google_denied` (the login page shows the notice).
  +4 backend tests.
- **Requires one Google Cloud Console change**: add
  `https://inmo-demo.ekoaiautomation.com/api/v1/auth/login/google/callback` to
  the OAuth client's **Authorized redirect URIs** (see
  `docs/setup-google-signin.md`). Password login is unchanged. The legacy JSON
  popup endpoint `POST /api/v1/auth/login/google` is kept for back-compat.

## [0.22.0] — 2026-05-29

### Native-app mobile dashboard (bottom tab bar + slim top bar + notch support)

Mobile visitors to `inmo-demo.ekoaiautomation.com` now get a genuinely usable,
native-app-feeling dashboard. Desktop is unchanged.

- **Fixed bottom tab bar** (phones only, hidden ≥ `md`): Discovery · Leads ·
  Inbox · Properties · Stats. The active tab is highlighted in violet based on
  the current route; Inbox shows an amber dot when there are pending
  conversations. This is the primary navigation on mobile.
- **Slim top bar on mobile**: brand + language + sign-out (plus a Settings gear
  for admins, since Settings isn't in the tab bar). The full desktop link row is
  hidden below `md`.
- **Notch / safe-area support**: `viewport-fit=cover` + dark `theme-color` +
  apple-web-app metadata. The tab bar honors `env(safe-area-inset-bottom)`, and
  page content reserves bottom clearance via `body:has(.eko-tabbar)` so login /
  about (which have no tab bar) keep their full-height layout.
- **Touch-friendly composer on mobile**: the channel selector (SMS / Email /
  Voice) spans full width with larger tap targets; the "Suggest replies" and
  "Send" buttons are roomier for the thumb. Desktop layout is untouched.
- Single-column stacking was already handled per-page by Tailwind responsive
  classes; this release adds the native mobile chrome that was missing.

Implements the mobile design handed off from Claude Design (claude.ai/design).

## [0.21.2] — 2026-05-28

### Inbox handled-state moved to a real column (removes the Lead.meta race)

- The inbox "handled" state moved from `Lead.meta["inbox"]["handled_at"]` (JSON
  blob) to a dedicated `leads.inbox_handled_at` column (Alembic `009`, backfilled
  from the existing JSON). Previously, marking handled reassigned the whole `meta`
  dict, so it could clobber (or be clobbered by) a concurrent writer to `meta`
  (e.g. discovery enrichment writing `meta.enrichment`). They're now separate
  columns and can't interfere.
- `set_handled()` is now a plain column assignment (no ISO parse, no dict
  reassign); removed the silent parse-swallow that could leave a lead "pending"
  forever on a corrupt value.
- **Regression test +1**: two overlapping sessions on the same lead (one writes
  `meta.enrichment`, the other marks handled) both survive (the old approach lost
  one on the last commit).

## [0.21.1] — 2026-05-28

### Code-review fixes for the inbox

- **Past visits no longer shown as booked**: `_next_visit_per_lead` now filters
  `scheduled_at >= now`, so a visit still in scheduled/confirmed status only
  because it was never advanced to completed isn't counted as booked, and
  `next_visit_at` is the next *future* visit (was: earliest-ever, possibly past).
- **Channel/identifier guard**: the channel picker allowed choosing Email for a
  phone-only lead (or SMS for an email lead), which dispatched to an invalid
  recipient and persisted the message as FAILED. `send_human_message` now rejects
  with `channel_identifier_mismatch` before creating an undeliverable
  conversation; the composer surfaces a clear message.
- **Channel-scoped counts**: with `?channel=X` the pending/booked counts were
  computed before the channel filter, so the chip badges didn't match the rows.
  Counts are now computed over the channel-filtered set.
- **Tests +4**: past visit not booked (+ next_visit_at is the future one),
  mismatched channel rejected without creating a conversation, create-when-missing
  uses a compatible channel (whatsapp→sms), counts scoped by channel.

## [0.21.0] — 2026-05-28

### Communications inbox — leads buzón with badges, filters, priority

New **Inbox** tab in the Nav (with a pending counter): a mailbox-style view of
leads with open conversations. Each lead shows its priority (🔥/🟡/⚪), a
**pending-channel badge** (✉️ Email / 💬 SMS / 🗣️ Voice) when it's waiting for our
reply, and a 📅 **Visit** badge with date if a visit is booked; leads with nothing
pending show **✅ Up to date**.

- **Filters**: Pending (default) / With visit / All. **Auto-sorted by priority**
  (score desc; within a score, the longest-waiting first). "Pending" = the lead's
  last message is inbound and we haven't replied/handled it since.
- **Mark handled** removes a lead from pending (stored in `Lead.meta` — no
  migration); it re-arms only when a new inbound arrives. Replying from the
  conversation also clears it (last message becomes outbound). "Reply" opens the
  lead's unified conversation.
- **Backend**: `services/inbox.py` (derived state via grouped queries — no N+1:
  last message per lead, channels per lead, next active visit) + `api/v1/inbox.py`
  (`GET /api/v1/inbox?filter=pending|booked|all`, `GET /inbox/count` for the nav
  badge, `POST`/`DELETE /inbox/{id}/handled`). Behind the same `require_auth` gate
  as the rest of the data API.
- **Tests +5**: pending reflects last inbound by channel; handled suppresses then a
  new inbound re-arms; `filter=booked` only with-visit ordered by date; priority
  sort + coherent count; mark-handled idempotent + isolated + 404.

## [0.20.0] — 2026-05-28

### Unified multichannel lead thread + channel picker + real email (plumbing)

A lead's conversation is now a **single timeline merging all channels** (SMS +
email + WhatsApp), time-ordered, each bubble showing its channel icon; the header
lists the active channels. Previously only the most-recently-active channel showed.

- **New endpoint** `GET /api/v1/conversations/{lead_id}/timeline` — merges messages
  across all of the lead's conversations (each tagged with its channel); returns
  `channels[]`, `primary_channel`, and per-channel summaries; 200 with empty arrays
  when the lead has no conversation yet. `MessageOut` now includes `channel`.
- **Channel picker** in the composer (SMS / Email active; Voice disabled "coming
  soon", Phase 13). Sending on a channel the lead hasn't used creates that
  conversation. `send_human_message(channel=…)` (auto-picks when omitted —
  backward compatible) rejects voice; `HumanMessageIn.channel` is
  `Literal["sms","email","whatsapp"] | None` (voice → 422).
- **Fix**: sent messages now appear instantly (client-side timeline refetch via an
  `onSent` callback) instead of relying on `router.refresh()`, which didn't re-run
  the client component effect — the outbound didn't show until a full reload.
- **Real email (plumbing)**: `docker-compose.yml` now passes
  `EMAIL_SIMULATED` / `RESEND_API_KEY` / `RESEND_FROM` / `RESEND_WEBHOOK_SECRET`
  to the backend (was missing); `RESEND_FROM` default moved to a **dedicated
  subdomain** (`realtors.ekoaiautomation.com`) — never mixed with Eko AI Main's
  `biz.ekoaiautomation.com`. New `docs/setup-email.md` (subdomain + Cloudflare DNS,
  isolated from the sales platform).
- **Tests +8**: timeline (2-channel merge ordering, id tiebreak, empty 200) +
  channel selection (reuse existing conversation, create when missing, voice 422 +
  service-level `unsupported_channel`, auto-pick when channel omitted).

## [0.19.0] — 2026-05-27

### Sign in with Apple

Adds a **"Sign in with Apple"** button on `/login`, below Google under the same
"or" divider. Coexists with the password and Google flows — none replaces the
others. It reuses the **same office allow-list as Google** (the list is keyed on
the email, not the provider), so an already-allowed email signs in via Apple with
the same role.

- **Web popup flow** (Sign in with Apple JS, `usePopup: true`): Apple authenticates
  in a popup and returns the `id_token` in-page; the frontend POSTs it to
  `POST /api/v1/auth/login/apple`.
- **Backend verification**: `verify_apple_id_token` validates the identity token's
  **RS256** signature against Apple's public keys (`appleid.apple.com/auth/keys`),
  plus `iss == https://appleid.apple.com`, `aud == APPLE_CLIENT_ID` (the Services
  ID), expiry and `email_verified`. Role resolved via the shared
  `resolve_email_access`. No client secret / `.p8` key needed — only the public
  Services ID. Apple Private Relay emails (`@privaterelay.appleid.com`) log in only
  if explicitly allow-listed.
- **Config**: `APPLE_CLIENT_ID` (backend) + `NEXT_PUBLIC_APPLE_CLIENT_ID` +
  `NEXT_PUBLIC_APPLE_REDIRECT_URI` (frontend, inlined at build), wired through
  `docker-compose.yml` + `frontend/Dockerfile` like Google. `GET /api/v1/auth/me`
  now reports `apple_signin_enabled`. New dependency `pyjwt[crypto]`.
- New component `frontend/components/ui/AppleSignInButton.tsx`; `docs/setup-apple-signin.md`.
- **Tests +4**: `verify_apple_id_token` (happy path with mocked JWKS + decode;
  rejects not-configured + unverified email), `/me` reports the flag, and the Apple
  login flows (pinned admin + DB member + denied) reusing the Google allow-list.

## [0.18.0] — 2026-05-27

### Version button + changelog viewer in the dashboard

Adds a version pill (`v0.18.0`) in the top-right of the Nav (next to the language
switcher). Clicking it opens a modal listing the full version history (version,
date, title, bullet changes) read from `lib/version.ts` — mirroring Eko AI Main.

- Modal closes on ESC, click-outside or the Close button; locks body scroll while
  open; rendered via a portal. Dashboard violet/noir palette, EN/ES i18n.
- New component `frontend/components/ui/VersionButton.tsx`, mounted in
  `components/ui/Nav.tsx`.

## [0.17.0] — 2026-05-27

### Add Lead — manual lead creation (demo + operational) with AI kickoff

Adds an **Add Lead** button + modal on `/leads` to create a lead by hand. One
flow, two uses: (1) the realtor poses as a client to experience the agent
live, and (2) the realtor enters a real referral/contact into their CRM. Either
way the lead enters the **same pipeline** as auto-captured ones — scoring, intent
classification, property matching and follow-ups.

- **First-message kickoff**: an optional "first message from the client" is
  injected as an INBOUND message and triggers the full AI turn (classify → reply
  → send through the chosen channel) via the same path a real webhook takes. On
  save the dashboard lands directly on the lead's conversation with the AI reply
  already generated.
- **Channels**: SMS (default) and Email work today; Voice shows as disabled
  ("coming soon", Phase 13) and WhatsApp is omitted for now. The backend only
  accepts `sms`/`email` for the kickoff so it can't create an undeliverable
  conversation.
- **Backend**: `POST /api/v1/leads` (`LeadCreate`, `extra="forbid"`) with dedupe
  by identifier (409 on conflict), marks `meta.source="manual"` (NOT a demo flag
  → first-class lead, not wiped by `seed_demo --reset`) and rescores on create.
  Reuses `handle_inbound_message` for the first turn; sits behind the same
  `require_auth` as the rest of the data API.
- **Frontend**: `AddLeadButton` modal (dashboard violet/noir palette),
  `leadsApi.create` + `LeadCreate` interface, EN/ES i18n.
- **Tests +5**: create without message (source=manual + score + no conversation),
  create with first message (mocked LLM → conversation + inbound/outbound),
  duplicate 409, missing phone 422, unknown field 422.

## [0.16.2] — 2026-05-27

### Fix — Google login 401'd (missing `requests` transport dependency)

The Google button rendered but selecting an account failed with "Google sign-in
failed". `google-auth`'s `verify_oauth2_token` uses `google.auth.transport.requests`
to fetch Google's public keys, and `requests` is an **optional** dependency of
`google-auth` — it wasn't in `requirements.txt`, so verification raised
`requests library is not installed` → 401. (Password login was never affected.)

- Added `requests==2.32.3` to `backend/requirements.txt`.
- Regression test: `verify_google_id_token` on a malformed token must fail with
  `invalid_id_token`, not `google_auth_library_missing` — so an absent transport
  dep is caught in CI (the existing tests mocked verification and missed it).

## [0.16.1] — 2026-05-27

### Fix — wire the Google Sign In env vars into the containers

v0.16.0 shipped the Google Sign In code but `docker-compose.yml` didn't pass the
`GOOGLE_*` vars to the backend, so `GOOGLE_ADMIN_EMAILS` never reached the
container and the bootstrap admin wasn't seeded into `allowed_users`.

- Backend `environment:` now passes `GOOGLE_CLIENT_ID`, `GOOGLE_ADMIN_EMAILS`,
  `GOOGLE_ALLOWED_EMAILS`, `GOOGLE_ALLOWED_DOMAIN`.
- Frontend gets `NEXT_PUBLIC_GOOGLE_CLIENT_ID` as a **build arg** (Next.js inlines
  `NEXT_PUBLIC_*` at build time — declared in the Dockerfile, not runtime env).

## [0.16.0] — 2026-05-27

### Google Sign In (GIS) + admin-managed team access

Adds "Sign in with Google" on `/login` (coexists with the password) **and**
admin-managed access control. The allow-list moves out of env vars into the
database so an admin edits it live from a restored, admin-only **Settings** tab.

#### Auth model

- The session token now carries **identity + role** (`admin` | `member`), still
  an HMAC-signed `eko_auth` cookie (no new dependency, no JWT lib).
- **Password login → admin** (master key; lockout-proof fallback). **Google login**
  takes its role from the access list.
- **`POST /api/v1/auth/login/google`** verifies the Google ID token (signature +
  `aud == GOOGLE_CLIENT_ID` + `email_verified`) via `google-auth`, resolves the
  email against the access list, and mints the role-bearing cookie. Not on the
  list → `401 email_not_in_allow_list` (safe default deny).
- **`GET /api/v1/auth/me`** now returns `role` + `google_signin_enabled`.

#### Team / access (admin-only)

- New `allowed_users` table (email, role, added_by) — Alembic `008`.
- **`/api/v1/team`** CRUD (`require_admin`): list / add / change-role / remove.
  Guards: cannot demote or remove an env-pinned admin; cannot remove the **last**
  admin.
- **`GOOGLE_ADMIN_EMAILS`** (env) pins bootstrap admin(s) — always admin, seeded
  into the table on startup, immutable from the UI.
- The **entire Settings page is admin-only** now (`/api/v1/settings` +
  `/api/v1/team` under `require_admin`; hidden + 403 for members).

#### Frontend

- **`/login`** shows the GIS "Sign in with Google" button (via `@react-oauth/google`)
  when configured; coexists with the password.
- **Settings** restored to the nav (gear), shown only to admins. New **Team /
  Access** panel: add Gmail addresses, set role, promote/remove; env-pinned admins
  shown as immutable "owner".
- `lib/api.ts` `teamApi` + `MeResult.role`; i18n `settings.team.*` (EN + ES).

#### Config & docs

- `.env.example`: `GOOGLE_CLIENT_ID`, `GOOGLE_ADMIN_EMAILS`, `GOOGLE_ALLOWED_EMAILS`,
  `GOOGLE_ALLOWED_DOMAIN`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
- `docs/setup-google-signin.md` updated for the DB-managed team + bootstrap admin.

## [0.15.2] — 2026-05-27

### Nav reorder — Discovery · Leads · Properties · Analytics · API · EN

- Reordered the top nav to **Discovery, Leads, Properties, Analytics, API, EN**
  (language switcher) — Discovery leads (the prospecting flow starts there).
- **Settings** was removed from the top bar to match the requested menu; the page
  is still reachable at `/settings`.

## [0.15.1] — 2026-05-27

### Discovery — SIMULATED fallback per category with no real provider

- In real mode (`DISCOVERY_SIMULATED=false`, how the ROG demo runs) only
  `investor_llc` returned data (Colorado SOS, free); the seller categories +
  `renter` came back **empty** because they have no free real source (ATTOM is
  paid, FSBO needs a licensed feed) — so most of Discovery looked broken.
- **Fix**: when a category has no configured real provider (or it returns
  nothing), Discovery falls back to that category's curated SIMULATED leads, so
  all 7 categories stay demoable. Real data (Colorado SOS now, ATTOM once keyed)
  takes precedence when present.
- Test: in real mode, `fsbo` with no provider still returns leads.

## [0.15.0] — 2026-05-27

### Discovery v2 — search reoriented to real-estate leads (not businesses)

Discovery now finds **people likely to buy / rent / sell** real estate, not
generic businesses — the whole point of a realtor product. Backed by research
(see [`docs/discovery-realestate-research.md`](docs/discovery-realestate-research.md)).

#### Lead categories (how agents actually prospect)
- **Sellers**: `fsbo` (For Sale By Owner), `expired` (expired listings),
  `absentee` (out-of-state owners), `preforeclosure` (distressed),
  `high_equity` (long-tenure / likely-to-sell).
- **Buyers**: `investor_llc` (real-estate investor LLCs), `renter`
  (renters / relocators).

#### What changed
- Each discovered lead carries **motivation** ("listing expired 2 weeks ago",
  "notice of default recorded"), **timeline** (immediate / 3-6mo / exploring),
  **property type** and **estimated value**. Enrichment uses these to classify
  `intent` (seller → `valuation`, buyer → `buy`/`rent`) and to weight the score
  by motivation + urgency.
- **SIMULATED-first**: ~17 curated realistic Denver-metro leads across the
  categories — $0, no keys. Real per category: `investor_llc` via **Colorado SOS
  (free)**; `absentee`/`preforeclosure`/`high_equity` via **ATTOM**
  (`ATTOM_API_KEY`, key-gated); `fsbo`/`expired`/`renter` need a licensed feed
  (stay SIMULATED).
- API: `POST /discovery/search` now takes **`category`** (+ optional `query`
  refine) instead of `sources`. `BusinessOut` / `Lead.meta` carry
  motivation/timeline/property_type/est_value.
- Frontend: **lead-category preset chips** (Sellers / Buyers) replace the source
  toggles; results show motivation + timeline + type + value; a **DNC/TCPA
  compliance note** is shown (leads are prospects, not consented contacts). i18n
  EN/ES.
- Tests updated to category-based search.

## [0.14.4] — 2026-05-27

### Fix — surface the real API error (no more "body stream already read")

- The API client (`lib/api.ts`) read an error response body twice (`res.json()`
  then `res.text()` in the `catch`), which threw *"Failed to execute 'text' on
  'Response': body stream already read"* and **masked the real error** — a backend
  500 showed up as that confusing message instead.
- Fix: an `errorDetail()` helper reads the body **once** as text, then tries
  `JSON.parse` to pull out `detail`. Applied to `api()` and `discoveryApi.upload()`.
- Context: this surfaced when the backend returned 500 because the ROG disk was
  100% full and Postgres was stuck in recovery (crash-loop on "No space left on
  device"). Freed ~93 GB of Docker build cache and the DB recovered; this fix
  ensures the *real* error shows next time.

## [0.14.3] — 2026-05-27

### Discovery — server-side enrichment (no longer depends on the browser)

Leads passed through the flow but stayed unenriched. **Root cause**: enrichment
only fired from the **frontend** loop over **newly created** leads — so leads
imported before classification (v0.14.2), skipped by dedupe on re-import, or left
when the user closed the tab, never got enriched (`score 0`, no intent).

- **Fix**: a server-side enrichment worker. `enrich_pending_leads()` finds
  discovery leads still unclassified (`score == 0`) and enriches them; it runs as
  an in-process loop (`ENRICHMENT_ENABLED`, every 120s, mirroring the follow-ups
  worker) plus a manual `POST /api/v1/discovery/enrich-pending`. Enrichment no
  longer depends on the browser — every discovery lead ends up classified.
- **Retry cap**: `enrich_lead` tracks `meta.enrichment.attempts`; the sweep gives
  up on a lead after 3 failures so it won't retry forever.
- **Backfill**: on deploy, the worker (or the manual endpoint) classifies the
  older leads that were sitting at `score 0` / no intent.
- The frontend per-lead loop stays for immediate progress feedback; the worker is
  the safety net. Tests +1 (sweep only touches unclassified discovery leads,
  respects the cap, leaves conversation leads alone).

## [0.14.2] — 2026-05-26

### Discovery — imported leads are now classified (intent + 🔥 score) like the rest

Imported discovery leads showed up bare in `/leads` (status `new`, no intent,
score `0` ⚪) next to worked leads with 🔥 / qualified / buy badges. Enrichment now
**also classifies and scores** the lead so it carries the same `IntentBadge` +
`ScoreBadge`.

- The enrichment LLM now also returns **`intent`** (`buy` / `rent` / `valuation` /
  `other` — best-fit if the contact could be a client, else `other`) and
  **`relevance`** (0-10). `enrich_lead` sets `lead.intent` and computes
  `lead.score` + `score_breakdown` via a prospect-lead scoring (no conversation
  to score): `partner_type` (referral_partner 35 / prospect 32 / vendor 18 /
  competitor 6 / other 12) + `relevance×2` + real contact (+25) + website (+10),
  mapped to `hot ≥67 / warm ≥34 / cold` with the same thresholds as `scoring.py`.
- A referral-partner mortgage broker with contact + high relevance → 🔥 hot; a
  competitor with no contact → ⚪ cold. The leads list ranks them by score
  alongside conversation leads.
- Status stays `new` (honest — freshly sourced, unworked). If enrichment fails the
  lead is still saved, just unclassified.
- Tests +3: `_coerce` of intent/relevance, `discovery_score` tiers, and the happy
  path now asserts `lead.intent`, `lead.score > 0`, and
  `score_breakdown.source == "discovery_enrichment"`.

## [0.14.1] — 2026-05-26

### Hotfix — widen `leads.phone` 32 → 254 (discovery import was 500-ing)

- Importing a discovery lead with a long identifier (a LinkedIn URL, or the
  synthetic `discovery:<source>:<slug>:<city>` key) raised HTTP 500
  `StringDataRightTruncationError`. **Root cause**: `leads.phone` was still
  `VARCHAR(32)` in the database even though the model has declared `String(254)`
  since Phase 3 — that migration renamed columns but never actually altered
  `leads.phone` (emails under 32 chars worked by luck).
- **Migration `007_phase12_widen_phone`**: `ALTER leads.phone TYPE VARCHAR(254)`
  to align the DB with the model. Safe widening (no data loss, keeps the unique
  index).
- Without this, the v0.14.0 fix (importing contact-less leads) failed in
  production for most Colorado SOS / LinkedIn results.

## [0.14.0] — 2026-05-26

### Discovery fix — imported leads now save + LLM enrichment with a progress bar

Follow-up to Phase 12 after testing surfaced that "Import selected" appeared to do
nothing.

#### Critical fix: imports were silently dropped

- **Root cause**: `import_business_leads` used `phone | email` as the unique
  identifier, but most sources (Colorado SOS, LinkedIn) carry **neither** → every
  such lead was skipped and never reached `/leads`. The `phone` column is
  `NOT NULL UNIQUE`, so a contact-less lead couldn't even be created.
- **Fix**: identifier now falls back **phone → email → website → synthetic**
  (`discovery:<source>:<slug>:<city>`). Every named business imports, and
  re-imports **dedupe** on that stable key instead of duplicating. Import also
  returns the created `lead_ids`.

#### New: lead enrichment + visible progress

- **`services/enrichment.py`** + **`POST /api/v1/discovery/enrich/{lead_id}`**:
  per lead, the LLM (`json_mode`) infers a normalized **business_type**, a
  **partner_type** (`referral_partner` / `vendor` / `prospect` / `competitor` /
  `other`), a one-line **summary**, an **outreach_angle**, and **tags** — stored
  in `meta.enrichment`. Flags `contact_missing` when there's no real phone/email.
  Graceful (mirrors `classifier.py`): LLM down or bad JSON → `status="failed"`,
  never raises, never loses the lead.
- **Progress bar**: after import, the frontend enriches lead-by-lead with a real
  **X/N progress bar**, then shows a summary + a **"View in Leads"** link.
- `/leads` table renders contact-less discovery leads cleanly (synthetic id → `—`
  with a search glyph; `linkedin.com/in/…` URLs with a globe glyph).

#### Tests

- **+9**: `lead_identifier` fallback + deterministic synthetic key; import with no
  contact **now creates + dedupes + returns `lead_ids`**; `_coerce`
  (invalid `partner_type` → `other`, tag string → list capped at 4); `enrich_lead`
  happy path (persists `meta`, `contact_missing`) + graceful on LLM failure + bad JSON.

## [0.13.0] — 2026-05-26

### Phase 12 — Discovery: lead search (4 sources) + import from any file

Adds proactive lead sourcing — until now leads were inbound-only (WhatsApp /
email / SMS). A realtor can now go find new business leads, or bulk-import an
existing contact database in any file format.

#### Search (4 sources, preview-and-select)

- New **Discovery** tab (mirrors the Eko AI sales platform): search **Google
  Maps, Yelp, LinkedIn, Colorado SOS** for businesses, see a checklist preview,
  pick which to import.
- **`services/discovery.py`** — ported + adapted from the sales platform's
  discovery agent (Paperclip dropped). SIMULATED-first like `listings.py`:
  `DISCOVERY_SIMULATED=true` (default) serves a curated set of plausible CO
  businesses with **zero keys**. Real adapters per source, each degrading to
  `[]` without its key: **Colorado SOS** (public Socrata API — **free, no key**),
  **Yelp** (Fusion), **Google Maps** (Outscraper), **LinkedIn** (SerpApi).

#### File import (any format)

- **`services/file_import.py`** — `extract_text` routes by extension: **PDF**
  (`pypdf`), **XLSX** (`openpyxl`), **images JPG/PNG** via OCR (`pytesseract` +
  `tesseract-ocr` in the Dockerfile), CSV/TXT/HTML (stdlib + tag strip). Then
  `extract_leads` runs the text through the LLM (`json_mode`) to pull contacts
  as a JSON array, with the classifier's graceful-degradation style (bad output
  → `[]`, never crashes).

#### Import → leads

- Search/upload return **transient** results (not persisted). `POST
  /api/v1/discovery/import` creates the selected ones as `Lead` rows
  (`status=new`, `meta.source`), **deduped** by identifier (phone, else email)
  against existing leads. No new table / migration.

#### API + frontend + config

- API under **`/api/v1/discovery`** (`/search`, `/upload` with a
  `FILE_IMPORT_MAX_MB=25` cap, `/import`) — protected by `require_auth`.
- Frontend **`/discovery`**: `DiscoveryPanel` (4 toggleable source chips + a
  reusable `ResultsList` checklist) + `FileImport` (drag-drop). Discovery link
  in the nav (Search icon). i18n EN/ES.
- `config` + `.env.example` + compose: `DISCOVERY_SIMULATED`,
  `YELP_API_KEY` / `OUTSCRAPER_API_KEY` / `SERPAPI_API_KEY` (reuse the sales
  platform keys), `FILE_IMPORT_MAX_MB`. `requirements`: `pypdf` / `openpyxl` /
  `pillow` / `pytesseract`. New **`docs/setup-discovery.md`**.

#### Tests

- **+13 (total 145)**: `test_discovery.py` (6 — simulated search returns
  businesses, source filtering, `max_results` cap, `sanitize_email`, import
  creates + dedupes, import without identifier skips) + `test_file_import.py`
  (7 — `extract_text` plaintext/csv/html-strip/empty, `extract_leads` parses a
  JSON array, tolerates prose, bad output → `[]`, empty text skips the LLM).

Voice (VAPI / Retell) renumbered to Phase 13.

## [0.12.0] — 2026-05-26

### Phase 11 — Pilot hardening: dashboard auth + analytics

Makes the product safe and measurable to hand to a paying office.

#### Dashboard auth (one office = one shared password)

- **`/login`** page + **`AuthGuard`** (redirects to login when the session is
  missing). HMAC-signed session token in an httpOnly cookie (no new dependency).
  **Sign-out** in the nav.
- **`require_auth`** gate on the data API (leads / conversations / visits /
  settings / properties / analytics); webhooks + health stay open. Gated by
  **`AUTH_ENABLED`** — default **off** (dev + the public demo stay open); the
  installer turns it on with a password. Startup **WARN** if `APP_ENV=production`
  and `AUTH_ENABLED=false`.
- `config` + `.env.example` + compose: `AUTH_ENABLED` / `DASHBOARD_PASSWORD` /
  `AUTH_SECRET` / `AUTH_TTL_HOURS`. `scripts/install.sh` now prompts for a
  dashboard password and enables auth.

#### Analytics

- **`GET /api/v1/analytics`** + **`/analytics`** page: funnel by status,
  conversion rate, leads by channel, by score tier (🔥/🟡/⚪), average first-
  response time, and new leads per day (14d). No chart library (div bars).

#### Tests

- **+6 (132 total)**: auth service (password / token / tamper / expiry) + the
  gate (open when disabled; 401 → login → cookie when enabled) + analytics envelope.

#### Roadmap

- Voice (VAPI/Retell) renumbered to **Phase 12**.

## [0.11.0] — 2026-05-26

### Phase 10 — Autonomous nurture + in-conversation listing offers

The agent now works leads **while you sleep**, and offers real inventory in chat.

#### Autonomous follow-ups

- **`FollowUp` model** + Alembic `006` (lead / visit / kind / status /
  `scheduled_for`, UNIQUE(visit, kind) → idempotent enqueue).
- **`services/followups.py`** — `enqueue_for_visit` schedules a 24h-before
  **reminder** + a post-visit sequence (**24h** "how was it?", **72h** nudge,
  **7d** "new similar listings"). `process_due_followups` sends the due ones,
  **skipping** human takeover, cancelled visits, and the 72h nudge if the lead
  already replied. Bilingual templates, sent as the AI agent via the lead's channel.
- **In-process worker** (`main.py` asyncio loop, `FOLLOWUPS_ENABLED` +
  `FOLLOWUPS_INTERVAL_SECONDS`) + **`scripts/run_followups.py`** for cron. Booking
  a visit enqueues the sequence.

#### Agent offers listings in-conversation

- When a lead is buy/rent with a known zone, the orchestrator injects the **real
  matched listings** into the system prompt (only those, never invented) so the
  agent offers them naturally — closing the Phase 7 loop (matching was
  dashboard-only before).
- **Fix**: the matcher crashed on `float * Decimal` when the budget came fresh
  from the classifier (swallowed → empty matches). Normalized with `Decimal(str())`.

#### Tests

- **+6 (126 total)**: follow-up scheduling / due-processing / skip rules +
  agent-gets-real-listings-in-prompt.

#### Roadmap

- Voice (VAPI/Retell) renumbered to **Phase 11** (still deferred).

## [0.10.0] — 2026-05-26

### Multilingual dashboard (English default + Spanish) with a language switcher

The realtor dashboard is now multilingual: **English by default, Spanish second**,
with a **language switcher** (globe + EN/ES) in the nav on **every page**.

- **`lib/i18n.tsx`** — client `LanguageProvider` + `useI18n` hook + full EN/ES
  dictionaries. The choice persists to `localStorage` and syncs `<html lang>`.
  `t(key)` falls back to English, then the key.
- **Every UI string** goes through `t()`: nav, pages, badges (status / intent /
  score / visit), leads table + detail, composer, suggestions, property matches,
  visits, booking dialog, properties grid, settings, takeover toggle, messages.
- **Locale-aware formatters** — `relativeTime` / `exactTime` / `formatBudget`
  (USD, en/es) + visit & booking dates follow the active language.
- Pages use a client `PageHeader`; the lead-detail page is now a client component.
  `/about` landing copy refreshed (MLS matching).

This pairs with the agent already replying in the lead's language (Phase 3) — now
the realtor's interface is bilingual too.

## [0.9.1] — 2026-05-26

### SMS hardening — A2P `MessagingServiceSid` + delivery status callbacks

Two production improvements to the SMS channel, surfaced by reading Twilio's API docs:

- **`send_sms` via `MessagingServiceSid`** — when `TWILIO_MESSAGING_SERVICE_SID`
  is set, outbound goes through the A2P 10DLC-registered Messaging Service (the
  Twilio-recommended path for US delivery) instead of the bare `From` number.
  Falls back to `TWILIO_PHONE_NUMBER`.
- **Delivery status callbacks** — new `POST /api/v1/webhooks/sms/status`. With
  `TWILIO_STATUS_CALLBACK_URL` set, `send_sms` asks Twilio to POST status updates
  (`sent` → `delivered`/`undelivered`/`failed` + `ErrorCode`); the backend
  reflects the final state on the outbound `Message` so the dashboard shows real
  delivery (and logs carrier errors like **30034** = A2P 10DLC unregistered).
- `config.py` + `.env.example` + compose: `TWILIO_MESSAGING_SERVICE_SID` +
  `TWILIO_STATUS_CALLBACK_URL`.
- **`docs/setup-twilio.md`** expanded: A2P 10DLC registration (Sole Proprietor vs
  Standard), the Messaging Service webhook override gotcha, and STOP/HELP opt-out
  (handled by Twilio's default Advanced Opt-Out).
- Tests **+4 (120 total)**: status mapper + status-callback e2e.

## [0.9.0] — 2026-05-26

### Phase 9 — SMS channel (Twilio)

A third channel: SMS via Twilio, on the same multichannel architecture as
WhatsApp and email. SIMULATED-first, so it works without an account.

#### Backend

- **`services/sms.py`** — `send_sms` (SIMULATED logs / real Twilio REST API),
  `verify_twilio_signature` (HMAC-SHA1 over the request URL + sorted POST params,
  keyed by the auth token), `parse_inbound_sms` → `ParsedMessage(channel="sms")`.
- **`POST /api/v1/webhooks/sms`** — parses Twilio's form, validates the signature
  (unless SIMULATED), hands off to the orchestrator, returns empty TwiML (the
  reply is sent asynchronously via REST). Signature URL comes from
  `TWILIO_WEBHOOK_URL` or is rebuilt from forwarded headers.
- Dispatcher gains an `sms` branch; idempotency via UNIQUE `messages.external_id`
  (the `MessageSid`).
- `config.py` + `.env.example` + compose: `SMS_SIMULATED` (default true) +
  `TWILIO_ACCOUNT_SID` / `AUTH_TOKEN` / `PHONE_NUMBER` / `WEBHOOK_URL`.
- `scripts/simulate_inbound_sms.py` for smoke testing.

#### Docs

- **`docs/setup-twilio.md`** — account + number + webhook + signature + cost/safety
  notes.

#### Tests

- **+9 (116 total)**: `test_sms_service.py` (7) + `test_sms_webhook_e2e.py` (2).

#### Roadmap

- Voice (VAPI/Retell) remains **Phase 10**, deferred until a provider account exists.

## [0.8.0] — 2026-05-26

### Phase 8 — Lead intelligence (scoring + prioritization + digest)

Leads are now scored and ranked so the realtor knows who to call first — no
external accounts needed (it scores signals the pipeline already produced).

#### Backend

- **`leads.score`** (0-100, indexed) + **`score_breakdown`** (JSON) — Alembic `005`.
- **`services/scoring.py`** — `compute_lead_score` is deterministic and cheap:
  intent (20) · budget (15) · engagement (15) · urgency (12) · zone (10) ·
  recency (10) · visit (10) · property_type (8), then a **status gate**
  (WON/LOST → 0, PAUSED → ½). Returns an explainable breakdown + tier. No
  per-lead LLM call. `rescore_lead` / `rescore_all` (grouped queries).
- The orchestrator **recomputes the score after every inbound turn**.
- **API**: `score`/`score_breakdown` in `LeadOut`; `sort=score|recent` (default
  `score`); `GET /leads/digest` (top hot/active leads); `POST /leads/rescore-all`.
- **`scripts/daily_digest.py`** — cron-friendly hot-leads digest.

#### Frontend

- **`ScoreBadge`** — 🔥 hot (≥67) / 🟡 warm (≥34) / ⚪ cold, in the leads table
  (now score-sorted) and the lead detail header.
- **`HotLeadsPanel`** — "Leads calientes — a quién llamar primero" on `/leads`,
  fed by `/leads/digest`.

#### Tests

- **+11 (107 total)**: `test_scoring.py` (8 pure) + `test_lead_digest.py` (3 API).

#### Roadmap

- SMS (Twilio) → **Phase 9**, Voice (VAPI/Retell) → **Phase 10** — both still
  deferred until the external accounts exist.

## [0.7.0] — 2026-05-25

### Phase 7 — MLS / IDX listings (RESO) + per-lead property matching

The agent now works against real-estate inventory: listings are ingested from a
RESO Web API feed (SIMULATED in dev), browsable at `/properties`, and matched to
each lead's intent / zone / budget on the lead detail.

#### Backend

- **`Property` model reworked for the USA**: `source` (`reso`/`idx`/`mls`/`manual`),
  `status` (`active`/`pending`/`sold`/`off_market`), `bedrooms`, `bathrooms`
  (half-baths, `2.5`), `sqft`, `property_type`, `address`/`city`/`state`/`zip_code`,
  `zone` (neighborhood), `latitude`/`longitude`, `photos`, `description`,
  `listed_at`. Alembic `004` drops + recreates the (empty) EU placeholder table.
- **`services/listings.py`**:
  - `fetch_listings` — SIMULATED returns a curated 9-listing Miami set; real mode
    queries a **RESO Web API** (OData) feed and maps the RESO Data Dictionary
    fields. Configured via `RESO_BASE_URL` + `RESO_ACCESS_TOKEN`.
  - `sync_listings` — idempotent upsert by `(source, external_id)`.
  - `match_properties_for_lead` — intent gate (rent vs sale) + zone + budget
    (±10%) + property type, ranked by price.
- **Endpoints**: `GET /properties` (filters), `POST /properties/sync`,
  `GET /properties/{id}`, `GET /leads/{id}/matches`.
- **`scripts/sync_listings.py`** ingest CLI (cron-friendly). Config + `.env.example`
  + compose env (`LISTINGS_SIMULATED` default true, `RESO_*` for prod).

#### Frontend

- **`/properties`** — grid of listing cards with zone / max-price filters and a
  **Sincronizar MLS** button.
- **`MatchesSection`** on the lead detail — "Propiedades sugeridas" matched to the
  lead, each with **Enviar al lead** (sends a formatted blurb via the composer).
- **Propiedades** nav link.

#### Docs

- **`docs/setup-mls.md`** — connecting a real RESO Web API / IDX feed + the
  matching rules + an IDX-compliance note (why the public demo stays SIMULATED).

#### Tests

- **+12 (96 total)**: `test_listings_service.py` (5) + `test_properties_api.py`
  (7 — idempotent sync, filters, 404s, buy-lead matches sale-only, rent-lead
  matches rentals-only).

## [0.6.0] — 2026-05-25

### Phase 6 — Single-customer installer + branding panel + public demo

The product is now installable by a single office in one command, brandable
from the dashboard, and demoable from a live public URL — and CI is green for
the first time since Phase 1.

#### Branding panel (Settings API + `/settings` page)

- **`GET/PUT /api/v1/settings`** over the `AgentSettings` singleton (auto-created
  with defaults). `PUT` is a partial update; `languages` is normalized to
  lowercase + de-duped. Empty body → 400, unknown field → 422.
- **`/settings`** dashboard page: agency name + phone, agent persona (system
  prompt), greeting template, languages (es/en/pt/fr chips), and business hours
  (per-day open/close or closed). A **Configuración** link is in the nav.
  Changes apply immediately to new auto-replies.

#### Single-customer installer

- **`scripts/install.sh`** — interactive installer: checks prerequisites
  (Docker/Compose/daemon), generates a `.env` with **strong random secrets**
  (`POSTGRES_PASSWORD`, `WHATSAPP_VERIFY_TOKEN`, mode `600`, never printed),
  builds + starts the stack, waits for the health check, runs
  `alembic upgrade head`, and sets the agency branding via the API. Channels stay
  **SIMULATED** unless explicitly opted in. `--no-prompt` for provisioning scripts.
- **`docs/install.md`** — full single-office install + channel-enable + upgrade
  guide (no GPU — the LLM is cloud-hosted Kimi + MiniMax).

#### Public demo

- **`backend/scripts/seed_demo.py`** — idempotent demo dataset (*Sunset Realty
  Group*, Miami): 6 bilingual EN/ES leads + realistic conversations + 2 visits
  (scheduled / completed). Every row is tagged `meta.demo=true`; `--reset` wipes
  only the demo rows, `--keep-settings` preserves branding.
- **`deploy/cloudflared/config.example.yml`** + **`docs/setup-demo.md`** — a
  **dedicated** Cloudflare Tunnel for `inmo-demo.ekoaiautomation.com`, isolated
  from the sales-platform tunnel. Safety model: all channels SIMULATED (a visitor
  can never trigger a real send), seed data only, optional Cloudflare Access.

#### CI (green for the first time since Phase 1)

- **Backend**: added a real Postgres service + `alembic upgrade head` so the
  DB-backed tests actually run instead of erroring on a missing server. Ruff now
  ignores the 3 rules that conflict with intentional idioms (`B008` FastAPI
  `Depends`/`Query` defaults, `UP042` `str`+`Enum` for pg_enum, `UP037`
  SQLAlchemy quoted forward-refs) and auto-fixes the rest.
- **Frontend**: dropped `cache: npm` (there's no `package-lock.json`, so the
  cache step was aborting the whole job before tsc/lint).

#### Tests

- **+7 (84 total)**: `test_settings_api.py` (GET auto-create, PUT update +
  persistence, partial update, languages normalize/dedupe, empty-body 400,
  unknown-field 422, empty-languages 422). The singleton model test no longer
  couples to a specific `agency_name`.

## [0.5.0] — 2026-05-25

### Phase 5 — Calendar booking (Cal.com) + dashboard VisitsSection

The realtor can now book property visits from the dashboard. `/leads/[id]`
shows a **Visitas** section under the conversation with upcoming + past
visits, an **Agendar visita** button that opens a slot picker (next 7 weekdays,
groups by day, click slot + optional address/notes → Confirm), and a per-card
cancel.

#### Backend

- **`Visit` model** + Alembic migration `003_phase5_visits` (5 columns +
  `external_booking_id` UNIQUE for idempotency + status enum).
- **`services/calendar_cal.py`** — Cal.com v2 API wrapper:
  - `list_available_slots(start, end, timezone, busy_starts)` —
    SIMULATED returns weekday slots at 10/11/14/15/16 in-memory; production
    calls Cal.com `/v2/slots/available` with `cal-api-version: 2024-08-13`.
  - `create_booking(start_time, attendee_name, email, phone, notes, tz, duration)`
    — SIMULATED returns `calcom-sim-<uuid>` ids no-network; real Cal.com
    `POST /v2/bookings` otherwise.
  - `cancel_booking(external_id)` — IDs starting with `calcom-sim-` always
    cancel locally even in production mode (lets you clean up dev data).
- **Endpoints**:
  - `GET /api/v1/leads/{id}/calendar/slots?days=7&timezone=UTC`
  - `POST /api/v1/leads/{id}/calendar/book` → `Visit`
  - `GET /api/v1/leads/{id}/visits`
  - `POST /api/v1/visits/{id}/cancel` `{reason?}`
- Slots **excludes already-booked starts** for the same lead (`busy_starts`
  set built from active visits) so no double-booking.
- Attendee email/phone auto-picked from `lead.phone` (email if it contains `@`,
  phone otherwise). Real Cal.com requires email; SIMULATED accepts phone-only.

#### Frontend

- **`VisitsSection`** — lists upcoming + past visits with status badges,
  formatted ES dates, address, notes, per-card cancel button.
- **`BookingDialog`** — modal slot picker grouped by day, optional address +
  notes, real-time validation, `router.refresh()` style update via
  `onBooked()` callback.
- **`VisitStatusBadge`** — color-coded badge for the 5 visit statuses.
- `lib/api.ts` — `calendarApi.slots/book` + `visitsApi.list/cancel` + types.

#### Config

- + `CALENDAR_SIMULATED=true` (dev default — no Cal.com account required)
- + `CALCOM_BASE_URL=https://api.cal.com`
- `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID` from Phase 0 now actually used.

#### Tests (+13, total 77)

- `test_calendar_service.py` (7): simulated slots weekday-only, hours match
  the constant, busy_starts filter, list_available_slots simulated branch,
  create_booking returns `calcom-sim-` id, cancel_booking returns True,
  `calcom-sim-` id cancels locally even when SIMULATED=false.
- `test_visits_api.py` (6): /slots returns weekday slots, /slots 404 on
  missing lead, /book persists Visit with `calcom-sim-` id, /visits lists
  inserted, cancel flips status + rejects re-cancel, /slots excludes
  already-booked starts (no double-booking).

#### Docs

- `docs/setup-calcom.md` — Cal.com account + event type + API key + smoke
  test + troubleshooting matrix.

## [0.4.0] — 2026-05-25

### Phase 4 — Composer manual + AI reply suggestions

Completes the human-takeover loop. Phase 2 added the toggle that pauses the AI
agent; Phase 4 adds the UI to actually reply from the dashboard, plus an AI
helper that drafts 3 options the realtor can pick / edit / send.

#### Frontend

- **`Composer`** component below the chat in `/leads/[id]`: textarea +
  character counter (0/4000) + Send button. Sends via the lead's last-active
  channel — no channel picker needed for the common case.
- **"Sugerir respuestas"** button generates 3 alternative replies from the
  LLM. Each suggestion is a clickable card that fills the textarea — the
  realtor can edit before sending. Powered by the same Kimi + MiniMax fallback
  used by the agent itself.
- `router.refresh()` after a successful send → the new outbound bubble appears
  immediately, no page reload.
- Errors render inline below the composer (no toast/modal), keeping the
  realtor's attention on the conversation.

#### Backend

- **`POST /api/v1/leads/{id}/messages`** — accepts `{ "text": ..., "subject"?: ... }`.
  Auto-picks the channel from the most recently-active Conversation. For email,
  derives `Re: <subject>` from the last inbound + threads via `In-Reply-To`
  header. Persists as `Message(sender=HUMAN, direction=OUTBOUND)` and routes
  through the existing `_dispatch_send()` dispatcher.
- **`POST /api/v1/leads/{id}/suggestions`** — accepts `{ "count": int }`
  (clamped to `[1, 5]`). Builds a system prompt asking for a JSON array of N
  diverse short replies + the language-steering line from Phase 3. Parses the
  array tolerantly (matches first `[...]` block, drops empties, coerces to
  strings).
- **Degrades gracefully**: any LLM failure / invalid JSON / missing lead /
  empty conversation returns `{"suggestions": [], "error": "..."}` with HTTP
  200 so the UI shows an empty state instead of crashing.

#### Orchestrator

- Two new functions in `app/services/conversation.py`:
  - `send_human_message(lead_id, text, db, subject?)` — dispatches via the
    existing channel dispatcher and persists with `sender=HUMAN`.
  - `generate_reply_suggestions(lead_id, db, count=3)` — re-uses the same
    history-build + language-detection pipeline as the auto-reply, but with a
    "give me 3 options as a JSON array" prompt.

#### Tests

- **63 passing** on live ROG Postgres (+8 new):
  - human-send happy path (WhatsApp SIMULATED → outbound persists SENT
    with synthetic wamid).
  - human-send lead not found → `{status: error, error: lead_not_found}`.
  - human-send empty text → HTTP 400.
  - human-send lead without any Conversation → `error: no_active_conversation`.
  - suggestions happy path (3 quoted in valid JSON).
  - suggestions with prose around the JSON (parser extracts the array).
  - suggestions LLM returns non-JSON → empty list + error field.
  - suggestions count=99 clamps to 5.

## [0.3.0] — 2026-05-25

### Phase 3 — Multichannel + Email (Resend) + Bilingual (USA pivot)

**Strategic pivot**: target customers shift from EU real-estate offices
(WhatsApp-first) to USA realtors where SMS, Email and phone calls dominate.
WhatsApp remains an optional channel for international clients. Roadmap
reordered: Phase 4=SMS (Twilio), Phase 5=Voice (VAPI/Retell), Phase 6=Calendar
booking (moved from Phase 3), Phase 7=MLS/IDX, Phase 8=installer.

#### Multichannel refactor

- Schema rename to channel-agnostic names:
  - `messages.wa_message_id` → `external_id` (120 → 255 chars)
  - `messages.wa_status` → `delivery_status`
  - `conversations.wa_thread_id` → `external_thread_id` (80 → 255)
  - `leads.phone` widened 32 → 254 chars (RFC 5321 max email length — same
    column doubles as identifier for whatsapp/sms/voice and email)
- New `messages.subject` column (nullable, email-only).
- New `conversations.channel` index (queries filter on it constantly).
- `ParsedMessage` moved to `app/services/_common.py` with `channel`,
  `external_id`, `from_identifier`, `content`, `subject`, `thread_id` —
  single shared type emitted by every channel parser.
- Orchestrator routes outbound through `_dispatch_send(channel, ...)` →
  `whatsapp_send` / `email_send` (lazy imports). One conversation per
  `(lead, channel)`: a lead writing via both WhatsApp AND email gets two
  active conversations.

#### Email channel (Resend)

- `services/email.py`:
  - `send_email(to, subject, body_text, in_reply_to)` POSTs to
    `api.resend.com/emails` with threading headers.
  - `parse_inbound_email(payload)` returns `ParsedMessage(channel="email")`
    with subject + `thread_id` from In-Reply-To/References/Message-ID.
  - `verify_resend_signature(...)` Svix-style HMAC-SHA256 with multi-sig
    header support (key rotation).
  - `EMAIL_SIMULATED=true` (dev default) logs outbound instead of POSTing —
    no Resend account or domain DNS required.
- `POST /api/v1/webhooks/email` — same idempotency contract as the WhatsApp
  webhook (200 + UNIQUE `external_id` catches retries).
- New env vars: `EMAIL_SIMULATED`, `RESEND_API_KEY`, `RESEND_FROM`,
  `RESEND_WEBHOOK_SECRET`.

#### Bilingual agent

- `services/i18n.py` — `detect_language()` (langdetect, deterministic seed) +
  `pick_supported_language()` (clamps to AgentSettings.languages whitelist) +
  `language_instruction()` (steering line for the system prompt).
- Orchestrator detects on the **latest inbound only** (no bias from historical
  AI replies), picks `target_lang`, appends an "IDIOMA: el cliente escribe
  en X. Responde EXCLUSIVAMENTE en X" line to the system prompt.
- Classifier accepts optional `language_hint` so it disambiguates words like
  "rent" (EN) vs "renta" (ES, can mean income). JSON output values still
  English (rent/buy/valuation/other) regardless of input language.

#### Dashboard

- `MessageBubble` renders a channel icon next to the sender label (envelope
  email / message-circle WhatsApp / message-square SMS / phone voice) +
  shows the email subject above the bubble when channel="email".
- `LeadsTable` shows a heuristic glyph (email vs phone) next to the
  identifier so the realtor knows at a glance which channel the lead used.
- API client (`lib/api.ts`) interfaces updated to new field names.

#### Tests

- **55 passing** on live ROG Postgres (+10 new):
  - `test_email_service.py` (8) — signature accept/reject/missing/wrong-secret/
    multi-sig-one-matches + parser minimal/threading/html-fallback/non-received
    skipped/missing-from-skipped + send_email SIMULATED.
  - `test_i18n.py` (9) — detect ES/EN, short-text fallback, pick_supported,
    language_instruction both personas, unknown lang fallback.
  - `test_email_webhook_e2e.py` (1) — end-to-end POST → Lead (email
    identifier), Conversation(channel="email"), 2 Messages with subject +
    threading.
- Existing tests updated to use `external_id` / `delivery_status`.

## [0.2.0] — 2026-05-25

### Phase 2 — Realtor dashboard (UI for the Phase 1 backend)

What was protocol-only after v0.1.0 now has a face. The realtor can open
`http://<host>:3004/leads` and see the leads the AI captured, drill into
any conversation, and click one button to take over from the agent.

#### Frontend (Next.js 14 App Router)

- **`/leads`** — paginated list with status + intent filters (querystring-based,
  Suspense-wrapped so SSR works). Each row shows name, phone, status badge,
  intent badge, zone, budget range, relative time of last message, and a "Humano"
  pill when human_takeover is on.
- **`/leads/[id]`** — detail page with:
  - Lead header (avatar, name, phone, status + intent badges, last activity).
  - Metadata grid (zona, presupuesto, tipo, urgencia, created/updated timestamps).
  - **Takeover toggle** (top-right of header) — one-click PATCH to flip
    `human_takeover`. While ON, the orchestrator skips AI auto-reply (Phase 1
    already enforces this).
  - Conversation thread (chat-style bubbles, inbound left/outbound right,
    per-message LLM provider badge + Meta delivery status + timestamps).
- **`/about`** — public-facing landing kept (the Phase 0 placeholder) for
  sharing the product link. `/` redirects to `/leads`.
- **API client** — typed in `frontend/lib/api.ts` (Lead, Conversation, Message
  interfaces + `leadsApi.list/get/patch` + `conversationsApi.get`). All requests
  go through same-origin `/api/...`, which `next.config.js` rewrites to the
  backend container — works identically from LAN, Tailscale, or future
  Cloudflare tunnel without per-env URLs.
- **Components**: `Nav`, `StatusBadge`, `IntentBadge`, `FilterBar`, `LeadsTable`,
  `MessageBubble`, `LeadDetail`, `TakeoverToggle`. All Tailwind, Eko-violet
  palette, lucide-react icons.

#### Backend

- **`PATCH /api/v1/leads/{id}`** — partial update endpoint. Accepts any subset
  of `name | status | intent | zone | budget_min | budget_max | property_type |
  urgency | human_takeover`. Empty body → 400. Unknown field → 422 (Pydantic
  `extra='forbid'`). Missing lead → 404.

#### docker-compose

- Frontend now reads `INTERNAL_API_URL` at runtime for the rewrite (defaults
  to `http://backend:8000`). Build arg `NEXT_PUBLIC_API_URL` defaulted to `/api`
  since client JS no longer touches an absolute backend URL.

#### Tests

- `test_leads_api.py` (+8): list envelope, get 404, PATCH takeover roundtrip,
  PATCH partial update preserves untouched fields, PATCH empty 400, PATCH
  unknown field 422, PATCH invalid enum 422, PATCH 404. Total **33 passing**.

#### Brand

- Final rename Inmobiliario → **Eko AI Realtors** in `<title>`, landing copy,
  README, CLAUDE.md.

## [0.1.0] — 2026-05-25

### Phase 1 CORE — WhatsApp 24/7 + Kimi/MiniMax fallback + Lead capture

The product is now functional end-to-end at the protocol layer: an inbound
WhatsApp message → upsert Lead → save inbound message → classify intent →
generate AI reply → save outbound message → send. Frontend dashboard is still
Phase 2 (next).

#### Identity & infrastructure

- `CLAUDE.md` at repo root: anti-patterns ("never touch sales platform repos
  or containers"), port map across all 4 stacks on the ROG, brand name
  "Eko AI Realtors" vs repo name `Eko-AI-RealEstate`, LLM decisions
  (Kimi+MiniMax, NOT Anthropic OAuth for customer traffic), phase status.
- `docker-compose.yml` port remap to `5434/6381/8011/3004` (no collisions with
  sales prod, sales main dev, or pricing-v2 preview).
- Container rename `eko-realestate-*` for unambiguous identity.
- `.github/workflows/ci.yml`: ruff + pytest (backend) + tsc + lint (frontend)
  on every PR to main.
- GitHub repo: 10 topics, milestones for Phases 1–5, brand-aligned description.
- Memory file `project_eko_ai_realestate.md` + MEMORY.md pointer for
  cross-session continuity.

#### Database (SQLAlchemy 2 async + Alembic)

- `backend/app/db/base.py` — async engine + sessionmaker + get_db() FastAPI dep
  + `pg_enum()` helper (uses `.value` lowercase for Postgres enum members, not
  Python NAME).
- 5 models in `backend/app/models/`:
  - `Lead` — phone (UNIQUE), name, status enum (7 states), intent enum
    (rent/buy/valuation/other), budget_min/max, zone, property_type, urgency,
    last_message_at, human_takeover, meta (JSON), timestamps.
  - `Conversation` — lead_id FK CASCADE, channel, wa_thread_id, status, summary,
    started_at/last_at.
  - `Message` — conversation_id FK CASCADE, direction (inbound/outbound), sender
    (lead/agent/human), content, **UNIQUE wa_message_id** (webhook idempotency),
    wa_status, llm_provider, llm_model, created_at.
  - `Property` — placeholder for Phase 4 (Idealista/Fotocasa scrapers).
  - `AgentSettings` — singleton (id=1) with Spanish defaults for agent_persona,
    greeting_template, languages, business_hours.
- Baseline migration `20260525_1200_phase1_baseline.py` creates the 5 tables
  + indices + FK cascades + enum types.

#### LLM client (Kimi primary + MiniMax fallback)

- `backend/app/services/llm.py` — single entry `generate_reply()`. Inline
  fallback per request: if Kimi times out / 429 / 5xx, retries against MiniMax
  in the same request before raising `LLMUnavailable`.
- Both providers use the `anthropic` Python SDK with custom `base_url`
  (Anthropic-messages protocol).
- `json_mode=True` appends a "return JSON only" steer for the classifier.
- A/B test script (`backend/scripts/llm_ab_test.py`) ran 5 representative
  Spanish realtor prompts through both providers; results:
  - Kimi: avg 3,371 ms / 5/5 OK / more concise
  - MiniMax: avg 5,626 ms / 5/5 OK / more conversational
  - Decision: keep Kimi primary, MiniMax fallback (both produce natural ES).

#### Intent classifier

- `backend/app/services/classifier.py` — `classify_intent(messages)` returns
  `IntentResult` Pydantic schema (intent + confidence 0-1 + entities).
- Entities extracted: zone, budget_min, budget_max, property_type, urgency.
- Coerces `"1.500€"` strings to `1500.0` floats.
- Three failure modes degrade gracefully to `intent=OTHER + raw_response`:
  LLMUnavailable, JSON not parseable, JSON valid but schema mismatch.

#### WhatsApp webhook + orchestrator

- `backend/app/services/whatsapp.py`:
  - `verify_signature()` — HMAC-SHA256 with `WHATSAPP_APP_SECRET`,
    constant-time compare.
  - `parse_inbound_message()` — flattens Meta's nested
    entry/changes/value/messages tree; non-text types persisted as
    `[imagen]/[audio]/[video]/...` placeholders.
  - `send_text_message()` — POSTs to Meta Graph API; LOGS instead when
    `WHATSAPP_SIMULATED=true` (dev default).
- `backend/app/services/conversation.py` — `handle_inbound_message()`
  orchestrates the full 10-step turn: lead upsert → conv get-or-create →
  idempotency check → save inbound → human_takeover bypass → build history →
  classify intent (apply if confidence ≥ 0.55, never overwrite existing values)
  → load AgentSettings → generate reply → save outbound (PENDING) → send →
  update status (SENT/FAILED).
- `backend/app/api/v1/webhooks/whatsapp.py`:
  - `GET /api/v1/webhooks/whatsapp` — Meta verification handshake.
  - `POST /api/v1/webhooks/whatsapp` — signature verify (skipped in SIMULATED)
    → parse → orchestrator per message; always returns 200 unless body is
    malformed (Meta retries non-200; idempotency handles retries cleanly).
- Startup log warning if `WHATSAPP_SIMULATED=true` AND `APP_ENV=production`.

#### API routes

- `GET /api/v1/leads` — paginated list with `?status=` + `?intent=` filters.
- `GET /api/v1/leads/{id}` — detail.
- `GET /api/v1/conversations/{lead_id}` — most recent conversation + full
  message history ordered chronologically.

#### Tests (23 total, all passing on live ROG Postgres)

- `test_signature.py` (7) — HMAC valid, invalid, missing, wrong-prefix,
  body-tampered, wrong-secret, empty-secret.
- `test_llm_fallback.py` (4) — primary OK no fallback, primary timeout →
  fallback, both fail → LLMUnavailable, primary unconfigured → skip to fallback.
- `test_classifier.py` (7) — clean JSON, confidence clamp, prose-wrapped JSON,
  invalid JSON degrades, invalid enum degrades, LLMUnavailable degrades,
  budget coercion.
- `test_webhook_e2e.py` (4) — GET handshake accept, GET handshake reject,
  inbound text creates lead + reply, duplicate wa_message_id is idempotent
  (only 2 messages persist after 2 POSTs).
- `test_models.py` (2) — Lead/Conversation/Message roundtrip,
  AgentSettings singleton defaults.
- `test_health.py` (1) — health endpoint contract.

#### Scripts & docs

- `backend/scripts/simulate_inbound.py` — CLI to POST a simulated WhatsApp
  payload to the webhook for manual testing.
- `backend/scripts/llm_ab_test.py` — side-by-side LLM A/B with 5 Spanish
  realtor prompts.
- `docs/setup-whatsapp.md` — full production setup walkthrough (Meta App
  creation, secrets, webhook registration, troubleshooting matrix).
- `docs/architecture.md` — trust boundary + stack rationale (Postgres,
  Ollama-as-option, port choices).
- `docs/roadmap.md` — Phase 1 ✅ done, Phase 2-5 status.

## [0.0.1] — 2026-05-25

### Bootstrap

- Repo initialized with project skeleton (FastAPI + Next.js + Postgres + Redis)
- `docker-compose.yml` brings up the full stack locally
- Health endpoint at `GET /api/v1/health`
- Placeholder landing page on the frontend
- README + architecture + roadmap docs
- `.env.example` with the env vars required for Phase 1 (WhatsApp + LLM + DB)

# PROJECT STATUS

Estado de ejecución del plan `~/.claude/plans/si-haz-el-plan-jazzy-sifakis.md`
(**el embudo Denver Home Story**). Es un estado, no un diario: el historial de
v0.56.0 y anteriores vive en git y en el plan.

## Contexto en una línea

El embudo es: vídeos → redes de @denverhomestory → `www.denverhomestory.com` →
formulario o llamada → el sistema filtra, agenda y hace seguimiento → todo se
controla desde el panel. La **Fase A** es la casa: mover el sistema del portátil
de casa (ROG) al VPS, donde ya viven Zorros y Black Volt.

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

### 2. `business_hours` no gobierna las horas que se ofrecen

`calendar_cal.py:36` — `SIMULATED_HOURS_OF_DAY = (10, 11, 14, 15, 16)`, lunes a
viernes, **cableado**. `agent_settings.business_hours` (editable en Ajustes,
09:00–19:00) no lo lee el calendario: solo se usa en `conversation.py` para
*decirle* al lead el horario. El sistema anuncia 9–19 y ofrece cinco huecos
fijos. Arreglarlo solo merece la pena si Cal.com tarda: él se lleva esa función.

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

**Ejecutar A.1, el corte**, en cuanto el dueño lo autorice viendo estas
evidencias. Después: encender el puente de Ollama y verificar `off → ok`, mover
el vigía al ROG (A.2), y cerrar (A.3). Solo entonces, la Fase B con la landing.

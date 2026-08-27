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

### 🔴 A.1 — el corte: PREPARADO, NO EJECUTADO

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

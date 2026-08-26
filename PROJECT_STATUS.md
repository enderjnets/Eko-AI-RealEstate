# PROJECT STATUS

Estado de ejecución del plan `~/.claude/plans/si-haz-el-plan-jazzy-sifakis.md`
(v0.54.4 — durabilidad de entrega de avisos). Es un estado, no un diario.

## Contexto en una línea

Una revisión adversarial de Codex encontró que las dos capas de vigilancia de
v0.54.3 **daban una avería por comunicada aunque el email no hubiera salido**:
un fallo de transporte retiraba la transición y la avería no se volvía a
mencionar nunca. El watchdog reproducía internamente el fallo que existe para
evitar.

## Fases

| # | Fase | Estado |
|---|---|---|
| 1 | Capa 1: `alerted_state` + máquina de estados + tests | ✅ completada |
| 2 | Capa 2: `deploy/heartbeat.sh` escribe estado solo tras acuse | ✅ completada |
| 3 | Cierre: bump v0.54.4, changelog, checklist de despliegue | ✅ completada |

Rama: `feat/alert-delivery-durable`. **Sin commits a `main`. Sin despliegue.**

---

## Fase 1 — capa 1 (completada)

**Commit:** `b1fa424` en `feat/alert-delivery-durable` (subida a origin).

### Checklist de "terminado"

| # | Criterio | Resultado real |
|---|---|---|
| 1 | Tests en verde, sin saltados | ✅ `985 passed, 20 warnings in 125.28s` desde base recreada + `alembic upgrade head`. Cero `skipped`. (Antes del cambio: 977.) |
| 2 | Lint / typecheck | ✅ `ruff check app tests` → `All checks passed!` · `npx tsc --noEmit` → limpio (frontend sin tocar, control de regresión) |
| 3 | Build compila | ✅ `docker build -f backend/Dockerfile backend/` → OK, y dentro de la imagen `import app.main, app.services.llm_monitor, app.services.ops_alert` → OK. (Vía `docker compose build` falla en el Mac por interpolación: el `.env` vive en el ROG, no en este portátil — es entorno, no código.) Frontend: `npx tsc --noEmit` limpio. |
| 4 | Cobertura del código nuevo no baja | ✅ **SUBE.** No había herramienta; se instaló `pytest-cov` en el venv y se midió contra `main` en un worktree aparte, misma orden y mismos ficheros.<br>`main`: `llm_monitor 87%` · `ops_alert 94%` · **TOTAL 89%** (15 tests)<br>rama: `llm_monitor 87%` · `ops_alert 96%` · **TOTAL 90%** (23 tests)<br>Más **3 mutaciones verificadas** (abajo), que es la evidencia que un porcentaje no da: una línea puede estar cubierta y no comprobada. |
| 5 | Sin secretos en el diff | ✅ Barrido del diff por `api_key\|secret\|token\|password\|bearer\|re_[a-z0-9]{20,}` → sin coincidencias reales |
| 6 | Entrada validada, errores manejados, sin prints | ✅ Sin `print(`/`console.log`/`breakpoint(` añadidos. Todos los caminos de fallo de envío quedan en `log.error` y el tick continúa; `send_operator_alert` ya no puede propagar excepción (probado en `test_ops_alert.py`). |

### Mutaciones verificadas (el criterio real de que los tests ven algo)

| Mutación | Resultado |
|---|---|
| Avanzar `alerted_state` sin mirar el acuse del envío | 🔴 `test_failed_send_is_retried_next_tick` |
| Mover `last_seen_fallback_at = newest` antes del envío | 🔴 `test_failed_ground_truth_send_does_not_advance_the_mark` |
| Cobrar solo la entrega y no el intento | 🔴 `test_a_failed_send_spends_budget_so_a_broken_transport_cannot_loop` |

### Auditoría — hallazgos y qué se hizo

Dos auditorías independientes (correctitud y seguridad) sobre el árbol de
trabajo. **Ambas encontraron el mismo defecto en la migración**, y la de
correctitud encontró uno peor en el código nuevo. Los dos eran míos.

| # | Clasificación | Hallazgo | Estado |
|---|---|---|---|
| A | **BLOQUEANTE** | El reintento no tenía techo: `alerts_today` solo subía con éxito, así que `_budget_left` nunca cerraba → 288 intentos/día. Y como un envío **entregado** cuya respuesta expira (timeout 20 s) se lee como fallo, serían 288 correos **duplicados** contra la cuota que responde a los leads. Mi comentario afirmaba lo contrario y era falso. | ✅ **corregido**: se cobra el INTENTO. Medido: 6 ticks fallidos → 3 intentos, luego silencio |
| B | **BLOQUEANTE** | Backfill `alerted_state = state` sobre toda fila. La premisa ("v0.54.3 solo escribía `state` tras intentar avisar") es falsa: `row.state = status` estaba fuera de todo condicional. Enterraría el aviso pendiente que esta rama existe para rescatar. | ✅ **corregido**: `WHERE state = 'ok'`. Verificado migrando una fila averiada → `alerted_state` queda NULL (deuda pendiente) |
| C | **BLOQUEANTE** | Un fallo **permanente** de configuración (`OPS_ALERT_FROM` vacío — el defecto en `.env.example` y compose) se trataba como transitorio: reintento eterno que además congelaba `last_seen_fallback_at`, dejando una ventana sin límite sobre `messages.llm_provider`, que no tiene índice. | ✅ **corregido**: `undeliverable_reason()` separa "falló este intento" de "ningún intento puede llegar" |
| D | IMPORTANTE | **Regresión aceptada**: si la avería se auto-cura mientras el transporte falla, el hueco se cierra y el aviso pendiente se cancela en vez de reintentarse. Antes llegaba un correo de recuperación que nombraba la avería. Ventana: 300 s, y solo si además falla la entrega. La señal de **daño** (respuestas enlatadas) sí se conserva. | 🔶 **backlog** |
| E | MENOR | El cuerpo completo del aviso se escribe en `log.error` cuando el canal no está configurado. Con C corregido pasa de "cada 5 min para siempre" a "una vez por transición". Nota de forma: si alguien pusiera credenciales en `OLLAMA_BASE_URL`, acabarían ahí. | 🔶 **backlog** |
| F | MENOR | Preexistente, fuera del diff: las migraciones 019 y 041 interpolan `APP_DB_ROLE` en DDL con f-string. Solo explotable por quien ya controla el entorno. La 042 **no** repite el patrón. | 🔶 **backlog** |

Verificado limpio por la auditoría de seguridad, con evidencia: sin inyección
SQL en 042 (literal estático); `GRANT` de tabla de 041 cubre la columna nueva
(`information_schema.column_privileges` confirmado); RLS sigue desactivada a
propósito (`relrowsecurity='f'`); los `log.error` nuevos solo llevan literales
cerrados, enteros y fechas — ni `org_id`, ni lead, ni texto de conversación; el
aviso de respuestas enlatadas lleva un **número**, no contenido; `run_for_every_org`
corre bajo el rol con RLS FORCE, así que no hay fuga entre agencias.

### Decisiones y por qué

- **Columna nueva en vez de reordenar el commit existente.** `state` (lo
  observado) y `alerted_state` (lo comunicado) son dos hechos distintos y los
  dos hacen falta: `state` alimenta `/api/v1/health`, que es lo que lee el vigía
  externo. Colapsarlos fue el bug.
- **Backfill solo de las filas sanas.** La versión inicial copiaba `state` en
  toda fila; la auditoría demostró que la premisa era falsa. Una fila averiada
  se queda en NULL, que bajo las reglas nuevas es una deuda y se entrega en el
  siguiente tick.
- **El reintento es el siguiente tick, y se cobra el INTENTO.** El intervalo
  (300 s) es el backoff. La versión inicial cobraba solo las entregas, con el
  argumento de que reintentar es gratis; no lo es, porque un envío entregado
  cuya respuesta expira se lee como fallo. Cobrar intentos acota el bucle sin
  perder la deuda: sigue pendiente para el día siguiente.
- **Fallo permanente ≠ fallo transitorio.** Un canal sin remitente no se
  reintenta: ningún número de intentos llega a nadie, y mantener el hueco
  abierto congelaba el cutoff del barrido.
- **Sin Redis.** Está configurado pero ningún servicio lo usa; estrenar esa
  dependencia para cuatro campos no se justifica.

### Incidencias de entorno (resueltas, para que no sorprendan)

- Docker Desktop del Mac estaba parado y el contenedor **local de desarrollo**
  `eko-realestate-db` (no producción; producción vive en el ROG) había salido
  con código 0. Arrancados los dos.
- No había herramienta de cobertura. Instalada `pytest-cov` **en el venv**, no
  declarada en el repo. Si se quiere que la métrica sea reproducible en CI hay
  que añadirla a las dependencias — queda como MENOR en el backlog.
- `docker compose build` no funciona en el Mac (sin `.env`); el build real se
  hace con `docker build -f backend/Dockerfile`.

### Pendiente de la fase 3 (no es un hallazgo, es el orden del plan)

`APP_VERSION` sigue en `0.54.3` dentro de la imagen. El bump a `0.54.4` va en la
fase de cierre, antes de cualquier despliegue — `/api/v1/health` es la única
superficie con la que se comprueba que el despliegue entró.

---

## Fase 2 — capa 2, el vigía externo (completada)

**Commit:** `65f86be` en `feat/alert-delivery-durable`.

### Qué cambia

`send_alert` pasa de booleano a **tres desenlaces**: `0` entregado, `1` el
intento falló (reintentar), `2` no se puede entregar en absoluto (canal sin
configurar — no reintentar). El fichero de estado se escribe solo con `0` o `2`.
El contador diario cobra el **intento**, no la entrega, por la misma razón que
en la fase 1. Y `RESEND_URL` es overridable, que es lo único que permite probar
el camino de éxito sin mandarle un correo a una persona real en cada prueba.

### Checklist de "terminado"

| # | Criterio | Resultado real |
|---|---|---|
| 1 | Tests en verde, sin saltados | ✅ `997 passed` desde base recreada (985 → +12 del script). Cero `skipped`. |
| 2 | Lint / typecheck | ✅ `shellcheck deploy/heartbeat.sh` → sin avisos · `bash -n` → OK · `ruff` → `All checks passed!` |
| 3 | Build compila | ✅ El artefacto es el propio script: `bash -n` + `shellcheck` + **9 tests que lo ejecutan como subproceso de verdad**, no que lo lean. |
| 4 | Cobertura del código nuevo no baja | ✅ Medida con traza `PS4='+${LINENO} '` sobre los escenarios: **76%** de sentencias. Lo no cubierto son líneas de continuación que `bash -x` atribuye al comando entero (el `curl` multilínea, el cuerpo del email). La medición **encontró un hueco real** —la rama "responde 200 pero `llm_fallback` no es ok"— y se añadió el test que faltaba. Antes de esta fase el script tenía **0 tests**. |
| 5 | Sin secretos en el diff | ✅ Barrido limpio, y hay un test que lo afirma: `test_the_alert_carries_no_credentials` comprueba que ni la clave ni `Bearer` viajan en el cuerpo |
| 6 | Entrada validada, errores manejados, sin prints | ✅ `$code` y el contador se sanean contra basura (`case ... *[!0-9]*`); el payload se construye con `python3`/`json.dumps` y variables de entorno, no pegando cadenas en shell; sin `set -x` ni `echo` de depuración |

### Mutaciones verificadas

| Mutación | Resultado |
|---|---|
| Escribir `$STATE_FILE` incondicionalmente (el bug original) | 🔴 `test_a_rejected_alert_does_not_retire_the_outage` (+ el del techo) |
| Cobrar la entrega en vez del intento | 🔴 `test_the_retry_is_capped_so_a_broken_transport_cannot_mail_all_day` |
| Que `alert_rc` recoja el código de otra orden en la rama de recuperación | 🔴 `test_a_rejected_recovery_does_not_retire_it_either` |

### Auditoría de la fase 2 — hallazgos y qué se hizo

Dos auditorías (correctitud y seguridad). **Ningún bloqueante.** Lo notable es
que casi todo lo encontrado eran **guardarraíles míos a medio hacer**, no fallos
del script.

| # | Clas. | Hallazgo | Estado |
|---|---|---|---|
| G | IMPORTANTE | La rama de **recuperación** no la cubría ningún test: un mutante que hacía a `alert_rc` recoger el código equivocado sobrevivía 11/11, con una recuperación rechazada escribiendo `up` igualmente. El script hacía lo correcto; faltaba el guard. | ✅ **corregido**: test nuevo, verificado con el mutante del auditor |
| H | IMPORTANTE | La clave de Resend viajaba en el `argv` de `curl` → legible en `/proc/<pid>/cmdline` por cualquier usuario local. El `chmod 600` del `.env` no servía de nada. Preexistente, pero el diff reescribe ese mismo `curl`. | ✅ **corregido**: clave por `--config -` (stdin), cuerpo por fichero `0600`. Verificado mirando el `argv` en vuelo |
| I | IMPORTANTE | **Backlog**: cobrar el intento puede dejar mudo al vigía hasta ~13 h si el proveedor tiene un bache de 45 min. Es el intercambio consciente frente al bucle sin techo, y no es peor que `main` (allí el aviso se perdía del todo). Cierre propuesto por el auditor: techo **horario** para intentos, reservando el diario para entregas. | 🔶 **backlog** |
| J | MENOR | Mi test de la clave se esquivaba con `${RESEND_API_KEY}` (llaves) — un guard con bypass trivial es peor que ninguno. | ✅ corregido |
| K | MENOR | La mitad `Bearer` de `test_the_alert_carries_no_credentials` **no podía fallar**: el stub no guardaba cabeceras. | ✅ corregido: el stub las guarda y ahora se afirma que la cabecera llega íntegra |
| L | MENOR | Un fallo **permanente** al construir el payload (sin `python3` en el PATH escaso de cron) reintentaba sin techo y sin síntoma. | ✅ corregido: el contador se cobra por encima de todo lo que puede fallar |
| M | MENOR | El cron **documentado** mandaba toda la salida a `/dev/null` — justo el único canal donde se ve la deuda pendiente, el reintento y el canal inentregable. | ✅ corregido: la instalación documentada ahora escribe a `~/.eko-heartbeat/log` |
| N | MENOR | Un test omitía `RESEND_URL`: si alguien movía la construcción del payload, ese test llamaría al **Resend real** desde CI. | ✅ corregido |
| O | MENOR | Sin `flock`: dos ejecuciones solapadas mandan 2 correos y cobran 1. Preexistente e inalcanzable hoy (el script dura ~46 s contra un cron de 900 s). | 🔶 **backlog** |
| P | — | Mi comentario prometía un "reparto en tres" que el llamante no hace (0 y 2 se tratan igual). | ✅ comentario corregido para decir la verdad |

Verificado limpio con evidencia: sin inyección de shell ni de JSON desde el
cuerpo del endpoint (probado con `$(id)`, backticks, `;`, y con un intento de
inyectar un destinatario extra — `json.dumps` lo escapó); sin inyección de
cabeceras de correo (`tr -d` elimina CR/LF antes del `sed`); los saneadores
`case ... *[!a-z0-9]*` cierran la evaluación aritmética; ficheros de estado
corruptos degradan sin colgar ni perder el aviso; el cambio de día UTC libera el
presupuesto correctamente.

### Test intermitente ajeno a estas fases (diagnosticado, NO corregido)

`test_consent_holds_backfill.py::test_the_clamp_is_right_at_the_edges` falla de
forma intermitente. **Primero lo atribuí a no haber recreado la base; era falso**
— volvió a fallar recreándola. Causa real, probada:

```
siembra: scheduled_for = datetime.now(UTC)     <- reloj del HOST (Python)
SQL:     1 + FLOOR(EXTRACT(EPOCH FROM (NOW() - scheduled_for))/86400)
                                        ^ reloj del CONTENEDOR (Postgres)
```

Con `scheduled_days_ago=0` el caso queda **exactamente sobre un cambio de
signo**: transcurrido ≥ 0 da `1`; negativo por un microsegundo da
`FLOOR(-1e-7) = -1` → `1 + (-1) = 0`. La deriva medida entre los dos relojes es
de ~26 ms y cambia de signo, así que el test gana o pierde según el instante.

No es un fallo del producto (el SQL de la migración es correcto) ni de estas
fases (`test_consent_holds_backfill` no se toca en ninguna). Arreglo de una
línea: sembrar con el reloj de la base, no con el de Python. **Deliberadamente
no lo hago aquí**: tocar el test de otro módulo para que mi release salga verde
es una decisión que merece su propio commit, no colarse en este.

---

## Fase 3 — cierre (completada)

**Commit:** `f7a80bd`.

`APP_VERSION` y `CURRENT_VERSION` a **0.54.4** (`test_version_is_one_number.py`
fuerza la paridad y está en verde), entrada en `CHANGELOG.md` y entrada bilingüe
EN/ES en el changelog de la app.

### Checklist de "terminado"

| # | Criterio | Resultado real |
|---|---|---|
| 1 | Tests en verde, sin saltados | ✅ `997 passed` backend + `90 passed` frontend, cero `skipped`. ⚠️ Con una salvedad honesta: `test_consent_holds_backfill::test_the_clamp_is_right_at_the_edges` falla **de forma intermitente**, por comparar el reloj del host con el del contenedor sobre un cambio de signo. Ajeno a estas fases y diagnosticado abajo; no lo corrijo aquí. |
| 2 | Lint / typecheck | ✅ `ruff` → `All checks passed!` · `npx tsc --noEmit` → limpio · `shellcheck` → limpio |
| 3 | Build compila | ✅ backend: `docker build -f backend/Dockerfile` verificado en la fase 1 · frontend: `tsc` + `vitest` |
| 4 | Cobertura del código nuevo no baja | ✅ Esta fase no añade código ejecutable (versión + textos). Medida de la rama completa: `main` 89% → rama 90% en los módulos tocados. |
| 5 | Sin secretos en el diff | ✅ Barrido limpio |
| 6 | Entrada validada, errores manejados, sin prints | ✅ N/A en esta fase (sin lógica nueva) |

---

# ✅ DESPLEGADO — 26-ago-2026 (autorizado por el dueño)

**Ejecutado y verificado:** merge fast-forward a `main` + tag `v0.54.4` en
GitHub · bundle al ROG (`20200e4`) · imágenes construidas ANTES de migrar ·
`042_alerted_state` aplicada · `up -d` · vigía externo actualizado en
`ender-vps` con el cron corregido para dejar de tirar la salida a `/dev/null`.

| Verificación | Resultado real |
|---|---|
| `/api/v1/health` | `"version":"0.54.4"`, `"llm_fallback":"ok"` · frontend 200 |
| Backfill | `state='ok'` → `alerted_state='ok'`; el primer tick **no** mandó nada, como estaba previsto |
| Arranque | `LLM fallback monitor started (every 300s)` + los tres workers, sin errores |
| **Capa 1, reintento en vivo** | envío mockeado a `False`: `(unreachable, ok, 1)` → `(unreachable, ok, 2)` — **no se dio por comunicada y reintentó**. Al entregar: `(unreachable, unreachable, 3)`. Estado y presupuesto restaurados a `(ok, ok, 0)` |
| **Capa 2, reintento en vivo** | en `ender-vps` con estado desechable: fallo de entrega → `state` sigue `up` + `state NOT recorded`, y el siguiente ciclo **reintenta**. Estado real intacto |

Antes: `0.54.3` / migración `041`. Rollback documentado más abajo — **bajar la
migración ANTES de volver el código**.

### Variables de entorno

**Ninguna nueva.** `OPS_ALERT_FROM` ya se añadió al `.env` del ROG en v0.54.3
(`alertas@realtors.ekoaiautomation.com`, respaldo en `.env.bak.20260825`).
`LLM_MONITOR_INTERVAL_SECONDS` mantiene su valor por defecto de 300.

### Migración

`042_alerted_state`: **aditiva** — añade `monitor_state.alerted_state`
(`VARCHAR(30) NULL`) y rellena `alerted_state = state WHERE state = 'ok'`.
Sin bloqueo relevante: la tabla tiene **una fila**. No necesita `GRANT` (el de
tabla de 041 ya cubre columnas añadidas después; verificado en
`information_schema.column_privileges`). No activa RLS.

**Efecto concreto en esta instalación:** la fila está en `state='ok'`, así que
quedará `alerted_state='ok'` y el primer tick tras el despliegue **no** mandará
ningún correo. Si en el momento de migrar estuviera en cualquier otro estado,
quedaría NULL y el primer tick avisaría — que es lo correcto, porque ese aviso
nunca se entregó. Matiz: si entre migrar y ese primer tick el fallback se
recupera, la deuda NULL se consume en silencio (una lectura sana con
`alerted_state` NULL es una primera observación, no un cambio). Ventana de
minutos, y hoy no aplica porque la fila está en `ok`.

### Orden de pasos

```bash
# 0. Tras aprobar el merge de la rama a main: etiquetar (el bundle usa --tags,
#    pero nadie crea el tag por su cuenta)
git tag -a v0.54.4 -m "v0.54.4 — un aviso que no salio no comunica nada"
git push origin main && git push origin --tags

# 1. Llevar el código (bundle: no depende de que el ROG llegue a GitHub)
git bundle create /tmp/v0544.bundle main --tags
scp /tmp/v0544.bundle pcrug:/tmp/
ssh pcrug 'cd ~/Eko-AI-RealEstate && git fetch /tmp/v0544.bundle "main:refs/remotes/bundle/main" "+refs/tags/*:refs/tags/*" && git merge --ff-only refs/remotes/bundle/main'

# 2. CONSTRUIR ANTES DE MIGRAR (la migración corre con la imagen nueva)
ssh pcrug 'cd ~/Eko-AI-RealEstate && docker compose build backend frontend'

# 3. Migrar
ssh pcrug 'cd ~/Eko-AI-RealEstate && docker compose run --rm -T backend alembic upgrade head'

# 4. Levantar
ssh pcrug 'cd ~/Eko-AI-RealEstate && docker compose up -d backend frontend'

# 5. Actualizar el vigía externo (NO tocar ~/.eko-heartbeat.env)
scp deploy/heartbeat.sh ender-vps:~/eko-heartbeat.sh
ssh ender-vps 'chmod +x ~/eko-heartbeat.sh && chmod 700 ~/.eko-heartbeat'
# y cambiar el cron para que deje de tirar la salida a /dev/null:
#   */15 * * * * $HOME/eko-heartbeat.sh >>$HOME/.eko-heartbeat/log 2>&1
```

### Verificación posterior (con salida real, no inspección)

1. `curl .../api/v1/health` → `"version":"0.54.4"` y `"llm_fallback":"ok"`.
2. `SELECT key,state,alerted_state FROM monitor_state` → `ok | ok`.
3. Logs de arranque: `LLM fallback monitor started (every 300s)` + los tres workers.
4. **`PLATFORM_ADMIN_EMAILS` y `EMAIL_SIMULATED`** — los dos deciden en silencio
   si algún aviso llega a un humano, y ninguno es "nuevo", que es justo por lo
   que se olvidan:
   `docker exec eko-realestate-backend printenv | grep -E "PLATFORM_ADMIN_EMAILS|EMAIL_SIMULATED"`
   Con `PLATFORM_ADMIN_EMAILS` vacío, **todo** aviso cae en la rama
   consumir-sin-reintentar. Con `EMAIL_SIMULATED=true`, el envío "tiene éxito"
   sin tocar la red y `alerted_state` avanza por un correo que nadie mandó.
5. **Probar el reintento en vivo** (ojo: NO usando el canal sin configurar —
   esa rama consuma el estado a propósito, así que probaría lo contrario).
   Parchear `send_operator_alert` para que devuelva `False` en un tick forzado
   dentro del contenedor → `alerted_state` **no** debe avanzar y `alerts_today`
   sube a 1; segundo tick → vuelve a intentarlo. Restaurar y devolver
   `alerts_today` a 0.
6. En `ender-vps`: `~/eko-heartbeat.sh` con `HEARTBEAT_STATE_DIR` desechable y
   `RESEND_URL` a un stub → confirmar los tres desenlaces. Limpiar después.
7. Confirmar que **`~/.eko-heartbeat/log`** empieza a recibir líneas (esa es la
   ruta del cron; `~/eko-heartbeat.log` no existe).

### Plan de rollback

⚠️ **Solo existen imágenes `:latest`**, así que volver atrás significa
**recompilar desde el tag**, no arrancar una imagen guardada.

⚠️ **EL ORDEN IMPORTA Y NO ES EL INTUITIVO.** `backend/Dockerfile` hace `COPY . .`,
así que una imagen construida desde el árbol de v0.54.3 **no contiene** el
script `20260825_1200_alerted_state.py`. Si se hace el checkout primero, Alembic
aborta con `Can't locate revision identified by '042_alerted_state'` y el
rollback muere a medias. **La migración se baja ANTES de tocar el código.**

```bash
# 1. Bajar la migración PRIMERO, con la imagen que todavía tiene el script 042
ssh pcrug 'cd ~/Eko-AI-RealEstate && docker compose run --rm -T backend alembic downgrade 041_monitor_state'
# 2. Ahora sí, el código a v0.54.3 (rama, no tag: un checkout de tag deja
#    HEAD desacoplado y el siguiente `merge --ff-only` fallaría)
ssh pcrug 'cd ~/Eko-AI-RealEstate && git checkout main && git reset --hard v0.54.3'
# 3. Reconstruir
ssh pcrug 'cd ~/Eko-AI-RealEstate && docker compose build backend frontend'
# 4. Levantar y verificar que /api/v1/health dice 0.54.3
ssh pcrug 'cd ~/Eko-AI-RealEstate && docker compose up -d backend frontend'
# 5. Devolver el vigía externo a la versión de v0.54.3
ssh pcrug 'cd ~/Eko-AI-RealEstate && cat deploy/heartbeat.sh' | ssh ender-vps 'cat > ~/eko-heartbeat.sh'
```

**Qué se pierde al hacer rollback:** vuelve el defecto original — un aviso que no
salga dará la avería por comunicada. `alerted_state` se borra; `state`,
`alerts_today` y `last_seen_fallback_at` sobreviven. El vigía externo vuelve a
escribir su estado incondicionalmente.

**Punto sin retorno:** ninguno **si se respeta el orden de arriba**. La migración
es aditiva y reversible y no toca datos de clientes, pero deja de ser reversible
en el momento en que el árbol ya no contiene su propio script de bajada.

---

## Siguiente paso concreto

**Fase 2** — `deploy/heartbeat.sh`: la escritura final del fichero de estado es
incondicional, así que un aviso que no salió también da la caída por comunicada.
Aplicar la misma invariante que la fase 1, **incluida la lección de A**: el
reintento necesita techo. Ojo — el comentario actual del script defiende la
escritura incondicional diciendo que reintentar quemaría el presupuesto; ahí sí
es cierto que `send_alert` comprueba el tope antes de intentar la entrega, pero
ese tope solo cuenta **envíos aceptados**, así que tiene el mismo agujero que
tenía la capa 1. Contar intentos, no entregas.

Después, **fase 3**: bump a v0.54.4 (`config.py` + `version.ts` + los dos
changelogs), y preparar el checklist de despliegue **sin desplegar**.

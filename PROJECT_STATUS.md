# PROJECT STATUS

Estado de ejecución del plan `~/.claude/plans/si-haz-el-plan-jazzy-sifakis.md`
(**v0.56.0 — el filtro llega al carril vivo, y tres deudas del backlog**). Es un
estado, no un diario. La v0.55.1 quedó cerrada y desplegada el 26-ago-2026; su
historial vive en el plan y en git.

## Contexto en una línea

El filtro Fair Housing existe desde v0.52 y hasta hoy corría **solo sobre los
vídeos**: sus tres consumidores eran `api/v1/content.py`,
`services/content_studio.py` y `services/content_writer.py`. El carril que habla
con leads reales por SMS, email y WhatsApp —`services/conversation.py`— no lo
llamaba nunca. La protección se construyó donde era fácil, no donde está el
riesgo.

## Fases de v0.56.0

| # | Fase | Estado |
|---|---|---|
| 1 | El filtro corre sobre lo que sale hacia el lead | ✅ completada — `f63ef4e` |
| 2 | Recortar espacios donde el usuario escribe | ✅ completada — `a1820d8` |
| 2b | El `except IntegrityError` que reventaba y perdía el turno | ✅ completada — `a1820d8` |
| 2c | El timezone de una cita que la desplazaba seis horas | ✅ completada — `4b76280` |
| 3 | Aviso de tamaño antes de gastar la subida | ⏳ pendiente |
| 4 | El nav entre 768 y 1279 px + bump v0.56.0 | ⏳ pendiente |

Rama única: `feat/fair-housing-carril-vivo`. **Sin commits a `main`. Sin desplegar.**

---

## Fase 1 — el filtro en el carril vivo (completada)

**Qué se construyó**

- `messages.fair_housing_flags` (JSONB, migración `043_fair_housing_flags`).
  Sin backfill a propósito: NULL significa «nunca se comprobó», que es la
  verdad de las filas anteriores. Escribir `[]` afirmaría una revisión que no
  ocurrió.
- `conversation.py:1515` — `find_violations` sobre `reply_text`, **después** de
  `_with_broker_credits`, porque la atribución IDX se reproduce verbatim por
  obligación legal y una brokerage llamada «Perfect for Families Realty» pasaría
  de largo ante un filtro apuntado a `reply.text`. **Registra y envía igual**:
  decisión del dueño del 26-ago.
- `services/fair_housing_watch.py` — vigilante que avisa al operador una vez
  cuando un día limpio pasa a marcado. Monta en el bucle del monitor LLM que ya
  corría cada 300 s: sin task nuevo, sin ajuste nuevo, sin tocar el shutdown.
  Reutiliza el invariante de v0.54.4 (`alerted_state` solo avanza con un 2xx).
- Superficie: chip ámbar en `MessageBubble.tsx` con las frases en el `title`,
  campo en `api/v1/conversations.py`, tipo en `lib/api.ts`, i18n EN+ES.

**Checklist de «terminado» — resultado real**

| # | Comprobación | Resultado |
|---|---|---|
| 1 | Suite backend desde base recreada | ✅ **1031 passed**, 0 failed, 0 skipped |
| 1b | Baseline `main` en worktree aparte | 1019 passed — los 12 nuevos son míos |
| 1c | ~~3 `ERROR` "preexistentes"~~ | **corrección**: no eran del repo. `-p no:logging`, que yo añadía para acortar la salida, quita el plugin que provee `caplog`. Sin ese flag: **0 errores** |
| 2 | `ruff check app tests` | ✅ All checks passed |
| 2b | `npx tsc --noEmit` | ✅ sin errores |
| 2c | `npx vitest run` | ✅ 101 passed (9 ficheros) |
| 3 | `docker build -f backend/Dockerfile` | ✅ compila |
| 4 | Cobertura del código nuevo | ✅ `fair_housing_watch.py` **100%** (80/80) |
| 5 | Secretos/credenciales/endpoints en el diff | ✅ sin hallazgos |
| 6 | Validación, errores manejados, sin prints | ✅ sin `print`/`console.log`/TODO |

**Mutaciones verificadas** (guardar, mutar, ver rojo, restaurar) — 7 de 7:

| Mutación | Resultado |
|---|---|
| Quitar `find_violations` de `conversation.py` | 🔴 6 tests |
| `flags` → `flags or None` (limpio vuelve a NULL) | 🔴 2 tests |
| Quitar `none_as_null=True` del modelo | 🔴 `test_a_none_written_to_the_column_becomes_sql_null` |
| Filtro apuntado a `reply.text` en vez de `reply_text` | 🔴 `test_the_filter_runs_after_the_broker_credit_is_added` |
| `jsonb_array_length(...) > 0` → `isnot(None)` | 🔴 `test_a_busy_but_clean_day_is_not_an_email` |
| Quitar `created_at >= cutoff` (sin ventana) | 🔴 `test_a_flag_just_after_midnight_is_still_reported` |
| Quitar `await run_fair_housing_tick()` del bucle | 🔴 `test_the_watch_is_actually_scheduled` |
| Consumar `alerted_state` sin mirar el envío | 🔴 `test_the_watch_alerts_once_and_retries_a_failed_send` |

**Verificado contra la base, no supuesto**

- `eko_app` tiene `INSERT/SELECT/UPDATE` sobre la columna nueva sin GRANT
  adicional (`has_column_privilege` → `t|t`). El GRANT de tabla la cubre.
- Los 112 tests de los cuatro guardianes (barridos AST de opt-out y de
  publicación, `test_text_limits`, `test_config_example`) pasan **sin ninguna
  exención nueva**.

## Auditoría de cierre de la Fase 1

Dos revisiones independientes. **1 bloqueante reportado fue falso** y se
descartó con evidencia; **1 bloqueante real** y 5 importantes se corrigieron
en la fase.

| Hallazgo | Veredicto |
|---|---|
| «El presupuesto se cobra solo en éxito» | ❌ **descartado**: el auditor leyó mi fichero mutado (md5 `c592ef0…` vs real `5b4af21…`). El código carga `alerts_today` **antes** del envío |
| **Ningún test hacía tick con un `[]` en la tabla** | 🔴 **real y corregido**: revertir el filtro a `isnot(None)` habría mandado un correo de «día marcado» en un día enteramente limpio, porque las respuestas cribadas-limpias son `[]`. Test nuevo con tráfico limpio real |
| El día UTC cancelaba un aviso no entregado a medianoche | 🔴 real y corregido |
| Una marca en los 300 s tras medianoche silenciaba el día entero | 🔴 real y corregido |
| `NULL` vs `[]`: 3 docstrings lo prometían, el código no lo cumplía | 🔴 real y corregido — ahora se escribe `[]` de verdad |
| Mi test decía cubrir las plantillas de `followups` y no las tocaba | 🔴 real y corregido |
| `find_violations("") == []` es trivialmente cierto | 🔴 real y corregido |
| El `except` del bucle culpaba al monitor LLM del otro tick | 🔴 real y corregido |
| Bug **preexistente** en `conversation.py:1576-1590` | ⚠️ **al backlog** (ver abajo) |

Los tres primeros defectos de esa lista tenían **una sola causa**: el estado se
leía por día de calendario. Se sustituyó por una **ventana móvil de 24 h**, que
no tiene frontera por la que caerse.

**Nota de método, para las fases siguientes**: los dos auditores mutaron
ficheros de producción para medir la cobertura, y uno **me revirtió** la línea
109 desde un snapshot viejo mientras yo editaba. Se detectó por `grep`, no por
suerte. **En la Fase 2 los auditores trabajarán sobre un `git worktree` propio.**

## Hallazgos abiertos (backlog, no bloquean)

- 🔴 **Bug preexistente, reproducido**: `conversation.py:1576-1590`. El
  `except IntegrityError` escrito para «un proveedor repitiendo un id» **no se
  recupera: revienta**. Tras el rollback del savepoint el objeto queda
  expirado, y el `log.warning` toca `outbound.id` → refresh síncrono →
  `MissingGreenlet`, que escapa al `except Exception` de abajo, que vuelve a
  tocar `outbound.id`. Se pierde el turno entero. No es de esta rama.
- El vigilante devuelve su lectura y **nadie la consume**: con el canal de
  avisos sin configurar, un día de marcas vive solo en el log y en la columna.
  Falta un readout (no en `/health` público: es cumplimiento de clientes).
- El nombre de la agencia se interpola verbatim en las plantillas de nurture
  (`followups.py:808`) y ese texto **no se filtra**. Las plantillas están
  limpias hoy (medido); el valor interpolado no se comprueba en ningún sitio.
- Sin test para múltiples categorías en una respuesta, ni para JSON malformado
  en la columna (el `isinstance` defensivo funciona — medido — pero no está
  fijado).

---

## Fase 2 — recortar espacios donde el usuario escribe (completada)

**Qué se construyó**

- `settings.py`: **dos** validadores `mode="before"`, repartidos por la
  nulabilidad **real** de la columna (verificada en `information_schema`, no
  supuesta). `_trim` para las NOT NULL (`agency_name`, `agent_persona`,
  `greeting_template`, `timezone`); `_trim_or_clear` para las nullable
  (`brokerage_line`, `agency_phone`, `booking_contact_email`). Se retiró el
  `.strip() or None` que vivía en el handler: ahora hay una sola casa.
- `content.py`: `PieceEdit`, `DraftIn` (hook/script/caption) y `RejectIn.reason`.
- `public.py`: `PublicLeadIn` — `name`, `email`, `phone`, `message`.

**Por qué `mode="before"` y no `after`** — medido, no razonado: con `before`,
`"  Ashly  "` → `"Ashly"` y `"   "` → `""` → lo rechaza el `min_length=1` que ya
existía. Con `after` (o con un `.strip()` en el handler), `min_length` juzga la
cadena CRUDA, así que `" "` pasa la validación y se persiste. Es exactamente
cómo `agency_name` llegó a valer `"Ashly "`.

**Por qué dos validadores y no uno** — el diseño ingenuo («recorta y devuelve
None si queda vacío») convierte `agency_name=" "` en `None`, que el `setattr`
ciego del handler escribe en una columna NOT NULL: un **500 donde toca un 422**.

**Dos exclusiones deliberadas, con el motivo en el código**

- `website` (honeypot): se evalúa como `if body.website`, y `"   "` es truthy —
  hoy caza a un bot que rellena con espacios. Recortarlo lo **debilitaría**.
  Verificado leyendo la ruta, no asumido.
- `consent_text`: registro verbatim de lo que la persona consintió. Un registro
  legal no se normaliza.

**Bug preexistente encontrado y arreglado en esta fase**

`{"agency_name": null}` llegaba al `setattr` y devolvía **500**
(`NotNullViolationError`) — reproducido antes de arreglarlo. `exclude_unset` no
lo caza: un `null` enviado **sí** está *set*. Ahora es un 422 que nombra el
campo.

**Checklist — resultado real**

| # | Comprobación | Resultado |
|---|---|---|
| 1 | Suite backend desde base recreada | ✅ **1072 passed**, 0 failed, 0 errors, 0 skipped |
| 2 | `ruff check app tests` | ✅ All checks passed |
| 2b | `npx tsc --noEmit` · `npx vitest run` | ✅ sin errores · 101 passed |
| 3 | `docker build -f backend/Dockerfile` | ✅ compila |
| 4 | Cobertura del código nuevo | ✅ 6 mutaciones rojas (abajo) |
| 5 | Secretos en el diff | ✅ sin hallazgos |
| 6 | Validación, errores manejados, sin prints | ✅ limpio |

**Mutaciones verificadas** — 6 de 6:

| Mutación | Resultado |
|---|---|
| Quitar `_trim` (NOT NULL) | 🔴 11 tests |
| Quitar `_trim_or_clear` (nullable) | 🔴 9 tests |
| **`mode="before"` → `mode="after"`** | 🔴 8 tests — la trampa central de la fase |
| Quitar el trim de `content.py` | 🔴 5 tests |
| Quitar el trim de `public.py` | 🔴 4 tests |
| Desactivar el guard de `null` explícito | 🔴 4 tests |
| Quitar el manejo de `bytes` en los validadores | 🔴 3 tests |

**Instrumento**: los 16 tests de `test_settings_api.py` que ya existían siguen
verdes **sin tocarlos** — eso es lo que prueba que mover el strip del handler al
schema no perdió nada.

**Hueco encontrado alimentando basura a los validadores** (no leyéndolos):
Pydantic convierte `bytes` a `str` **después** de un validador `mode="before"`,
así que `isinstance(value, str)` dejaba pasar `b"  x  "` sin recortar mientras
el mismo valor como `str` sí se recortaba. No alcanzable por JSON, que no tiene
bytes — pero un guard con un agujero es cómo se sorprende el siguiente. Cerrado
en los cinco validadores.

**Test flaky preexistente, ajeno a esta fase**:
`test_consent_holds_backfill.py::test_the_clamp_is_right_at_the_edges` falló una
vez en suite y pasó aislado y en la corrida siguiente. Causa verificada: usa
`datetime.now(UTC)` con márgenes de **1 minuto** (`postponed_until = now - 1min`,
`:65`) dentro de una suite que tarda 3 minutos. No menciona ninguno de los
esquemas que toqué. Al backlog.

---

## Fase 2b — el `except` que mataba el turno que iba a salvar (completada)

Pedido por el dueño tras el informe de la Fase 1: *«corrígelo y va en v0.56»*.

**El fallo, reproducido antes de tocarlo.** `messages` lleva
UNIQUE (org_id, external_id), y estampar el id que devuelve el proveedor puede
colisionar. `conversation.py` abre un savepoint justo para eso — pero **un
rollback de savepoint EXPIRA todos los objetos que tocó**, así que el
`log.warning` del propio manejador, que leía `outbound.id`, era una carga
perezosa síncrona dentro de código async: `MissingGreenlet`. Eso no es
`IntegrityError`, así que escapaba al `except Exception` de fuera, **cuyo primer
acto era leer `outbound.id` otra vez**. Se perdía el turno entero — y la
respuesta ya había salido por el cable: el lead contestado y sin registro.

La lección estaba escrita en este mismo repo, en `followups.py:423-427`:
*«even `fu.id` becomes a synchronous lazy load and raises MissingGreenlet
outside every handler here»*. `conversation.py` la incumplía.

**Arreglo**: `outbound_id` capturado como `int` antes del savepoint, y
`await db.refresh(outbound)` en el manejador. **Medido, no supuesto: cada mitad
basta por separado**; solo mutando las dos a la vez se pone rojo el test. El
comentario dice eso en vez de afirmar que ambas son necesarias.

**Cobertura nueva**: `test_duplicate_provider_id.py` — el turno sobrevive, el
segundo mensaje cede el id en vez del turno, y ambos leads con su mensaje
entrante siguen ahí. Más un control que impide que el arreglo sea «no estampar
nunca».

## Auditoría de cierre de las Fases 2 y 2b

Un auditor en **worktree propio** (`/tmp/eko-audit-f2`) y base propia, tras el
incidente de la Fase 1. **Dos bloqueantes reales, uno de ellos regresión mía.**

| Hallazgo | Veredicto |
|---|---|
| **Vaciar hook/script/caption dejó de funcionar** | 🔴 **regresión mía, corregida**. Mi validador convierte `""` en `None` y el handler saltaba los `None`: el realtor vaciaba el campo, recibía **200**, y el texto volvía. El console manda los tres campos en cada guardado. **Cobertura previa: cero.** Ahora usa `model_fields_set` — «¿se envió?» en vez de «¿es None?» |
| **La guarda de `null` cubría 4 de 6 columnas NOT NULL** | 🔴 real, corregida. `languages` daba `TypeError` y `business_hours` llegaba a Postgres: el mismo defecto, a medias, dentro de la función que lo arreglaba. Ahora se **deriva de `AgentSettings.__table__`** en vez de escribirse a mano |
| **Mi manejo de `bytes` empeoró las cosas** | 🔴 revertido. Cambiaba un 422 limpio por aceptar `b"\xff\xff\xff"` → tres U+FFFD, que satisfacen el `min_length=3` que ese validador existe para hacer cumplir. Entre dos comportamientos inalcanzables por JSON, el que rechaza es el correcto |
| **El validador de `public.py` era un no-op** | 🔴 retirado. `capture.py` ya normaliza los cuatro campos; la fila guardada era idéntica con y sin él. Código que no hace nada se lee como cobertura |
| **`consent_text` NO se guarda verbatim** | 🔴 afirmación falsa mía, corregida. Pasa por `clean_text`, que colapsa saltos de línea. Mi comentario prometía lo contrario sobre el campo cuyo trabajo entero es defensa legal |
| El `.strip()` del timezone era código muerto | 🔴 retirado |
| «Los espacios se quemarían en el vídeo» | 🔴 falso: `content_render.py:310` ya recorta. Corregido |

**Mutaciones verificadas** — 9 de 9 rojas, incluidas las tres nuevas:
volver a `is not None` en el editor · lista de NOT NULL escrita a mano ·
las dos mitades del arreglo del `except` a la vez.

## Hallazgo del auditor que NO entra aquí (backlog, con evidencia)

🔴 **`visits.py:119` — `ManualEventIn.timezone` no se valida, y falla en
silencio.** `_resolve_wall_clock` (`visits.py:265-268`) se traga el
`ZoneInfoNotFoundError` y devuelve `when.replace(tzinfo=UTC)`. Un timezone
pegado con un espacio delante (`" America/Denver"`) guarda una cita de las 10:00
como 10:00 **UTC** = **04:00 en Denver**: seis horas de desfase, con 201 y sin
un solo aviso. Incoherente con `settings.py`, que valida la misma cadena con
`ZoneInfo` y devuelve 400. Es más grave que cualquier cosa de esta fase y NO lo
he tocado porque está fuera de su alcance. **Decisión del dueño.**

Otros al backlog: `platform.py:63` (`OrgCreateIn.name="  "` crea una
organización con nombre en blanco), `platform.py:645` (`InviteIn.email` sin
recortar), `visits.py:109` (`title="   "`), y `form` en el formulario público
(un valor en blanco da 404 en vez de caer al fallback).

---

## Fase 2c — seis horas, en silencio, con un 201 (completada)

Pedido por el dueño tras el informe de la Fase 2: *«sí arréglalo y agrégalo a
la v0.56»*.

**El fallo, reproducido antes de tocarlo.** `ManualEventIn.timezone` y
`BookingIn.timezone` no se validaban, y `_resolve_wall_clock` se tragaba el
`ZoneInfoNotFoundError` devolviendo `when.replace(tzinfo=UTC)`. Medido:

```
'America/Denver'    -> 2026-09-15T16:00:00+00:00   (10:00 Denver, correcto)
' America/Denver'   -> 2026-09-15T10:00:00+00:00   (04:00 Denver, SEIS HORAS antes)
'Invented/Zone'     -> 2026-09-15T10:00:00+00:00
```

Un espacio delante, pegado desde cualquier sitio, y la cita se archiva seis
horas antes con **HTTP 201** y el string malo guardado al lado. El docstring de
la propia función nombra ese número —*«in Denver, six hours apart»*— tres líneas
antes de causarlo. Y `settings.py` valida esa misma cadena con `ZoneInfo` y
devuelve 400: un producto, dos respuestas a una entrada.

**Arreglo en tres capas**: helper `_valid_timezone` que recorta y prueba la zona
· colgado de los dos esquemas · y `_resolve_wall_clock` deja de caer a UTC —
lanza 400 nombrando el valor, porque llegar ahí ya solo puede significar que la
configuración de la agencia está rota, y ese es un dato que hay que arreglar,
no rodear. De paso, `title="   "` pasaba `min_length=1` y salía en blanco en la
agenda: mismo orden mal, mismo arreglo.

**El mismo defecto, encontrado buscándolo en vez de esperarlo.** Un `grep` de
`ZoneInfoNotFoundError` destapó `voice.py:158` haciendo exactamente lo mismo en
el carril que habla por teléfono: caía a UTC con un `log.warning`. Cada hora que
el asistente cotiza y cada cita que reserva quedaban seis horas fuera; a un lead
al que le dicen «martes a las 2 PM» le cierran la puerta a las 8 AM, y el único
rastro es una línea de log que nadie lee durante una llamada. Arreglarlo solo en
`visits.py` habría sido reparar la mitad visible.

Ahí el arreglo tuvo que ser distinto: el manejador promete por contrato **no
lanzar nunca** (una excepción cuelga al asistente en mitad de la llamada). Así
que `_office_zone` devuelve `None` y la herramienta responde con una disculpa
hablada — *«no puedo consultar el calendario ahora; alguien te llamará»*. No es
lo ideal; es lo honesto: no se ofrece una hora que no se puede calcular.

**Checklist — resultado real**

| # | Comprobación | Resultado |
|---|---|---|
| 1 | Suite backend desde base recreada | ✅ **1084 passed**, 0 failed, 0 errors, 0 skipped |
| 2 | `ruff` · `tsc` · `vitest` | ✅ limpio · limpio · 101 passed |
| 3 | `docker build` | ✅ compila |
| 4 | Cobertura del código nuevo | ✅ 6 mutaciones rojas |
| 5 | Secretos en el diff | ✅ sin hallazgos |
| 6 | Validación, errores manejados, sin prints | ✅ limpio |

**Mutaciones verificadas** — 6 de 6:

| Mutación | Resultado |
|---|---|
| Sin recorte del timezone | 🔴 5 tests |
| Sin validar la zona | 🔴 2 tests |
| Vuelve el fallback a UTC en `visits.py` | 🔴 2 tests |
| Sin recorte del título | 🔴 2 tests |
| Vuelve el fallback a UTC en `voice.py` | 🔴 2 tests |
| **El bug original completo (tres capas revertidas)** | 🔴 el test imprime `which is 6:00:00 off` |

Esa última es la que vale: el test no dice «falló», dice **el número exacto del
daño**. Una primera mutación mía fue inválida (sustituyó un `return None` de
otra función 70 líneas antes) y el test «sobrevivió»; lo cacé comprobando dónde
había aterrizado en vez de creerme el resultado.

### Auditoría de la Fase 2c — hecha por mí, y por qué

**El auditor independiente se cortó**: `You've hit your monthly spend limit`
(se restablece a las 19:30, hora de Denver). Alcanzó a confirmar la suite
completa en su propia base —**1083 passed**— y murió mutando los tests de voz,
que yo ya había verificado. Completé sus once puntos a mano. **Dicho sin
adornos: una auto-auditoría vale menos que una independiente**, y este repo ya
tiene registrado que mi auto-revisión declaró una vez un arreglo inexistente.
La Fase 3 debería re-auditar este diff cuando el límite se restablezca.

| Punto del encargo | Resultado |
|---|---|
| El 400 nuevo, ¿puede saltar tras reservar en Cal.com? | ✅ **No.** `_resolve_wall_clock` corre antes de `_ensure_slot_free` y de `create_booking`. Sin riesgo de reservar fuera y fallar dentro |
| ¿Otros sitios con el mismo fallback? | ❌ **Dije «uno». Eran cuatro.** Ver la re-auditoría abajo |
| ¿El validador está registrado en ambos esquemas? | ✅ verificado en `__pydantic_decorators__`, no supuesto |
| Reparto por nulabilidad de `title`/`notes`/`property_address` | 🔴 **fallo mío, corregido**: di el validador de solo-recorte a dos columnas nullable, así que guardaban `""` donde el esquema dice «sin notas». Misma regla que ya había establecido en `settings.py`, aplicada por inercia en vez de mirando las columnas |
| DST | ✅ intacto: 02:30 del salto de primavera sigue rechazándose con 400 |
| ¿El borrado de filas del test es determinista? | ✅ ningún otro test usa 2028-09-20; los demás usan fechas relativas |
| Regresiones | ✅ 1084 passed |

**Un hallazgo que solo aparece midiendo en los dos sitios**: `america/denver` en
minúsculas **se acepta en mi Mac y se rechaza en producción** — `ZoneInfo` lee
tzdata del sistema de ficheros, y macOS no distingue mayúsculas. Mi entorno
local es **más permisivo** que el real, así que un test verde aquí puede estar
probando algo que producción rechaza. Documentado en el helper.

### Re-auditoría de la Fase 2c — `d1a1603`

Dos auditores independientes, en worktrees y bases aisladas, con ángulos
separados (correctitud/regresiones y seguridad/radio de explosión).
**Convergieron por separado en los mismos dos hallazgos grandes**, que es lo
que los hace creíbles. Los dos eran míos. Verifiqué cada uno midiendo antes de
aceptarlo; ninguno resultó falso esta vez.

| Hallazgo | Clase | Estado |
|---|---|---|
| **Mi guard convertía un 422 en un 500.** `ZoneInfo` lanza **tres** tipos de excepción; yo cogía dos. Y al ser `mode="before"`, corre ANTES de `max_length=50`, así que un timezone de 300 caracteres —que siempre había sido un 422 limpio— escapaba entero. Un guard que empeora la entrada que protege | 🔴 bloqueante, **regresión mía** | ✅ arreglado |
| **El bug reportado seguía vivo en el GET de al lado.** `list_slots` pasaba el timezone sin validar a `list_available_slots`, cuyo `except Exception` cae a UTC. Medido: `10:00-06:00` → `10:00+00:00`. Seis horas, 200, y el string malo devuelto en la respuesta. Es el endpoint que llena el diálogo de reserva | 🔴 bloqueante | ✅ arreglado |
| `BookingIn` escribe las **mismas dos columnas nullable** que `ManualEventIn` y se quedó sin la regla de «vacío = ausente» | importante | ✅ arreglado |
| El docstring de `settings.py` argumentaba por qué `isinstance(v, str)` no basta para `bytes`… encima de código con exactamente ese guard. `agency_name=b"  Ashly  "` se guardaba sin recortar | importante | ✅ arreglado |

**Lo que esto corrige del registro de arriba**: escribí «¿otros sitios con el
mismo fallback? Sí, uno». Eran **cuatro**. Mi barrido buscó la *forma* que yo
acababa de escribir (`except (ZoneInfoNotFoundError, ValueError)`) en vez de la
*pregunta* («¿dónde se convierte una zona inservible en una hora concreta?»), y
por eso encontró el sitio que se parecía al mío y no los tres que hacían el
mismo daño.

### Los otros dos sitios — decididos y cerrados en `2cf1ce0`

**Decisión del dueño**: cuando la zona horaria de la agencia es inservible, el
lead **no recibe horas**. Ni en UTC con aviso, ni deducidas del prefijo del
teléfono. La respuesta sale igual, sin horas dentro.

`calendar_cal.py` lanza ahora `UnusableTimezone` (subclase de `CalComError`, así
que todos los llamadores que ya degradaban con elegancia siguen haciéndolo) y
`conversation.py` devuelve `""`. **Las dos guardas se dejan a propósito**:
medido, cada una por separado basta, y esa redundancia es la que quiero.

**Descartada, con motivo**: usar el huso del visitante. No hay ningún visitante
con navegador — `public.py` tiene un solo endpoint sin login (el formulario de
captura) y el panel ya muestra la zona de la oficina deliberadamente
(`BookingDialog.tsx:50`). Un lead por SMS es un número de teléfono.

**Comprobación pre-despliegue que no pude hacer** (el clasificador bloqueó el
`ssh`): si alguna fila de producción tiene `agent_settings.timezone` inválido,
este cambio la convierte de un 201 silencioso en un **400 duro** en cada cita
manual y un 422 en cada reserva. Hay que mirarlo antes de desplegar:
`SELECT id, org_id, timezone FROM agent_settings;`

**Una cosa que dije de más en el commit de la 2c**: afirmé que unificaba «un
producto, dos respuestas a una entrada». No lo hace — `settings.py` devuelve
400 y `visits.py` 422, porque un validador de Pydantic no puede emitir 400. Las
dos rechazan, que era lo que importaba, pero la unificación no ocurrió.

## Fase 3 — el aviso de tamaño, antes de gastar la subida (completada)

`3b1db3b` (implementación) + `9d034cb` (arreglos de auditoría).

**Checklist, resultado real**: 1107 backend + 108 frontend verdes, 0 saltados ·
`ruff check app tests` y `npx tsc --noEmit` limpios · imagen compila · sin
secretos en el diff · mutaciones verificadas en las dos capas del backend y en
la guarda del cliente.

**Qué cambió**: `CONTENT_UPLOAD_MAX_MB` de 500 a **95** en los tres sitios a la
vez, `upload_max_mb` expuesto en `StudioStatus`, y el navegador comprueba
`file.size` **antes** de abrir la petición. El test que importa no comprueba que
rechace: comprueba que **`sent` quede vacío**.

### La auditoría, y el hallazgo que era mío

| Hallazgo | Clase | Estado |
|---|---|---|
| **Bajar el tope no desbloqueó la puerta: movió el ladrillo.** Escribí que a 95 respondería la ruta con su mensaje. No: el middleware `BodySizeLimit` de `main.py` corta cualquier petición que declare `Content-Length` —toda subida de navegador— y devuelve el token interno `body_too_large`. Medido: `95 MB + 1 byte -> {"detail":"body_too_large"}` | 🔴 bloqueante | ✅ arreglado |
| **Mi test pasaba precisamente por eso**: `monkeypatch` del ajuste a 1 MB, pero `_STREAM_PATHS` se construye al importar desde ese ajuste, así que el middleware seguía en 95. Una configuración que no puede existir | 🔴 bloqueante | ✅ arreglado |
| `API 413: body_too_large` en crudo a la agente, en inglés, con la frase traducida para ese evento sin usar | importante | ✅ arreglado |
| El changelog nombraba la 0.56.0, que aún no existe | importante | ✅ quitado |
| `toFixed(1)` decía «pesa 95 MB y el límite son 95 MB» | menor | ✅ redondeo hacia arriba |
| El tope no se enseñaba antes de elegir fichero — la justificación que escribí y no cumplí | menor | ✅ arreglado |
| Docstring espejo de TS, `CHANGELOG.md`, y el número de línea del comentario | menor | ✅ los tres |

**La forma del error, otra vez**: afirmé en un comentario algo que el código no
hacía, y escribí un test que no podía fallar por el motivo por el que producción
falla. Lo irónico es que **mi propio comentario en `UploadClip.tsx:48` ya avisaba**
de que el rechazo «puede llegar como `body_too_large`». El comentario tenía razón
y el mensaje del commit lo contradijo.

**Las dos capas se quedan, y no son redundantes**: el middleware mira el
`Content-Length` declarado (lo que fija un navegador) y la ruta cuenta bytes al
llegar, que es la única guarda contra un cuerpo **troceado** que no declara
longitud. Mutando cada capa por separado cae exactamente un test distinto.

**Coste dicho en voz alta**: un clip de 96 MB que ayer pasaba, hoy se rechaza.
95 y no 99 porque ~100 MB es donde se **observó** que rompe el túnel, no una
cifra documentada, y un tope al borde de un acantilado medido falla intermitente
en vez de limpio.

**Deuda anotada, no arreglada**: un clip de 4K de más de 95 MB sigue sin poder
subirse. La salida real es subida por trozos, y es otra versión.

**Siguiente paso concreto**: Fase 4 — el nav entre 768 y 1279 px (mover el corte
de `md` a `lg` en `Nav.tsx` **y** en `globals.css:31`, un `OverflowMenu`
reutilizable, y gatear `/discovery` con `isOperator` en escritorio), más el bump
a **v0.56.0** en los cuatro sitios.

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
| 2 | Recortar espacios donde el usuario escribe | ⏳ pendiente |
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
| 1c | 3 `ERROR` en `test_ops_alert` / `test_whatsapp_channel` | **preexistentes**: idénticos en el baseline |
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

**Siguiente paso concreto**: Fase 2 — recortar espacios en los campos de texto
(dos validadores `mode="before"` según la nulabilidad de la columna; el diseño
ingenuo de un solo validador escribe NULL en columnas NOT NULL).

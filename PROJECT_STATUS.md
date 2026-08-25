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
| 2 | Capa 2: `deploy/heartbeat.sh` escribe estado solo tras acuse | ⬜ pendiente |
| 3 | Cierre: bump v0.54.4, changelog, checklist de despliegue | ⬜ pendiente |

Rama: `feat/alert-delivery-durable`. **Sin commits a `main`. Sin despliegue.**

---

## Fase 1 — capa 1 (completada)

**Commit:** `b1fa424` en `feat/alert-delivery-durable` (subida a origin).

### Checklist de "terminado"

| # | Criterio | Resultado real |
|---|---|---|
| 1 | Tests en verde, sin saltados | ✅ `985 passed, 20 warnings in 125.28s` desde base recreada + `alembic upgrade head`. Cero `skipped`. (Antes del cambio: 977.) |
| 2 | Lint / typecheck | ✅ `ruff check app tests` → `All checks passed!` · `npx tsc --noEmit` → limpio (frontend sin tocar, control de regresión) |
| 3 | Build compila | ⚠️ Parcial. El backend no tiene paso de build propio (su "build" es la imagen Docker, que se construye en el despliegue — y el despliegue está explícitamente fuera de alcance). Typecheck del frontend sí verificado. |
| 4 | Cobertura del código nuevo no baja | ❌ **NO VERIFICABLE.** No hay herramienta de cobertura: `pytest --help` no expone `--cov`, `import coverage` → `ModuleNotFoundError`, y no está declarada en `pyproject.toml` ni en ningún `requirements*.txt`. Instalarla sería un cambio de entorno fuera del alcance de la fase. **Evidencia sustitutiva** (más fuerte que un porcentaje, porque una línea puede estar cubierta y no comprobada): 4 tests nuevos en el monitor + 4 en el canal + **3 mutaciones verificadas** (abajo). |
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

### Incidencia de entorno (resuelta, para que no sorprenda)

Docker Desktop del Mac estaba parado y el contenedor **local de desarrollo**
`eko-realestate-db` (no producción; producción vive en el ROG) había salido con
código 0. Arrancados los dos; la suite corre desde base recreada.

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

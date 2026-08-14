# La consola de llamada + motor de seguimiento — diseño

> Proyecto **E**. Fecha: 2026-08-13. Estado: **en construcción.**
> Hermanos: **A** landing + chat calificador (diseñado) · **B** rescate del
> abandono · **C** autopiloto de redes · **G** marcador asistido + email frío ·
> **F** esfera y referidos · **D** atribución.

## Contexto

Natalia y Robbie ya tienen llamadas hoy. Lo que aprenden en cada una —interés,
urgencia, qué busca, cuánto tiene— muere en una libreta.

Esa libreta es la razón de que el motor ya construido no gire. El emparejador
de propiedades lee `leads.intent/budget/zone/property_type`; el scoring lee los
mismos campos; el nurture arranca solo cuando hay una visita. Si nadie escribe
lo que se supo en la llamada, esos campos se quedan como los dejó el formulario
y toda esa maquinaria trabaja sobre una foto vieja.

**La landing produce llamadas. La consola convierte llamadas en clientes.** Es
el único proyecto que rinde sin tráfico, y tres de los otros cuelgan de él.

**Resultado que se mide:** porcentaje de llamadas registradas, y porcentaje de
llamadas que terminan en un siguiente paso concreto — visita agendada, opciones
enviadas, o seguimiento programado.

## Restricciones verificadas (leídas del código, no supuestas)

1. **`Lead` no tiene canal preferido.** Sus columnas son `phone, name, email,
   status, intent, budget_min, budget_max, zone, property_type, urgency,
   last_message_at, human_takeover, score, score_breakdown, meta, consent_*,
   opted_out_*, inbox_handled_at`. No hay dónde guardar *«prefiere que le
   llamen»*.
2. **El motor de seguimiento está atado a una visita.** Los cuatro
   `FollowUpKind` son `reminder_24h`, `post_visit_24h`, `post_visit_72h`,
   `post_visit_7d`, y la única alta es `enqueue_for_visit()`
   (`followups.py:123`). **No existe camino para nutrir a quien habló contigo y
   aún no agenda** — el caso más común tras una llamada.
3. **La elección de canal ya respeta el consentimiento.** `process_due_followups`
   (`followups.py:191`) arma candidatos y, si ninguno tiene consentimiento
   registrado o un mensaje entrante previo, **retiene y reintenta al día
   siguiente**, con un contador de rendición. El opt-out se aplica además en la
   frontera de despacho (`delivery.py:186`).
4. **`visits.property_address` es texto libre.** No hay FK a `Property`: hoy
   agendar «ver esta casa» no deja rastro de *qué* casa.
5. **No existe ningún modelo de llamada** ni de resultado de llamada.
6. **`UNIQUE(visit_id, kind)`** hace idempotente el alta por visita, pero en
   Postgres dos NULL no colisionan: no protege a un follow-up sin visita.
7. **Sin datos de REcolorado.** Producción tiene 9 propiedades `source=manual`,
   `state=FL`. El trámite de MLS Grid nunca se inició.
8. **RLS por defecto deniega**: toda tabla de inquilino necesita `org_id` y su
   política en la migración, o la leen todas las agencias.

## Decisión 1 — La consola escribe sobre el `Lead`, no al lado

`match_properties_for_lead()` (`listings.py:660`) y `compute_lead_score()`
(`scoring.py`) leen exactamente los campos que la llamada revela. Si la consola
los actualiza, el emparejador y el scoring funcionan **sin adaptación**.

Un modelo paralelo de «notas de llamada» habría exigido que alguien lo
sincronizara con el lead, y ese alguien no existe.

Lo único que se guarda aparte es el **registro de la llamada** (`CallLog`):
quién llamó, cuándo, resultado, nota. Eso es historia; el estado sigue viviendo
en el lead.

## Decisión 2 — El resultado de la llamada ES el disparador

Marcar no es archivar: es ejecutar. Un toque, una consecuencia.

| Resultado | Acción automática |
|---|---|
| **Quiere ver propiedades** | pantalla de propuestas → enviar la selección |
| **Agendar visita** | `calendar_cal.create_booking()` + `enqueue_for_visit()` |
| **Seguimiento en N días** | `enqueue_after_call()` en el canal preferido |
| **No contestó** | reintento en la cola de mañana |
| **Ya trabaja con otro agente** | NAR Art. 16: cancela lo pendiente, `paused` |
| **No molestar** | opt-out por la vía existente, cancela todo lo pendiente |
| **Número equivocado** | marca el teléfono inservible, no se le escribe más |

## Decisión 3 — La preferencia estrecha, nunca abre

Columna nueva `leads.preferred_channel` (`sms | email | call`, nullable).

**La preferencia solo reordena y estrecha la lista de candidatos que el worker
ya calcula. Jamás salta la retención por falta de consentimiento ni el
opt-out.** Que alguien diga «mándame un texto» es una preferencia; el
consentimiento TCPA es otra cosa y se registra aparte.

**`call` como preferido no es un robocall.** No hay proveedor de voz (Fase 13
diferida) y un robocall a un móvil es exactamente lo que TCPA castiga. Un
follow-up con canal `call` **se materializa como tarea humana** en la cola de
hoy, no como envío.

## Decisión 4 — El sistema propone, la humana decide

Tras guardar la llamada, la consola muestra las mejores N de
`match_properties_for_lead()` y **Natalia marca cuáles enviar**. Es su licencia
y su relación con el cliente; el sistema no manda casas solo.

**Los datos de la ficha los pinta el código y la atribución IDX es una
plantilla, nunca el LLM** — este repositorio ya pagó ese error cinco veces.

Hoy no hay propiedades de Colorado, así que **sin resultados es el caso normal,
no el error**: la sección lo dice y el resto de la consola funciona entera.

## Decisión 5 — El consentimiento capturado en la llamada

Cuando el cliente dice «sí, mándamelas», eso es consentimiento verbal y hay que
poder probarlo. El chip de envío por SMS exige confirmar que lo pidió en la
llamada; si el lead no tenía consentimiento previo se escriben
`consent_at/_text` con una frase fija que registra la petición verbal, quién la
marcó y en qué llamada.

**Sigue siendo de una sola escritura**: si ya existe, no se toca. El comentario
de `lead.py:102` («only ever set by the public capture form») se actualiza,
porque deja de ser cierto.

## Decisión 6 — La visita apunta a la propiedad

`visits.property_id` FK nullable (se conserva `property_address`). Sin eso el
post-visita no puede ser específico y la atribución no puede existir.

## Decisión 7 — La cola de hoy

Si hay tareas de canal `call` y reintentos, tienen que aparecer en algún sitio.
`/console`: **la lista de hoy** — llamadas a hacer, leads calientes sin tocar, y
**follow-ups retenidos por falta de consentimiento**, que hoy solo se ven en los
logs. Una lista, no un dashboard.

## El riesgo de diseño, y la regla que lo contiene

El riesgo no es técnico: es **un formulario que nadie rellena**. Si marcar una
llamada cuesta más de un minuto, no se marca, y el dato que llegue será basura.

Por eso: **toques, no escritura**; pre-rellenado con lo que ya se sabe —Natalia
**confirma y enriquece**, no transcribe—; y el resultado dispara la cadencia
solo, sin una segunda pantalla.

## Componentes

| Pieza | Qué hace | Dónde |
|---|---|---|
| `CallLog` (nuevo) | registro de la llamada + migración **con RLS** | `models/call_log.py` |
| `leads.preferred_channel` (nuevo) | canal que el cliente prefiere | migración |
| `visits.property_id` (nuevo) | qué casa se va a ver | migración |
| `follow_ups.call_log_id` + `UNIQUE` (nuevo) | idempotencia sin visita | migración |
| `services/calls.py` (nuevo) | `register_call()` transaccional | backend |
| `enqueue_after_call()` (nuevo) | nurture post-llamada | `followups.py` |
| `match_properties_for_lead()` | **se reutiliza** | `listings.py:660` |
| `compute_lead_score()` | **se reutiliza** | `scoring.py` |
| `calendar_cal.*` | **se reutiliza** | `calendar_cal.py` |
| `optout.py`, `delivery.py` | **se reutilizan** | backend |
| Panel de llamada | chips + campos pre-rellenados | `components/leads/` |
| `/console` | la lista de hoy | `app/console/` |

**Lo que NO se construye:** emparejador nuevo, sistema de consentimiento nuevo,
cliente de calendario nuevo, scoring nuevo. Todo eso existe.

## Verificación

- Cada resultado de llamada → su acción exacta, y ninguna otra.
- **La preferencia estrecha, nunca abre**: preferido sin consentimiento → se
  retiene igual; opt-out → cero envíos por cualquier canal.
- Canal `call` → tarea, jamás envío.
- Consentimiento: una sola escritura, con quién lo marcó y en qué llamada.
- «Ya tiene agente» / «no molestar» → pendientes cancelados, cero envíos luego.
- Idempotencia: registrar dos veces la misma llamada no duplica follow-ups.
- RLS: los `call_logs` de una organización son invisibles para las demás.
- Módulo de propiedades vacío → la consola completa funciona.
- Lead sin teléfono, sin email o sin nombre → el panel no rompe.
- **Extremo a extremo en navegador contra producción.** Un 200 no es
  verificación.

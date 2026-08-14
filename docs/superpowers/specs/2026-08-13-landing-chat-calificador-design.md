# Landing + chat calificador — diseño

> Proyecto **A** de cuatro. Fecha: 2026-08-13. Estado: **diseño, pendiente de revisión.**
> Proyectos hermanos, cada uno con su propia especificación:
> **B** rescate del abandono · **C** autopiloto de redes · **D** atribución por vídeo.

## Contexto

Natalia y Robbie (una organización, dos usuarios — ver `models/organization.py`)
quieren dejar de depender de la llamada en frío. El modelo que les enseñaron en
un entrenamiento —40 llamadas diarias durante dos años hasta construir una
cartera— funciona pero cuesta dos años. La apuesta es sustituir ese arranque por
tráfico entrante desde vídeo corto.

Esta pieza es **el destino de ese tráfico**: una landing pública donde un
visitante frío obtiene, en menos de un minuto y sin registrarse, una respuesta
concreta a *«¿qué podría comprar yo en Denver?»*, y desde ahí agenda una
asesoría de 15 minutos con Natalia y Robbie.

**Resultado que se mide:** llamadas de 15 min agendadas por cada 100 visitas, y
en qué paso exacto se cae el resto.

## Restricciones verificadas (no supuestas)

1. **No hay datos de REcolorado.** Producción tiene 9 propiedades, todas
   `source=manual`, `state=FL`: el set simulado de Miami. Sin
   `RESO_ACCESS_TOKEN` ni `RESO_BASE_URL` en el `.env` del ROG. El código de
   ingesta existe y está probado (v0.35.0), pero **el trámite de MLS Grid nunca
   se inició**. Es semanas de calendario y depende del managing broker.
2. **Acceso al feed ≠ derecho a mostrarlo en público.** Enseñar una ficha dentro
   de una conversación privada y publicarla en una landing abierta son permisos
   distintos. El IDX display público tiene su propio acuerdo, su texto exacto de
   descargo y sus reglas de frescura y atribución.
3. **No hay rate limiting en ninguna capa** (documentado en `CLAUDE.md`). Una
   superficie pública con LLM sin cuota es una factura esperando a pasar.
4. **Un solo worker, una sola réplica** — precondición dura de
   `tenant_resolver._cache`.
5. **TCPA.** El consentimiento se registra tal como se mostró:
   `leads.consent_at/_text/_ip/_user_agent`, y es de una sola escritura.
6. **NAR Artículo 16** prohíbe interferir con una representación exclusiva
   vigente.
7. **Engel & Völkers + reglas de publicidad de Colorado**: el material debe
   identificar a la brokerage. La landing se aprueba con el managing broker.
8. **LLM: Kimi primario, MiniMax de respaldo**, siempre por
   `llm.py:generate_reply()`. Nunca OAuth de Anthropic.

## Decisión central: el esqueleto es una máquina de estados, no un modelo

Se descartó el chat de IA de conversación libre. En tráfico frío desde móvil el
cursor en blanco es una página en blanco disfrazada, cada visita cuesta dinero
sin cuota que la limite, y un modelo que redacta datos de una ficha MLS es una
exposición legal, no un bug.

Lo que se construye **se ve y se siente como un chat** —una pregunta a la vez,
tono cálido, avanza contigo— pero las respuestas son botones y el recorrido es
determinista.

**El LLM tiene exactamente tres trabajos, los tres fuera del camino crítico:**

1. Interpretar una respuesta escrita a mano que no encaja en ningún botón
   (`"como 2 mil y pico"` → tramo 2.000–2.500). Si no puede, se vuelve a
   preguntar; no se adivina.
2. Responder una pregunta fuera de guion (*«¿aceptan FHA?»*), con tope duro de
   turnos por sesión.
3. Escribir la frase cálida de la pantalla de resultados.

**Criterio de aceptación, y es el test que manda: con el LLM caído o fuera de
presupuesto, el embudo se completa entero y se agenda la llamada.**

**Los datos de una propiedad los pinta el código, nunca el modelo.** La línea de
atribución IDX es una plantilla. Este repositorio ya pagó ese error cinco veces
(ver `feedback_atribucion_idx_cinco_intentos`).

## El recorrido

```
0. Gancho          «¿Cuánto pagas de renta? Te digo en 60 segundos
                    qué podrías comprar en Denver con eso.»
                    [ Quiero comprar ]  [ Quiero vender ]
                                │
1. Renta actual    chips: <$1.500 · $1.500–2.000 · $2.000–2.500 ·
                          $2.500–3.000 · +$3.000 · escribirlo
2. Enganche        chips: <$10k · $10–25k · $25–50k · +$50k · aún no sé
3. Cuándo          0–3 meses · 3–6 · 6–12 · solo explorando
4. ¿Ya trabajas    Sí → desvío cortés, sin captura agresiva
   con un agente?  No → continúa
                                │
5. RESULTADO       el rango + el desglose mensual honesto
                   + [hueco de propiedades: vacío hasta que exista el feed]
6. Captura         «¿A qué número te las mando?» + consentimiento
7. Agendar         botón → Cal.com, 15 min
```

**El interés no es una pregunta.** Viene pre-rellenado y con un enlace pequeño
de «ajustar». Preguntarle a un visitante frío qué tasa asumir es pedirle que
haga nuestro trabajo, y es la pregunta con más abandono: no la sabe.

**El contacto se pide como una entrega, no como un peaje.** *«¿A qué número te
mando estas opciones?»* es un favor; *«rellena tus datos para ver los
resultados»* es un impuesto. Es el mismo campo. Y es el momento natural para
registrar el consentimiento TCPA en contexto.

**Se guarda desde la primera respuesta.** Quien abandona en el paso 2 deja
rastro: eso es lo que permite arreglar el embudo, y es lo que un formulario no
da.

## La matemática de asequibilidad

El anclaje emocional es *«lo mismo que pagas de renta»*. La tentación es
calcular qué precio da un principal+interés igual a la renta. **Eso miente por
un 15–25%**, porque ignora impuestos, seguro y HOA — y la mentira se descubre
en la llamada, que es el peor momento posible: quema la confianza y le gasta el
tiempo a Natalia.

Por tanto el cálculo incluye impuesto predial estimado, seguro y HOA, y **se
muestra el desglose mensual completo**, no solo el precio.

Se presenta como **rango**, nunca como cifra exacta, y con el descargo pegado al
número en el propio componente — no en un pie de página.

Parámetros configurables por organización (Settings), no constantes en el
código: tasa de interés, tasa de impuesto predial, seguro estimado, HOA típico.

### Decisión pendiente del cliente: el prestamista

Diseño la derivación hipotecaria como **módulo enchufable**. Si Natalia y Robbie
trabajan con un loan officer, el paso 5 ofrece la pre-aprobación como siguiente
acción —convierte mucho mejor y saca la matemática hipotecaria de manos no
licenciadas—. Si no, el hueco queda vacío y el único siguiente paso es la
llamada. La respuesta no bloquea el trabajo.

## Que las propiedades puedan faltar es la decisión de arquitectura, no un parche

El premio que promete el gancho **es el número**, no las tres casas. Las casas lo
hacen tangible, pero son justo la parte que depende de un trámite ajeno y de un
permiso legal separado.

Por eso el bloque de propiedades es un módulo que **degrada**: cuando no hay
resultados para los criterios —que es *hoy, siempre*— la pantalla de resultados
muestra el rango, el desglose y los barrios de Denver donde ese rango es
realista, y sigue hasta agendar. El embudo se completa sin una sola fila de MLS.

Cuando el feed y los derechos de display lleguen, el hueco se llena y no se
reescribe nada.

## Componentes

| Pieza | Qué hace | Dónde |
|---|---|---|
| `QualifierSession` (modelo nuevo) | sesión anónima: `org_id`, respuestas, paso, atribución de origen, marcas de tiempo | `models/qualifier_session.py` + migración Alembic |
| `services/qualifier.py` (nuevo) | la máquina de estados: definición de pasos, validación, avance. Sin LLM | backend |
| `services/affordability.py` (nuevo) | el cálculo, puro y sin E/S. Tabla de casos en tests | backend |
| `api/v1/public.py` (existe) | endpoints nuevos de sesión bajo el mismo módulo público ya protegido por Turnstile | backend |
| `services/capture.py` (existe) | **se reutiliza tal cual** para crear el `Lead` y registrar consentimiento | backend |
| `match_properties_for_lead()` (existe) | emparejador ya escrito; se le da un adaptador para criterios de sesión anónima | `services/listings.py:660` |
| `services/calendar_cal.py` (existe) | agendado de 15 min | backend |
| `llm.py:generate_reply()` (existe) | los tres trabajos acotados, con `json_mode` para el parseo | backend |
| Landing (nuevo) | ruta pública, mobile-first, i18n ES/EN | `frontend/app/` |

**Lo que NO se construye:** un modelo de propiedades nuevo, un sistema de
consentimiento nuevo, un cliente de calendario nuevo, un emparejador nuevo.
Todo eso existe.

## Coste y abuso (entra en la v1, no después)

- **Turnstile** en el arranque de sesión — ya construido, pendiente de claves.
- **Tope de turnos y de tokens por sesión.**
- **Límite de creación de sesiones por IP.**
- **Presupuesto diario de LLM por organización**, con interruptor que degrada a
  modo puramente guionizado en vez de dar error.

El camino guionizado no llama al LLM nunca, así que quemar presupuesto exige
esfuerzo deliberado.

## Verificación

- Máquina de estados: cada paso, cada rama, reanudación desde cualquier punto.
- **LLM caído → el embudo se completa.** **LLM fuera de presupuesto → íd.**
- Turnstile sin secreto → el arranque de sesión se niega en producción.
- Consentimiento: una sola escritura, con el texto exacto mostrado.
- Atribución IDX presente aunque el LLM devuelva vacío o basura.
- RLS: una sesión pertenece a una organización y solo esa la ve.
- Asequibilidad: tabla de casos, incluidos impuestos, seguro y HOA.
- Extremo a extremo **en navegador contra producción**. Un `curl` con 202 no
  demuestra nada.

## Decisiones que dependen del cliente

| # | Decisión | Bloquea |
|---|---|---|
| 1 | ¿Hay prestamista socio? | el CTA del paso 5 (no el resto) |
| 2 | Dominio propio para la landing | el despliegue, no la construcción |
| 3 | La llamada: ¿Natalia, Robbie, o alternando? | la configuración de Cal.com |
| 4 | Aprobación de marca E&V con el managing broker | publicar, no construir |
| 5 | **Solicitud del feed MLS Grid + derechos de display IDX** | solo el bloque de propiedades |

Ninguna bloquea empezar. La 5 es la más lenta y hay que arrancarla ya.

# PLAN — La red de seguridad del LLM, arreglada de una vez

> Escrito el 5-sep-2026 tras diagnosticar en producción. **Ejecutor: Opus 5.**
> Modo de trabajo: una fase cada vez, máx. 3 intentos de corrección por fase,
> un commit convencional por fase, push, **sin merge ni PR sin pedirlo, sin
> desplegar sin autorización en un mensaje aparte**. Advisor en las fases
> [CRÍTICA] y tras el 2º intento fallido; registrar cada consulta en
> `PROJECT_STATUS.md`. Footer de commit: el de atribución vigente en la sesión
> del ejecutor + `Claude-Session:`.

---

## Contexto — por qué se hace esto

El producto encadena tres eslabones de LLM: **Kimi → MiniMax → Ollama local**.
El tercero es la última red: cuando los dos de pago fallan a la vez (un 429 en
un plan de suscripción es rutina; pasó el 1-jun-2026 con 403+429 en el mismo
minuto), es lo único que impide que un lead reciba *"alguien te responderá en
breve"* en vez de una respuesta.

**Diagnóstico del 5-sep (medido, no supuesto). Hay DOS averías independientes**
— el mismo patrón de la v0.54.2, donde arreglar una sola *parece* un arreglo:

- **Avería 1 — la red apunta a un portátil de casa intermitente.**
  `OLLAMA_BASE_URL=http://100.88.47.99:11434` es el ROG por Tailscale. Se
  **colgó** (encendido, ventiladores girando, pero congelado) y estuvo **7 h
  fuera de la red** por LAN y por tailnet. Su propio worker de vídeo está
  diseñado para funcionar a ratos (`monitor_state.render_worker` lleva horas de
  trabajo). Un producto en el VPS no puede tener su último recurso en una
  máquina que se cuelga y se cae del tailnet. *(Al cierre del diagnóstico el ROG
  se reinició y volvió: el VPS lo alcanza y `gemma3:4b` está; el fuego inmediato
  está apagado, la fragilidad no.)*

- **Avería 2 — la alarma no llega.** `monitor_state.llm_fallback`:
  `state=unreachable`, `alerted_state=ok`, **3 avisos gastados hoy**, presupuesto
  agotado. El ROG *parpadeó* (cae/vuelve), eso consumió el tope de 3/día, y
  cuando se colgó de verdad el aviso ya no salió. El canal verifica bien (clave
  de Resend válida, dominio `realtors.ekoaiautomation.com` verificado), pero hay
  **un solo transporte** (email) teniendo **Telegram configurado y sin usar**
  para esto (`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` presentes).

**Resultado buscado:** que exista una tercera red **siempre disponible** que no
dependa del ROG, y que si alguna vez la cadena entera falla, el dueño se entere
**sí o sí** (por dos canales, sin que un parpadeo lo silencie).

---

## Alcance

**Dentro:** (1) un tercer eslabón de LLM siempre disponible; (2) una alarma de
operador fiable (doble canal + anti-parpadeo + reset del estado atascado); (3)
verificación de extremo a extremo.

**Fuera, dicho en voz alta:** vigía externo en otra máquina para el caso "el
backend entero muere" (`deploy/heartbeat.sh` ya existe; esto es otra cosa);
reescribir el sistema de proveedores; tocar cualquier servicio del ROG
(crontab, bittrader, ollama, coqui — **prohibido**).

---

## Decisión del dueño (pendiente de confirmar al aprobar)

**Recomendado — Opción B: tercer proveedor en la nube.** Añadir un proveedor
compatible con el protocolo Anthropic como tercer eslabón, del mismo modo que ya
funcionan Kimi y MiniMax (mismo SDK, **sin ruta de código nueva** como sí la
tiene Ollama). Siempre disponible, sin gastar RAM del VPS (7,3 GB / 2 vCPU,
compartido con Zorros y Black Volt), y con calidad suficiente para respetar el
prompt de Fair Housing. El ROG deja de ser load-bearing (puede quedar como
eslabón extra opcional cuando esté vivo, nunca como el único).

- Candidatos, a confirmar endpoint en la **Fase 0**: DeepSeek
  (`/anthropic`), Z.ai/GLM, u otro Anthropic-compat. Coste: centavos + una clave
  que crea el dueño (como la de YouTube). El agente no la ve.

**Alternativa — Opción C (sin proveedor nuevo):** apagar la red falsa
(`OLLAMA_ENABLED=false`), y confiar en que la alarma de doble canal (Fase 2) te
avise al instante para tomar el control manual (el producto ya soporta traspaso
a humano). Cero infra, cero coste. En la caída doble el lead recibe la línea de
espera, pero te enteras al momento. Si eliges esto, la Fase 1 se reduce a apagar
el flag y documentarlo; las Fases 2 y 3 siguen igual.

**No recomendado — Opción A (modelo local en el VPS):** un modelo pequeño en
CPU de 2 núcleos puede redactar respuestas inmobiliarias con riesgo de Fair
Housing ("ideal para familias"), que recae en la licencia del bróker, y
tensiona la RAM compartida. Descartada salvo que lo pidas expresamente.

---

## Comandos del proyecto (la definición de "terminado")

```bash
# Backend — base con nombre propio de esta tarea (NO reusar la de otra sesión)
docker exec eko-realestate-db psql -U eko -d postgres \
  -c "DROP DATABASE IF EXISTS eko_realestate_test_llm WITH (FORCE)" \
  -c "CREATE DATABASE eko_realestate_test_llm OWNER eko"
cd ~/Eko-AI-RealEstate/backend
PW=$(docker exec eko-realestate-db printenv POSTGRES_PASSWORD)
export DATABASE_URL="postgresql+asyncpg://eko:${PW}@localhost:5434/eko_realestate_test_llm"
export DATABASE_URL_APP="postgresql+asyncpg://eko_app:eko_app_local_pass@localhost:5434/eko_realestate_test_llm"
export WHATSAPP_ENABLED=true
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m pytest -q -p no:cacheprovider --cov=app
./.venv/bin/python -m ruff check app tests --output-format=concise
```

Referencia de verde: **1550 backend** (medido hoy). Cada fase cierra con la
suite en verde **sin saltados**, `ruff app tests` limpio, la(s) mutación(es) de
la fase verificada(s) (copia, mutar, ver el rojo, restaurar, `md5` idéntico), y
`docker build -f backend/Dockerfile backend` OK. Cobertura del código nuevo ≥ la
del fichero que toca (ojo: `coverage` infra-mide handlers `async`; medir con
`concurrency = greenlet` si hace falta, sin cambiar la config del repo).

**Guardianes que muerden** (leer antes de escribir): `test_config_example.py` +
`test_compose_env.py` → **3 ediciones por setting** (`config.py`, `.env.example`,
bloque `backend:` de `docker-compose.yml`, valores idénticos);
`test_version_is_one_number.py` (`APP_VERSION` = `CURRENT_VERSION` = cabecera de
`CHANGELOG.md`); i18n no aplica aquí (nada de UI nueva salvo, si acaso, texto de
`/health`).

**Nunca imprimir** `.env` ni claves; verificar por **forma** (longitud/prefijo).
Los tests **jamás** llaman a un LLM real, ni a Resend, ni a Telegram, ni al ROG:
todo con transporte parcheado, como ya hace `test_llm_fallback.py`.

---

## Fases

Rama **`fix/llm-safety-net`** desde el HEAD actual (`a6ed8b8`, 0.78.0 ya
desplegado). Un commit por fase. Un solo checkpoint de deploy al final.

> **Reordenado el 5-sep tras la consulta de arranque al advisor.** La alarma
> pasa a ser la Fase 1 y el tercer eslabón la Fase 2, por tres razones: la
> alarma **no depende de una decisión ni de una credencial del dueño** y es
> ejecutable ya; es la que **habría detectado la caída de hoy** (el tercer
> eslabón hace la avería más rara, la alarma la hace *sabida*, y saberla gana);
> y el acoplamiento va Fase-tercer-eslabón → Fase-alarma, no al revés, así que
> hacer la alarma primero solo cuesta retocar una vez sus tests cuando cambie
> la semántica de `check_fallback_provider`.

### Fase 1 [CRÍTICA] — La alarma que sí llega

**Objetivo verificable:** cuando la red de seguridad cae, sale aviso por
**email y Telegram**; un parpadeo breve **no** dispara aviso; y el estado
atascado queda reseteado.

**Archivos y cambios:**
- `app/services/ops_alert.py`: `send_operator_alert` intenta **los dos
  transportes** y devuelve `True` si **cualquiera** entrega. Reutilizar el
  primitivo de `app/services/telegram_notify.py` (ya envía a `TELEGRAM_CHAT_ID`,
  que es el chat del propio dueño, no un lead). `undeliverable_reason()` →
  "indeliverable" solo si **ninguno** de los dos puede entregar.
- `app/services/llm_monitor.py`: **anti-parpadeo (debounce)** — exigir **2
  lecturas iguales consecutivas** antes de cambiar de estado y avisar, para que
  un ROG que cae/vuelve no vacíe el presupuesto de 3/día (lección v0.54.3 #3).
  Test guardián: una sola lectura mala entre dos buenas **no** avisa.
- **Reset puntual del estado atascado** en el deploy: poner `alerted_state`
  acorde a la realidad para que el ciclo vuelva a poder avisar. Hacerlo con una
  sentencia de mantenimiento documentada, no con migración.

**Tests** (`test_ops_alert.py`, `test_llm_monitor.py`, ya existen y son ricos):
- Email cae, Telegram entrega → `send_operator_alert` = `True`, aviso contado
  una vez. (Mutación: que solo intente email → rojo cuando email falla.)
- Los dos caen → `False`, se registra, no se reintenta en bucle (respeta el tope).
- Debounce: lectura mala aislada → silencio; dos malas seguidas → un aviso.

**Cierre:** commit `feat(ops): alarma de operador por email y Telegram + anti-parpadeo`.
Sin bump aún (va con la Fase 2, que cierra la versión).

### Fase 2.0 — Confirmar el endpoint (solo si Opción B)

Antes de escribir nada, confirmar en la **documentación oficial** del proveedor
elegido el `base_url` Anthropic-compat exacto y el nombre del modelo (p. ej.
DeepSeek expone un endpoint `/anthropic` para usarse con el SDK de Anthropic).
Anotar en `PROJECT_STATUS.md` la URL y el modelo. **No inventar la URL.** Si el
proveedor no fuera Anthropic-compat, avisar y parar (haría falta un adaptador y
cambia el alcance).

### Fase 2 [CRÍTICA] — El tercer eslabón siempre disponible

**Objetivo verificable:** con Kimi y MiniMax forzados a fallar, `generate_reply`
devuelve una respuesta real del tercer proveedor cloud, sin tocar el ROG.

**Por qué es crítica:** toca `generate_reply`, por donde pasan TODAS las
respuestas a leads, el clasificador, el enriquecimiento y el escritor de
contenido (`grep generate_reply app`). Un fallo aquí deja mudo al producto.

**Archivos y cambios (Opción B):**
- `app/config.py` (+ `.env.example` + compose): añadir el proveedor —
  `LLM_LAST_RESORT_API_KEY`, `LLM_LAST_RESORT_BASE_URL`, `LLM_LAST_RESORT_MODEL`
  (nombres genéricos: mañana puede cambiar de vendor sin renombrar). Defaults
  vacíos → si no hay clave, el eslabón simplemente no está (como Ollama hoy).
- `app/services/llm.py`:
  - `_provider_configs()`: añadir la entrada del tercer proveedor cloud. Habla
    protocolo Anthropic → **reutiliza `_build_client` + `messages.create`**, la
    misma ruta que Kimi/MiniMax. **No** una ruta como `_ollama_generate`.
  - `generate_reply`: extender `order` para incluir el tercer cloud **antes** de
    Ollama (si sigue habilitado): `[PRIMARY, FALLBACK, last_resort_cloud, (ollama)]`.
    Saltar los no configurados, como ya hace.
  - Decisión sobre el ROG: dejar `OLLAMA_ENABLED` como está pero **ya no
    load-bearing** (queda de 4º, opcional). Documentarlo en el docstring.
- `app/services/llm.py::check_fallback_provider` / `FallbackStatus`: hoy solo
  mira Ollama. Ampliar el concepto de "red de seguridad sana" para que un tercer
  cloud configurado y respondiendo cuente como sano aunque el ROG esté caído
  (si no, `/health` seguiría en rojo con la red cloud viva). **Sin** gastar
  cuota: la salud del cloud se puede afirmar por "configurado" + el hecho de que
  el tráfico real lo ejercita; una sonda activa que llame al modelo gastaría lo
  que vigila (lección v0.54.3). Definir con cuidado y con test.

**Tests** (`test_llm_fallback.py`, patrón existente con transporte parcheado):
- Kimi y MiniMax fallan (timeout/429) → responde el tercer cloud. (Mutación:
  no añadir el tercero a `order` → rojo.)
- Los tres cloud fallan y Ollama está off → `LLMUnavailable`.
- Tercer cloud sin configurar → se salta sin romper.

**Si Opción C:** esta fase es solo `OLLAMA_ENABLED=false` + docstring/`/health`
diciendo honestamente "dos eslabones, sin red local" + test de que la cadena de
dos, al fallar ambos, cae limpio a la línea de espera sellada `provider=fallback`.

**Cierre:** commit `feat(llm): tercer proveedor cloud como red de seguridad` (o
`fix(llm): retirar el fallback del ROG` en C). Cierra con el bump **0.79.0**.

### Fase 3 — Verificación de extremo a extremo y deploy

**Antes de pedir deploy:**
- Suite + ruff + build en verde; mutaciones de F1 y F2 verificadas.
- **Una** llamada real al tercer cloud desde el VPS (clave del dueño ya en
  `.env`), 1 petición, como se hizo con YouTube: confirma credencial y modelo,
  no solo que los tests pasan (lección Kling).

**Deploy (con autorización en mensaje aparte):** backup del `.env`
(`.env.bak.YYYYMMDD_v0790`) → bundle → `scp` → `git fetch && merge --ff-only` →
`docker compose build backend` (frontend solo si cambió `version.ts`) → `up -d`
→ `/api/v1/health` = `0.79.0` y `llm_fallback` sano. **Sin migración** (no hay
esquema nuevo).

**Tras el deploy, lo que prueba lo que los tests no pueden:**
- Un **aviso de operador de prueba** a la dirección **del propio dueño**
  (`PLATFORM_ADMIN_EMAILS`, no un lead — autorizado por él): confirmar que llega
  por **los dos** canales.
- Confirmar en `monitor_state` que `alerted_state` ya sigue a `state`.

---

## Riesgos y supuestos

- **Contar las averías antes de arreglar** (lección v0.54.2): son dos; arreglar
  solo una parecería un arreglo. F1 y F2 son ambas obligatorias.
- **El vigilante no gasta el recurso que vigila** (v0.54.3): nada sondea a los
  proveedores de pago activamente; se observan del tráfico real.
- **El ROG queda fuera del camino crítico**, no "arreglado": aunque hoy volvió,
  se cuelga y se cae del tailnet por diseño.
- **Ambos canales de alarma podrían compartir un fallo de red del VPS**; si el
  VPS no tiene salida, enmudecen los dos. El vigía externo (`heartbeat.sh`) es
  la capa para "el backend entero muere" y queda fuera de este plan.
- **Prohibido** tocar servicios del ROG y otros stacks del VPS (Zorros,
  Black Volt).

---

## Verificación (resumen ejecutable)

1. `pytest` 1550+ en verde, sin saltados; `ruff app tests` limpio.
2. Mutaciones: quitar el 3er proveedor de `order` → rojo; que la alarma solo use
   email → rojo al caer email; quitar el debounce → rojo el test del parpadeo.
3. `docker build` OK.
4. Una llamada real al 3er cloud desde el VPS (1 petición).
5. Tras deploy: `/health` = 0.79.0 + red sana; aviso de prueba llega por email y
   Telegram; `alerted_state` sigue a `state`.

# PLAN (4) — Otoño 2026 en @denverhomestory: medir `/fall`, segundo pase diario, imágenes honestas y 36 piezas

> **Para el ejecutor (Opus 5):** este fichero **sustituye** a
> `~/Eko-AI-RealEstate/PLAN.md` en la rama `feat/otono-2026` y se commitea en
> la Fase 0. Es la convención real del repo —**un plan vivo por rama**, no
> acumulación—: en `98c9182` el `PLAN.md` son las 498 líneas del plan de la
> v0.92.0 y nada más. (Las 1.749 líneas de tres planes concatenados que tiene
> `main` son el residuo de un tronco que va por detrás.) El plan anterior no se
> pierde: vive en su rama y en el historial. Lo que no esté escrito aquí, no existe. Máximo 3 intentos de
> corrección por fase; ante un bloqueo o en una fase **[CRÍTICA]**, consulta al
> advisor antes de improvisar. Se escribió el 8-sep-2026 desde una sesión que
> **no** ejecuta: todo número de este documento se midió ese día y **se vuelve
> a medir en la Fase 0**. Las citas `path:line` son de `main`@`ab6b442` (= lo
> que corre el VPS más commits de estado); si una línea no coincide, busca la
> función por nombre, no la línea.

---

## 1. Contexto — por qué existe este plan

**La premisa del dueño, en sus palabras:** «todo lo que hagamos con DHS en
redes sociales es para traer tráfico a la página de DHS y a su vez la gente se
interese por contactarnos para que seamos sus realtors».

### 1.1 Lo medido el 8-sep-2026

Fuentes: vidIQ público (la cuenta **no** está conectada a vidIQ: no hay reach,
saves, shares ni watch-time), `landing_sessions` y `content_pieces` en
producción, el log del obrero en el ROG, y lectura del código.

| Hecho | Dato | Cómo se midió |
|---|---|---|
| El reel de otoño `Dc_eGJtxy8E` (pieza 18, 12,6 s) es el único que funcionó | **425** reproducciones, 11 likes, 4 comentarios. Mediana de los otros 9 reels: **6**. Es el 60 % del alcance total de la cuenta (713) | `vidiq_ig_profile_reels` |
| No convirtió | **1** sesión en `/fall` desde Instagram (25 % de scroll); **8** sesiones en `/fall` en total; **0 leads en todo el sitio** (67 sesiones, 5–8 sep) | `SELECT source, landing_path, count(*) FROM landing_sessions WHERE first_seen_at > '2026-09-05' GROUP BY 1,2` |
| `/fall` **sí tiene formulario** — pero no se mide | `app/fall/page.tsx:407` renderiza `<ConsultForm variant="fall" />`. La sección que lo envuelve (`:385`) **no tiene `id="consult"`** → `section_view` nunca se emite; no hay ningún `href="#consult"` → `cta_click` **no puede dispararse** (`components/landing/LandingTracker.tsx:143` exige el literal); no hay enlace a `/calculator` | lectura del código (una sesión anterior dio el formulario por inexistente: **falso**) |
| `/calculator` tampoco mide el CTA | Tiene `id="consult"` (`app/calculator/page.tsx:630`) pero **ningún** `href="#consult"` | lectura del código |
| El CTA doble se anuló solo | El vídeo pedía «Comment FALL for the guide» y la caption del mismo post daba el enlace. 4 comentarios, **ninguno escribió FALL** | dueño |
| El metraje del ganador es IA y se subió montado | Kling/fal.ai (dueño). `content_pieces.id=18`: `kind=generated`, `scenes IS NULL`, `media_path=e25c5fe6….mp4`. El obrero **no lo tocó**: `enqueue_generated` exige `scenes IS NOT NULL` (`content_render.py:460`) | psql |
| Los reels educativos llevan fotos de stock que contradicen el guion | `Dc0D8ysE650` (earnest money) enseña `HOME INSURANCE POLICY`, sobres `MICROPRENEUR`, un calendario de **oct-2021** con `Check Breasts` y un periódico `Jobs wanted`. `Dc7QQPeiZ25`, un calendario de **2019**. `Dc0EHq9lT5x` y `Dc0Qlx1CLCr`, casas claramente **no estadounidenses** con cartel «For Sale» | `vidiq_watch_shortform_content` (vídeo visto entero) |
| **De dónde salen esas fotos: de Pexels, porque fal.ai está sin saldo** | `~/eko-render/worker.log` (ROG): **8 imágenes fal el 4-sep, 8 el 5-sep**, y desde el **6-sep** `fal.ai answered 403: the account has no balance. Today's pictures come from stock instead; the videos still go out`. Proveedores en el log: **700 pexels / 70 fal**. Kling (imagen) **nunca** corre: `KLING_ACCESS_KEY` y `KLING_SECRET_KEY` están **vacías** en `~/.eko-render.env` del ROG | ssh `pcrug`, longitudes de variable (nunca valores) |
| El obrero no es vídeo, son fotos con `zoompan` | Kling `/v1/images/generations` `kling-v1-5` y Pexels `/v1/search` (fotos); movimiento en `worker/produce.py:211-215`. La foto se elige así: primeras **4 palabras** del `visual_prompt` (`pictures.py:168`), 8 candidatas, **la primera cuyo alt no mencione personas** (`:220-223`). **No existe ninguna comprobación de que la foto corresponda a la escena** | informe del obrero |
| El código del obrero en el ROG ≠ el del repo | El ROG corre la rama **`fix/imagenes-fal`** (`643ebff`, 5 ficheros, **no fusionada** en `2588c2c`) desde un tar en `~/eko-render/app`. `worker/install-on-rog.sh` hace `cat > ~/.eko-render.env` (**sobrescribe** las claves cada vez que se ejecuta) | `git merge-base --is-ancestor` + lectura del instalador |
| Un hueco por canal y día | `_slot_for` devuelve una sola `time` (`buffer_publisher.py:475-484`); `_day_is_taken` marca el día entero (`:521-554`); `next_free_slot` salta al día siguiente (`:557-586`). Reordenar la cola **no mueve fechas** | lectura del código + memoria |
| Techo del formato en el nicho | `@coloradomamalife` **168,8 K** con «7 fall-color day trips within 90 minutes of Denver» (11 K seguidores); `@yourdenverrealtorco` **676 K con 2,9 K seguidores**. Gancho común: **un número + una restricción**; los realtors que rompen son **una persona en un sitio concreto, diciendo su nombre** | vidIQ outliers ago–sep 2026 |

**Producción hoy:** v**0.91.0**, commit `2588c2c`, rama `feat/maquina-de-video-dhs`
en el VPS — **superada el mismo 8-sep**: la sesión del calculador desplegó la
**0.92.0**, y lo verificado desde esta sesión es: VPS en **`98c9182`**, árbol
limpio, `inmo-demo…/fall` y `/calculator` → **308** al dominio de marca, marca
`/fall` → 200 sin salto. **La base de la rama es `98c9182`** (no `8a2d188`,
que fue un commit intermedio). La Fase 0 lo vuelve a medir de todos modos. `main` (`ab6b442`) = `2588c2c` + **26 líneas de `PROJECT_STATUS.md`**
y nada más (`git diff --stat 2588c2c main`, medido). La rama de este plan nace
de **`origin/main`**: la regla «nunca desde `main`»
([[feedback_main_por_detras_de_produccion]]) aplica cuando `main` lleva
*código* que producción no tiene; aquí lleva solo estado, y ramificar desde el
commit del VPS fabricaría un conflicto en el fichero más conflictivo del repo
en el primer commit (el propio plan). La Fase 0 vuelve a medir ese diff.

### 1.2 Sobre el gasto en fal.ai (pregunta del dueño del 8-sep)

Lo que se puede verificar desde aquí: el obrero pidió **16 imágenes** en total
(`flux/schnell`, `portrait_16_9` = 0,59 MP facturado como 1 MP a $0,003) ≈
**$0,05**, con caché por prompt (17 ficheros, 8,3 MB en `~/eko-render/cache`)
y tope `RENDER_KLING_IMAGES_PER_DAY=8`. La CLI local `~/fal-tools` tiene 14
imágenes en disco y **ningún vídeo**. En el ROG no hay otro consumidor de fal
(BitTrader usa Kling directo). **El obrero no es lo que gastó el saldo.** Lo
que lo agotó entre el 4-sep (recarga) y el 6-sep (403) no está en ningún log
que esta sesión pueda leer: solo lo dice el panel de fal.ai (`fal.ai/dashboard/usage`),
que el dueño tiene que mirar. **Desglose real (CSV de fal, septiembre,
entregado por el dueño el 8-sep): $12,48 en total.** Imágenes: **$0,21** (27 MP
+ 1 imagen, del 4 al 6-sep — el obrero y la CLI juntos). Vídeo: **$12,27, todo
el 6-sep, 76,3 segundos repartidos en SEIS modelos text-to-video distintos**:

| Modelo (`app_id`) | Segundos | $/s | Importe |
|---|---|---|---|
| `kling-video/v3/pro/text-to-video` | 36 | 0,14 | **5,04** |
| `veo3.1` | 8 | **0,40** | 3,20 |
| `veo3.1/fast` | 13,3 | 0,15 | 2,00 |
| `veo3/fast` | 8 | 0,15 | 1,20 |
| `minimax/hailuo-02/pro/text-to-video` | 6 | 0,08 | 0,48 |
| `kling-video/v2.5-turbo/pro/text-to-video` | 5 | **0,07** | 0,35 |

O sea: **el saldo se fue en una comparativa de modelos el 6-sep**, no en el
pipeline. Se generaron 76 s para un reel de 12,6 s (6×), y el modelo más caro
(`veo3.1`, $0,40/s) cuesta **5,7 veces** el más barato usado (`kling v2.5-turbo`,
$0,07/s). Y la secuencia importa: los $12,27 de vídeo se gastaron **el mismo
día** en que el obrero recibió el primer 403 (6-sep 21:56) — la comparativa
vació la cuenta y las educativas pasaron a Pexels esa misma noche. **Una
causa, dos síntomas.**

Consecuencia para la Fase 4c, con la aritmética del propio CSV (52 clips de
5 s): a $0,07/s → **$18** (1 intento) / **$36** (tope de 2); a $0,14/s → $36 /
$73; a $0,40/s → $104 / $208. Por eso: **modelo elegido UNA vez (D-2) y precio
confirmado en la doc el día de generar; una pieza de prueba antes que las
demás; tope de 2 intentos por clip** — si el segundo no sirve, cambia el
prompt, no se repite a ciegas. Nada de comparativas de seis modelos con el
saldo de producción.

Lo que sí es ineficiente y este plan corrige: **un 403 degrada a Pexels en
silencio y sigue publicando** — el mismo patrón de
[[feedback_kling_sin_saldo_silencioso]], ahora con fal. El resultado no es
«sin imagen», es **la imagen equivocada bajo la firma de Engel & Völkers**.

### 1.3 Decisiones del dueño, ya tomadas (8-sep-2026) — no reabrir

1. **Cadencia semanal en Instagram: 7 educativas (las que ya salen) + 3 de
   otoño + 3 de calculadora = 13 de 14 huecos.** Las educativas se
   **mantienen**; lo nuevo se **añade**.
2. **Segundo pase diario en los TRES canales.** Motivo: `publish_piece` recorre
   todos los `configured_channels()`; un segundo slot solo-IG obligaría a
   insertar a mano las filas de TikTok/YouTube de cada pieza.
3. **Medir `/fall`**: ancla `#consult`, enlace al formulario arriba, enlace a
   `/calculator` en medio. (El formulario ya existe: no se añade otro.)
4. **Las piezas de otoño no nombran sitios en pantalla** mientras el metraje
   sea generado (regla que `frontend/lib/fallGuide.ts` ya defiende para las
   fotos). Solo los 5 sitios con foto libre de ese sitio
   (`frontend/public/landing/fall/LICENCIA.txt`) pueden nombrarlo.
5. **Borrar los 4 reels con B-roll incoherente** y que no vuelva a pasar.
6. **Cada pieza de calculadora es un escenario con un número real de la propia
   calculadora**, nunca «usa nuestra calculadora» repetido.
7. **Un solo CTA por post**, el mismo en pantalla y en caption. Nunca
   «Comment X» y enlace en el mismo post.
8. **fal.ai es el ÚNICO generador de DHS, para vídeo y para imagen. Kling
   queda FUERA del obrero** (decidido el 8-sep tras ver el CSV): el plan de
   Kling es mensual y **comparte contador con The Power Unleashed** — meter
   las 280 imágenes/mes de DHS en él agota a los dos proyectos a la vez. Un
   solo saldo que vigilar; si fal está a cero, el obrero **para y avisa**
   (Fase 3b). Las claves de Kling **no se ponen** en `~/.eko-render.env`.
9. Orden: (1) medir `/fall` + rutas cortas → (2) segundo slot → (3) imágenes
   honestas + borrar reels → (4) piezas. **(1) lo encarga el dueño a la sesión
   del calculador**; (2), (3) y (4) los hace el ejecutor de este plan.
10. Versión **0.93.0** reservada (concedida por «DenverHomeStory Calculator» el
    8-sep; ella tiene la 0.92.0).

### 1.4 Fuera de alcance (explícito)

- Rodar metraje real con Natalia y Robbie. Se **recomienda** — es lo que rompe
  en el nicho — pero no es decisión tomada. Si se aprueba, sustituye al
  metraje generado pieza a pieza sin cambiar nada de este plan.
- Automatización de DM («Comment X» → mensaje). No existe y no se construye.
- Conectar @denverhomestory a vidIQ (lo hace el dueño; gratis).
- Una puerta de **visión** (modelo que mire la foto) en el obrero: exige una
  credencial nueva en el ROG y una dependencia nueva. Backlog B-1; la Fase 3
  resuelve el problema por otro camino.
- Cambiar `CONTENT_PUBLISH_MAX_PER_DAY` (riesgo R-4).
- Cualquier despliegue sin autorización del dueño **en mensaje aparte**.

### 1.5 Coordinación obligatoria con la otra sesión

Sesión viva **«DenverHomeStory Calculator»**, worktree `~/eko-calculator`
(ramas `feat/f0-plan`, `feat/f1-host-panel`; base `eko_realestate_test_calculator`;
puertos 8021/3010; versión 0.92.0). En vuelo: `frontend/middleware.ts`,
`frontend/lib/hosts.ts`, `components/landing/ConsultForm.tsx`,
`app/contact/page.tsx`, `lib/i18n.tsx`, `lib/leadName.ts`,
`lib/__tests__/hostRouting.test.ts`. Su 0.92.0: el host del panel responde
**308** a `/fall`, `/contact`, `/calculator` hacia `www.denverhomestory.com`;
los formularios públicos exigen **nombre y apellido**.

- `SendMessage` a esa sesión en la Fase 0 y **antes de cada despliegue**.
- **No tocar sus ficheros en vuelo.** La Fase 1 toca `app/fall/page.tsx`,
  `lib/__tests__/fallGuide.test.ts`, `next.config.js`,
  `lib/__tests__/bioLinks.test.ts` — ninguno está en su lista, pero es
  frontend y se despliega con el suyo: **o la hace ella con encargo del dueño,
  o la hace este plan después de su 0.92.0.** Nunca en paralelo.
- Base de tests **propia**: `eko_realestate_test_otono`
  ([[feedback_dos_sesiones_una_base_de_tests]]).
- **Nunca `git checkout -- .`, `git stash -u` ni `git reset --hard`** sobre un
  árbol con cambios ajenos ([[feedback_checkout_en_bloque_borra_produccion]]).

---

## 2. Comandos del proyecto (verificados el 8-sep-2026)

Desde `~/Eko-AI-RealEstate` (o un worktree: `git worktree add ~/eko-otono -b
feat/otono-2026 origin/main`, tras la comprobación de la Fase 0). **Nunca exportes `APP_DB_PASSWORD`** (el rol
`eko_app` es del clúster; `alembic` le cambiaría la contraseña a todas las
bases). **Nunca `docker compose up/down/restart` en local** (los `container_name`
son fijos y compartidos).

```bash
# ── base de tests propia (una vez) ───────────────────────────────────────
docker exec eko-realestate-db psql -U eko -d postgres \
  -c "DROP DATABASE IF EXISTS eko_realestate_test_otono WITH (FORCE)" \
  -c "CREATE DATABASE eko_realestate_test_otono OWNER eko"

# ── entorno backend (cada shell nuevo) ───────────────────────────────────
cd ~/Eko-AI-RealEstate/backend
PW=$(docker exec eko-realestate-db printenv POSTGRES_PASSWORD)
export DATABASE_URL="postgresql+asyncpg://eko:${PW}@localhost:5434/eko_realestate_test_otono"
export DATABASE_URL_APP="postgresql+asyncpg://eko_app:eko_app_local_pass@localhost:5434/eko_realestate_test_otono"
export WHATSAPP_ENABLED=true PYTHONDONTWRITEBYTECODE=1
./.venv/bin/python -m alembic upgrade head        # OBLIGATORIO: la suite no crea el esquema
./.venv/bin/python -m alembic heads               # UNA cabeza
./.venv/bin/python -m pytest -q -p no:cacheprovider
./.venv/bin/python -m ruff check app tests --output-format=concise
./.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_buffer_publisher.py   # solo el publicador

# ── obrero (tests puros, sin base) ───────────────────────────────────────
cd ~/Eko-AI-RealEstate && ./backend/.venv/bin/python -m pytest -q -p no:cacheprovider worker/tests

# ── frontend (SIEMPRE desde frontend/: un `next build` desde backend/ dio rc 254 y se leyó como 0)
cd ~/Eko-AI-RealEstate/frontend
npx tsc --noEmit && npx vitest run && npx next lint && npx next build
for p in calculator fall contact index; do f=".next/server/app/$p.html"; \
  printf "%-10s <main>=%s Checking=%s\n" "$p" "$(grep -c '<main' "$f")" "$(grep -c 'Checking session' "$f")"; done

# ── producción y ROG (solo lectura, siempre permitido) ───────────────────
curl -s -A "Mozilla/5.0" https://inmo-demo.ekoaiautomation.com/api/v1/health
ssh ender-vps 'cd ~/Eko-AI-RealEstate && git rev-parse --short HEAD && git branch --show-current'
ssh ender-vps "docker exec eko-realestate-db psql -U eko -d eko_realestate -A -F, -c \"<SELECT …>\""
ssh pcrug 'tail -50 ~/eko-render/worker.log; systemctl --user is-active eko-render-worker'
ssh pcrug 'for k in FAL_KEY KLING_ACCESS_KEY KLING_SECRET_KEY PEXELS_API_KEY; do v=$(grep -E "^$k=" ~/.eko-render.env | cut -d= -f2-); echo "$k len=${#v}"; done'   # longitudes, NUNCA valores
```

Baseline conocido (7-sep): backend **1779 passed, 0 skipped** (~6:40) sobre
base migrada a `055_calculator_snapshot`; frontend vitest **328/328**. Sin
`DATABASE_URL` los tests del publicador **se saltan en silencio**
(`test_buffer_publisher.py:60-65`): un «verde» con `skipped > 0` no es verde.

Notas: `pytest-cov` y `ruff` están **en el venv**, no en `requirements.txt`.
No encadenes `| tail`/`| head` a un comando cuyo `rc` necesites. El hook `rtk`
resume `grep`/`cat` (muestra `+N` líneas): para leer entero usa `sed -n 'a,bp'`
o `python3`. El clasificador de permisos bloquea a veces `ssh … psql` con
comillas anidadas: la forma que **sí** pasa es la de arriba (`-A -F,` y la
consulta entre `\"…\"`). `git merge --ff-only` en el VPS también se ha
bloqueado repetidas veces: el dueño lo corre a mano.

**Definición de «terminado» de cada fase = sus comandos en verde + commit.**
Commits convencionales con ámbito, en español, con la atribución vigente. **No
tocar `CHANGELOG.md`, `PROJECT_STATUS.md` ni `frontend/lib/version.ts` hasta
la Fase 5** (los tres ficheros de conflicto con la otra rama).

---

## 3. Fases

Orden real: la Fase 2 (backend puro) y la 4a (backend puro) no dependen de
nadie y arrancan ya; la 3 depende del dueño (saldo y claves); la 1 depende de
la otra sesión; la 4b–4d dependen de la 3; al final versión y despliegue.

### Fase 0 — Aislamiento, medición y aviso

**Objetivo:** la base de la rama es lo que corre en producción, la base de
tests es propia, y los números de §1.1 se vuelven a medir.

- `curl … /health` → `version`; `ssh ender-vps … git rev-parse` → commit. Lo
  esperado es **`0.92.0` / `98c9182`**. Si no coincide, **para y averigua qué
  corre**; ramifica desde ese commit.
- ✅ **Hecho el 8-sep.** `git fetch origin` + `git diff --stat 98c9182
  origin/main`: **19 ficheros, 1.740 inserciones**, entre ellos
  `frontend/middleware.ts`, `lib/leadName.ts`, `lib/i18n.tsx` y `lib/version.ts`
  — o sea, **`origin/main` no tiene el código de la 0.92.0 que corre en
  producción**. `98c9182..origin/main` está **vacío** y al revés hay 7 commits:
  `main` está estrictamente detrás. **Base = `98c9182`**, rama
  `feat/otono-2026` creada ahí.
- ✅ **Hecho el 8-sep.** El ROG corre exactamente `fix/imagenes-fal`:
  `md5` **`6359650d412e93742a53da98697303f9`** idéntico en
  `~/eko-render/app/worker/pictures.py` y en
  `git show fix/imagenes-fal:worker/pictures.py`; servicio `active`.
- ✅ **Saldo de fal comprobado con una llamada real** (no de palabra): una
  imagen `flux/schnell` devolvió un JPEG 1024×576 de 494.306 bytes con `rc=0`.
  El 403 de «no balance» ya no aplica.
- Añadir este bloque al final de `PLAN.md`; commit `docs(plan): otoño 2026 —
  medir /fall, segundo slot, imágenes honestas y las piezas`.
- Crear `eko_realestate_test_otono`; correr §2 completo. Anotar aquí los
  números reales (backend `N passed / 0 skipped`, obrero `N`, frontend `N/N`).
  Si difieren del baseline, **anótalo, no lo arregles**.
- ✅ **Vuelto a medir el 8-sep, 20:0x.** `Dc_eGJtxy8E`: **485** reproducciones
  (era 425), **13** likes, **4** comentarios — sigue siendo el **63 %** del
  alcance total (773) y ~**81×** la mediana de los otros nueve, que sigue en
  **6**. La pieza del 8-sep (`DdAZwW2jtLz`, educativa) lleva **6** en su primer
  día completo. `landing_sessions` desde el 5-sep: **1** sesión de Instagram a
  `/fall`, **0 CTA en todo el sitio, 0 leads** (69 sesiones). Obrero: **16 fal
  / 140 pexels** y **2** eventos `no balance`. Los números del §1.1 se
  confirman; ninguno mejora solo.
- `SendMessage` a «DenverHomeStory Calculator»: rama, base, 0.93.0, ficheros
  que toca este plan (lista de §1.5 + `backend/app/config.py`,
  `backend/app/services/buffer_publisher.py`, `backend/tests/test_buffer_publisher.py`,
  `backend/app/api/v1/content.py`, `.env.example`, `docker-compose.yml`,
  `worker/*`). Preguntar su fecha de despliegue de la 0.92.0 y si el dueño le
  encargó la Fase 1.

**Terminado:** rama desde el commit del VPS, suite en verde con `0 skipped`,
plan commiteado, mensaje enviado, md5 del ROG anotado.

---

### Fase 1 — Medir `/fall` y las rutas cortas *(frontend; **la hace el ejecutor de este plan, después de que la 0.92.0 esté en producción** — D-6 ✅; rebasar sobre `98c9182` antes de tocar nada)*

**Objetivo:** el tracker ve el formulario de `/fall`, un clic al CTA cuenta, la
guía enlaza a la calculadora, y cada pieza de Instagram aterriza con su
`utm_content`.

**Archivos:**

1. `frontend/app/fall/page.tsx:385` — la `<section className="bg-ln-dark …">`
   que envuelve el `ConsultForm` gana **`id="consult"`** y `scroll-mt-10`
   (como `app/calculator/page.tsx:630`). El default de `LandingTracker`
   (`SECTIONS`, `LandingTracker.tsx:43`) ya incluye `"consult"`: **no pasar
   `sections=`** — los `band-N` no están en `LANDING_SECTIONS`
   (`backend/app/models/landing.py:64`) y el servidor los descartaría en
   silencio, y el test que lo vigila (`lib/__tests__/track.test.ts:440-497`)
   **no ve** ids con guion.
2. `frontend/app/fall/page.tsx:275` (tras la intro) — un enlace
   **`<a href="#consult" data-track="fall-intro">`** con copy en inglés
   (la página es server component y no puede llamar a `useI18n()`):
   *«Thinking about selling before spring? Talk to us →»*. El literal
   `href="#consult"` es lo único que `LandingTracker.tsx:143` cuenta.
3. `frontend/app/fall/page.tsx` entre `:326` (fin de las franjas) y `:328`
   («Three things worth knowing») — un bloque corto con enlace a
   **`/calculator`**: *«Wondering what your rent would buy up here? Run the
   numbers →»*. Este clic **no genera evento** (el tracker solo cuenta `tel:` y
   `#consult`); la atribución sobrevive por `sessionStorage` (`dhs.attr`,
   `lib/track.ts:156-172`). Medirlo exigiría un `EventName` nuevo en
   `track.ts:32-42` + `IMMEDIATE` + el frozenset del backend — **backlog B-2**,
   no aquí.
4. `frontend/app/calculator/page.tsx` — el mismo `<a href="#consult">` cerca
   del resultado (hoy tampoco puede contar clics). **Solo si la otra sesión no
   tiene ese fichero en vuelo** en ese momento; si lo tiene, backlog B-3.
5. `frontend/next.config.js:19-33` — ayudante hermano de `bio()`:
   ```js
   const fall = (n) => ({
     source: `/fall/${n}`,
     destination: `/fall?utm_source=instagram&utm_medium=social&utm_campaign=fall2026&utm_content=band${n}`,
     permanent: false,   // 302 a propósito, como bio(): ver el comentario de :16-18
   });
   // …return [ ...bio, fall(1), fall(2), fall(3), fall(4) ];
   ```
   `bio()` no sirve tal cual: hardcodea `/`, `utm_medium=bio` y
   `utm_campaign=profile`. `/fall/1` ya cuenta como pública
   (`lib/hosts.ts:92-95`, prefijo). Va como **redirect, no como segmento
   `/fall/[n]`**: un segmento real crearía cuatro URLs indexables con el
   contenido de `/fall`.
   **Destino relativo, a propósito, y por qué es seguro aquí y no en `bio()`**
   (aviso de la sesión del calculador, 8-sep): `redirects()` corre **antes**
   que el middleware. En el host de marca es un salto. En el host del panel
   son dos: `inmo-demo…/fall/1` → 302 `/fall?utm_…` → 308 al dominio de marca
   **conservando la query** (su regla de la 0.92.0) — la atribución
   sobrevive. Las captions llevan siempre `denverhomestory.com/fall/N`, así
   que el caso normal es un salto. **El defecto que NO hay que heredar:** los
   seis `bio()` apuntan a `/?utm_…` y la regla del panel `/` → `/leads`
   (`middleware.ts:64-66`) **descarta la query**; a `/fall` no le pasa porque
   es ruta pública y no hay regla que la reescriba. Si algún día el destino
   deja de ser una ruta pública, tiene que ser absoluto al dominio de marca.

**Tests:**

- 🔴 `frontend/lib/__tests__/fallGuide.test.ts:149-163` **se pone rojo** con
  el `href="#consult"`: recorre todos los `href="#…"` de la página y exige
  que sean ids de franja. Extender su conjunto permitido con `"consult"`
  (y solo ese), con un comentario de por qué. `:175-187` sigue exigiendo que la
  página no diga `Engel` y sí `LANDING.brokerage` — no tocar el pie.
- `frontend/lib/__tests__/bioLinks.test.ts:45-52` recorre **todas** las reglas y
  exige `permanent === false`: las cuatro nuevas lo cumplen. Añadir un caso:
  para `n` en 1..4, existe la regla `/fall/${n}` y su `destination` contiene
  `utm_content=band${n}` y empieza por `/fall?`.
- `lib/__tests__/track.test.ts:336-344` cuenta anclas y `data-track` **solo en
  `Landing.tsx`**: no afecta.
- `publicMetadata.test.ts:64-131`: no cambia (metadata intacta).

**Mutaciones:** quitar el `id="consult"` → ningún test rojo hoy (**hallazgo**:
añade un caso en `fallGuide.test.ts` que exija `id="consult"` en la página);
`permanent: true` en `fall(1)` → rojo en `bioLinks`.

**Terminado:** vitest verde, `next build` verde, prerender `fall` `<main>=1`
`Checking=0`, **`curl -sI https://www.denverhomestory.com/fall/1` → 302 con
`location: /fall?…utm_content=band1`** tras el despliegue (`redirects()` se
hornea en el build: **exige reconstruir el frontend en el VPS**, no basta
reiniciar). Commit `feat(fall): el formulario se mide, la guía enlaza a la
calculadora, y /fall/1..4 atribuyen por pieza`.

---

### Fase 2 — Segundo pase diario en los tres canales **[CRÍTICA]**

**Objetivo:** cada canal puede publicar dos veces por día local, en dos horas
fijas, sin que dos piezas compartan nunca la misma hora; una pieza sigue
ocupando un hueco por canal.

**Diseño (decidido; las cuatro preguntas que el código obliga a contestar):**

| Pregunta | Decisión | Por qué |
|---|---|---|
| ¿Cómo se declaran dos horas? | **Lista separada por comas en la MISMA variable**: `CONTENT_SLOT_INSTAGRAM="11:30,18:30"`. Un solo valor sigue valiendo | No añade variables (`.env.example` y `docker-compose.yml` tienen tests que exigen declararlas); compatible hacia atrás |
| ¿`_day_is_taken` pasa a contar? | **No: pasa a decir qué huecos quedan libres.** `_free_slots(db, platform, day, zone) -> list[time]`: un hueco está ocupado si existe una fila `_HOLDS_A_SLOT` con `scheduled_at` **igual** al instante UTC de ese hueco | Contar e indexar falla cuando el ocupado no es el primero (18:30 ocupado a las 10:00 → el índice devolvería 18:30 otra vez) |
| ¿Qué gasta una fila con `published_at` y sin `scheduled_at` (un `shareNow`)? | **Un hueco, el más temprano libre de ese día**, no el día entero | Con dos huecos, un post manual del pipeline no debe cerrar el día; en modo cola esas filas solo existen como historia (3-sep) |
| ¿El margen de 20 min salta al día siguiente? | **Salta al siguiente hueco libre**, hoy si lo hay | Con el 11:30 pasado, el 18:30 de hoy sigue siendo útil |

`CONTENT_PUBLISH_MAX_PER_DAY` (4 piezas **reclamadas** por día UTC,
`publish_approved:1049,1072`) **no se toca** (riesgo R-4). `uq_content_publication`
(`piece_id, platform`, `models/content.py:189`) garantiza que el segundo hueco es
siempre **otra** pieza: sin migración.

**Archivos y cambios:**

1. `backend/app/config.py:567-569` — los tres `CONTENT_SLOT_*` conservan tipo
   `str`; el validador `_valid_clock_time` (`:579-600`) pasa a: `split(",")`,
   cada trozo `HH:MM` con cero a la izquierda, **estrictamente creciente**, sin
   repetidos, ≥ 1; el mensaje de error nombra el trozo malo. Comentario
   `:550-566`: «un hueco al día» → «uno o más huecos al día».
2. `backend/app/services/buffer_publisher.py`:
   - `_slot_for(platform) -> time` (`:475-484`) → **`_slots_for(platform) ->
     list[time]`**, ordenada.
   - `_day_is_taken` (`:521-554`) → **`_free_slots(db, platform, day, zone) ->
     list[time]`**: una consulta con `scheduled_at` (+ `status IN _HOLDS_A_SLOT`)
     y `published_at` de las filas del día local (`_local_day_bounds`, `:497-509`,
     se reutiliza); conjunto de instantes ocupados; `free = [s for s in slots if
     instante(s) not in ocupados]`; resta del principio tantos como filas «sin
     hueco» (`published_at` en el día y `scheduled_at` NULL o fuera del día).
   - `next_free_slot` (`:557-586`): 370 días × huecos libres, con
     `CONTENT_SCHEDULE_LEAD_MINUTES` aplicado **por hueco**. Devuelve UTC.
   - Cabecera `:463-472` («One slot a day per channel»): reescribir con la
     regla nueva; la cita del dueño «nunca dos a la vez» sigue siendo cierta.
3. `.env.example:198-205` y `docker-compose.yml:172-176` — defaults nuevos y
   comentario. **Defaults (D-1 ✅):** `CONTENT_SLOT_TIKTOK="08:30,17:30"`,
   `CONTENT_SLOT_INSTAGRAM="11:30,18:30"`, `CONTENT_SLOT_YOUTUBE="12:30,20:30"`.
   `test_compose_env.py` y `test_config_example.py` exigen que los tres sitios
   coincidan con los defaults de `Settings`.
   ⚠️ **En compose los valores van entre comillas**: `"${CONTENT_SLOT_YOUTUBE:-12:30,20:30}"`.
   Y un aviso de método: un `grep CONTENT_SLOT docker-compose.yml` bajo el hook
   `rtk` **devolvió solo `.env.example`** y me hizo creer que compose no las
   declaraba; quien las encontró fue `test_compose_env.py`. Para contar o
   localizar en este repo, `python3`/`sed`, nunca `grep` a secas
   ([[feedback_mi_contador_no_casaba]]).
4. `frontend/components/content/ContentQueue.tsx:366-372` **no cambia**.

**Tests (`backend/tests/test_buffer_publisher.py`; la fixture `queue_on`
`:790-797` pasa a listas de dos):**

- Reescribir los tres que codifican la regla vieja:
  `test_one_slot_a_day_per_channel` (`:827`, «días distintos» → **instantes
  distintos, mismo día permitido**), `test_a_post_already_out_today_spends_todays_slot`
  (`:857` → la pieza nueva cae en el **segundo** hueco de hoy),
  `test_a_denver_evening_is_the_next_utc_day` (`:941` → con el 20:30 ocupado y
  el 12:30 de mañana libre, mañana 12:30; con los dos ocupados, pasado mañana
  12:30).
- Nuevos: (a) tres piezas → dos hoy (11:30, 18:30) y una mañana 11:30; (b) a las
  11:20 con margen 20 → **18:30 de hoy**; (c) una fila `published_at` hoy sin
  `scheduled_at` deja **un** hueco libre; (d) `"18:30,11:30"` y `"11:30,11:30"`
  **fallan al construir `Settings`**; `"18:30"` a secas vale; (e) un
  `scheduled_at` histórico que no coincide con ningún hueco no ocupa ninguno.
- Sin tocar y en verde: `:908` (margen), `:992` (orden), `:1031`
  (`customScheduled`+`dueAt`), `:1096` (nunca dos veces), `:1602` (tope).

**Mutaciones** (copiar, mutar, ver el rojo, restaurar, `md5`; purgar
`__pycache__` entre una y otra — [[feedback_el_pyc_envenenado_por_la_mutacion]]):
(1) `_free_slots` devuelve siempre `slots` entera → rojo en «nunca a la misma
hora»; (2) el margen salta al día siguiente → rojo en (b); (3) el validador
acepta desordenado → rojo en (d); (4) se omite la resta de filas sin hueco →
rojo en (c). Una mutación que no pone nada en rojo = falta un test.

**Terminado:** publicador en verde con `0 skipped`, suite completa en verde,
ruff limpio, 4 mutaciones en rojo con `md5` restaurado, commit
`feat(publisher): dos huecos por canal y día local`.

✅ **Hecho el 8-sep.** `tests/test_buffer_publisher.py` **57 passed**;
`test_config_example.py` + `test_compose_env.py` + publicador = **62 passed**;
ruff **All checks passed**. Las cuatro mutaciones, **las cuatro en rojo** y con
`md5` restaurado en las dos: (1) `_free_slots` devuelve todo → 1 failed;
(2) el margen salta el día → 1 failed; (3) el validador acepta desordenado →
1 failed; (4) sin restar las filas sin hueco → 1 failed.
Suite completa: **1782 passed, 0 skipped, 5:00** — el baseline era **1779**, y
los tres de más son exactamente los tres tests nuevos.
Un fallo propio, encontrado y arreglado: reescribí el *docstring* de
`test_a_denver_evening_is_the_next_utc_day` para decir «19:00» y dejé el cuerpo
en mediodía — el test cayó en la primera corrida. Ahora siembra **dos** filas
(esta tarde 20:30 y mañana 12:30) para que la respuesta siga siendo un instante
del **día UTC siguiente**, que es lo que el test se llama.

---

### Fase 3 — Imágenes honestas: el obrero no publica la foto equivocada **[CRÍTICA]**

**Objetivo:** las educativas llevan imágenes generadas del guion (Kling o
fal), y cuando no hay saldo el obrero **para y avisa** en vez de meter stock.

**Diagnóstico que fija el diseño (§1.1):** las fotos malas son **Pexels**, y
Pexels entra porque fal está a 403 y Kling no tiene claves. Una puerta que
«mire» la foto de Pexels es una dependencia nueva en el ROG para arreglar un
proveedor que no debería estar eligiendo la imagen de una pieza educativa. La
solución barata y correcta es **quitar a Pexels de la ruta generada**.

#### 3a — Fusionar lo que ya corre y devolverle las claves *(dueño + ejecutor)*

- `git merge fix/imagenes-fal` en `feat/otono-2026` (5 ficheros:
  `worker/pictures.py`, `worker/produce.py`, `worker/tests/test_lane_b.py`,
  `worker/install-on-rog.sh`, +1). Es **el código que el ROG ya ejecuta**;
  fusionarlo evita que un despliegue futuro del obrero lo **revierta**.
  `worker/tests` en verde.
- **El dueño**: recarga fal.ai (D-3; con **$50** cubre imágenes y los 52
  clips con margen). **Las claves de Kling NO se ponen** (D-8): siguen vacías
  en `~/.eko-render.env` a propósito, y el ejecutor lo verifica por longitud
  (= 0). Cualquier edición de ese fichero va con `sed -i` por línea **sobre
  una copia previa** (`cp ~/.eko-render.env ~/.eko-render.env.bak.$(date +%Y%m%d)`).
  **Nunca `cat >` sobre ese fichero, y nunca ejecutar `install-on-rog.sh` sin
  patchearlo** (§3d).
- Orden de proveedores tras la fusión: caché → fal (`flux/schnell`,
  `RENDER_FAL_MODEL`) → *(Kling: sin claves, no entra)* → *(Pexels: ver 3b)*.
  Subir el tope `RENDER_KLING_IMAGES_PER_DAY` (es el contador compartido de
  imágenes generadas, el nombre es histórico) de 8 a **30** (D-4 ✅):
  13 piezas/semana × ~5 escenas ≈ 10 imágenes/día; a $0,003 son **$0,09/día**.

#### 3b — Pexels deja de ser un fallback silencioso

**Archivos:**

- `worker/pictures.py` (`fetch`, `:387` en la rama fal): nueva variable
  `RENDER_STOCK_FALLBACK` (default **`false`**). Con `false`, tras fal y Kling
  `fetch` devuelve `"none"` sin llamar a Pexels. Con `true`, comportamiento de
  hoy (queda para lane A o emergencias, decisión del dueño).
- `worker/produce.py:318-323` ya falla el trabajo si **todas** las escenas son
  tarjeta. Con Pexels fuera, un 403 de fal + Kling sin claves ⇒ todas tarjeta
  ⇒ `ValueError` **no terminal** ⇒ 3 intentos, **cada uno pagando una
  narración MiniMax** (`render_jobs.py:414-422` documenta ese incidente). Y
  una «comprobación previa» no vale: `_spent_today()` está vacío hasta que la
  primera llamada del día recibe el 403, así que el primer trabajo pagaría la
  narración igual. Por eso, dos cambios: (1) **reordenar `produce()`: las
  fotos antes que la voz.** `pictures.fetch` solo necesita `visual_prompt` y
  `people_words` (los `scenes` vienen de la pieza, no de la narración; la
  narración solo aporta los *tiempos*), así que el bucle de `:289-309` puede ir
  antes de `tts.narrate` (`:270-272`) sin tocar `plan_shots`. (2) Con
  `RENDER_STOCK_FALLBACK=false`, el 403 de fal (y el `1102` de Kling) lanzan
  desde `fetch` una excepción **terminal** propia (`NoPictureSupplier`) en vez
  de devolver `False`. Terminal ⇒ `render_jobs.py:433-435` marca el job
  `FAILED` **una sola vez**, con el motivo en `content_pieces.render_error`, y
  `_ring_the_bell` avisa por Telegram — **cero narraciones pagadas** en un día
  sin saldo.
- El motivo en `render_error` tiene que decir **qué hacer**: «fal.ai sin saldo
  desde HH:MM y Kling sin claves: recarga o pon claves; nada se publica hasta
  entonces» ([[feedback_disenar_una_alarma_que_se_escuche]]).

**Tests (`worker/tests/test_lane_b.py`, con los stubs que ya usa esa rama):**
(a) con `RENDER_STOCK_FALLBACK=false` y fal a 403, `fetch` devuelve `"none"` y
Pexels **no se llama** (contador del stub = 0); (b) con `true`, se llama; (c)
`produce()` con fal a 403 y Kling sin claves lanza `NoPictureSupplier` y **el
stub de `tts.narrate` no se ha llamado** (es la prueba del reorden); (d) el
mensaje contiene «recarga». **Mutaciones:** devolver el orden viejo (voz antes
que fotos) → (c) rojo (TTS llamado); ignorar la variable → (a) rojo; convertir
la excepción en `return False` → (c) rojo (no se lanza).

#### 3c — Los cuatro reels *(dueño, en la app de Instagram)*

Buffer no borra posts ya publicados; se hace en la app. Lista y motivo:

| Reel | Repr. | Motivo |
|---|---|---|
| `Dc0D8ysE650` | 1 | *earnest money* sobre `HOME INSURANCE POLICY`, `MICROPRENEUR`, calendario oct-2021 `Check Breasts`, `Jobs wanted` |
| `Dc7QQPeiZ25` | 7 | días en mercado sobre un calendario de 2019 |
| `Dc0EHq9lT5x` | 2 | casa no estadounidense con «For Sale» |
| `Dc0Qlx1CLCr` | 106 | la misma casa; el único con alcance — **se borra también** (D-7 ✅) |

En la base **no se toca nada**: las filas `content_publications` quedan como
historia. Anotar en `PROJECT_STATUS.md` (Fase 5) cuáles se borraron y cuándo.

#### 3d — El instalador no vuelve a borrar claves

`worker/install-on-rog.sh` hace `cat > ~/.eko-render.env <<EOF` (**sobrescribe**).
Cambio mínimo: si `~/.eko-render.env` existe, **no reescribirlo** — solo
actualizar el tar del código y reiniciar el servicio; imprimir «env existente
conservado». Y el despliegue del obrero (Fase 6) usa **solo** ese camino:
`tar` + `systemctl --user restart eko-render-worker`, con `md5sum` del
`pictures.py` remoto antes y después.

**Terminado (Fase 3 entera):** `worker/tests` en verde; `fix/imagenes-fal`
fusionada; `FAL_KEY` en el ROG con longitud > 0 y claves de Kling con longitud
**= 0** (**sin imprimir ninguna**);
`RENDER_STOCK_FALLBACK=false` y `RENDER_KLING_IMAGES_PER_DAY=30` en
`~/.eko-render.env`; una pieza educativa de prueba renderizada **con** el
proveedor en el log (`scene N: fal`, **0 `pexels`**, 0 `kling`); los 4 reels
borrados (confirmación del dueño). Commits: `feat(worker): fal dibuja;
el stock ya no entra en silencio` · `fix(worker): el instalador conserva el env`.

---

### Fase 4 — Las piezas: 18 de otoño + 18 de calculadora

**Objetivo:** 36 piezas en el estudio de contenido, cada una `NEEDS_APPROVAL`
para que **Natalia apruebe** en el panel; las de otoño con vídeo generado ya
montado, las de calculadora con un número real.

#### 4a — Subir un MP4 terminado como `generated` *(backend; no depende de nadie)*

Hoy `upload_clip` (`backend/app/api/v1/content.py:682-735`) hardcodea
`kind=RECORDED, status=DRAFT` y no admite hook/caption. La pieza 18 se subió
así y se editó después. Cambio mínimo:

- `upload_clip` acepta query `?kind=generated|recorded` (default `recorded`,
  para no cambiar el panel). El resto igual: raw-body stream, ruta exenta del
  límite de cuerpo por **coincidencia exacta** (`main.py:232`), fichero
  `uuid4().hex + sufijo` (`:708`; los tres servidores de medios exigen
  `[0-9a-f]{32}\.[a-z0-9]{2,5}`).
- Después, el flujo normal por el panel o por API con sesión: `PATCH /{id}`
  (hook, caption) → `POST /{id}/submit` (422 con las violaciones de Fair
  Housing si las hay) → aprobación **humana** `POST /{id}/approve` (exige
  `media_path`, `:502-520`).
- **Invariantes que ya lo protegen** (no hay que codificar nada): `kind=generated`
  lo excluye de `render_pending` (`content_render.py:348`, solo `RECORDED`);
  `scenes=NULL` lo excluye de `enqueue_generated` (`content_render.py:460`);
  `rebuild_piece` le responderá **409** (`content.py:615-622`) — correcto, no
  hay plan del que reconstruir; sin fila `RenderJob` el panel muestra «sin
  estado de render» (`_with_render_state`, `:368-369`): benigno.

**Tests (`backend/tests/`, el fichero que ya cubra `upload_clip`):** (a)
`?kind=generated` ⇒ `kind == GENERATED`, `scenes IS NULL`, `media_path` puesto;
(b) esa pieza **no** aparece en las consultas de `render_pending` ni
`enqueue_generated` (llamar a las dos funciones y afirmar 0); (c) `rebuild` ⇒
409; (d) sin `kind` ⇒ `RECORDED` como hoy; (e) `kind=otra` ⇒ 422.
**Mutación:** quitar el filtro `kind == RECORDED` de `render_pending` → (b)
rojo.

#### 4b — El montador de piezas estáticas *(repo, fuera del obrero)*

Nuevo `worker/static_piece.py` (importable y CLI), **no** llamado por
`worker/main.py`: 4 clips + texto fijo + bloque de marca + BGM → MP4
1080×1920, 12–13 s. Reglas de [[feedback_shortest_responde_otra_pregunta]]:
duración **declarada** (`-t`) y audio rellenado (`apad`), nunca `-shortest`;
después **medir** con `verify.check(path, expect_audio=True)` (`worker/verify.py:59`)
y comparar la duración con la declarada (±0,1 s) o fallar con el motivo.
Texto con `drawtext` (fuente del repo), bloque de marca desde el segundo 6:
`denverhomestory.com/fall` sobre la línea de marca **leída de la config**
(nunca literal `Engel`; `fallGuide.test.ts:175-187` es el precedente). BGM
`worker/assets/bgm/01-piano.mp3` a −18 dB. Sin voz, sin subtítulos.

**Tests (`worker/tests/test_static_piece.py`, con clips sintéticos de ffmpeg
`color=` de 3 s):** duración exacta, 1080×1920, pista de audio presente, el
texto está en el fotograma 1 s y el bloque de marca en el 8 s (`_grab_frame`
`verify.py:74` + OCR **no**: comparar contra un render de referencia por
correlación como `brand_is_present`, o simplemente afirmar que el fotograma a
8 s difiere del de 1 s en la zona del bloque). **Mutación:** poner `-shortest`
→ el test de duración rojo con un clip de 2,5 s.

#### 4c — Los clips y las imágenes

- **Otoño (vídeo): fal.ai** con `~/fal-tools/fal-gen` (skill `fal`). Modelo
  **D-2** (el dueño confirma **antes del primer vídeo de cada sesión**; los ids
  de fal rotan: consultar `context7 /websites/fal_ai`, no de memoria; fal no
  devuelve el coste en la respuesta: **no inventar cifras**). **Mecánica
  verificada:** `fal-gen video` es image-to-video y exige una **URL** de
  imagen, no un fichero; `fal-gen image` imprime por stdout el JSON completo
  de fal (`fal_gen.py:134`), que trae la URL alojada de la imagen → extraerla
  (`python3 -c 'import sys,json; print(json.load(sys.stdin)["images"][0]["url"])'`)
  y pasarla en el mismo minuto a `fal-gen video --image <url>` (la vigencia de
  esa URL no está documentada: no guardarla para después). **D-2 decidido:**
  primero **una sola pieza** con `fal-ai/kling-video/v2.5-turbo/pro/text-to-video`
  (id y precio confirmados en la doc ese día; en el CSV del 6-sep costó
  $0,07/s), 4 clips ≈ $1,40, montada y **vista por el dueño**. Si vale, las 17
  restantes con ese mismo modelo; si no, se sube **un** escalón
  (`kling-video/v3/pro`, $0,14/s), nunca varios modelos a la vez. Prompts **en
  inglés**, sin personas, sin carteles, sin topónimos. 18 piezas − 5 ★ con foto
  CC = 13 × 4 = **52 clips**; generar **una pieza primero**, montarla, que el
  dueño la vea, y solo entonces el resto. Verificar cada fichero (existe, pesa
  ≠ 0, `ffprobe` lo lee) — un 200 no es un vídeo.
- **Calculadora (imagen fija + `zoompan`)**: el mismo montador con 4 imágenes
  (fal `flux/schnell` o Kling) en vez de clips. Texto: el escenario con su
  número. **El número sale de `frontend/lib/calculator.ts`** (los fixtures
  dorados del plan de la calculadora) ejecutado con los supuestos por defecto
  de la página; se anota en la caption «assumptions on the page».

#### 4d — Los 36 guiones (3 de otoño/semana × 6 semanas = 18; 3 de calculadora/semana = 18)

Formato fijo (el del ganador): 12–13 s, un bloque de texto estático, sin voz,
piano, un solo CTA (`/fall/N` o `/calculator`), hashtags **exactamente**
`#colorado #denver #coloradofall #fall` en otoño y `#colorado #denver
#denverrealestate #firsttimehomebuyer` en calculadora (D-5). **Las 4 primeras
de otoño ya están escritas** (una por franja, sesión del 8-sep; copiar de
`scratchpad/fall-4-piezas.md` a `docs/content/otono-2026.md` en la Fase 0 si
el fichero sigue existiendo; si no, reescribirlas con las franjas de
`fallGuide.ts`). Las otras 14 de otoño (todas sin topónimo salvo las 5 con foto
libre, marcadas ★; todo dato viene de `fallGuide.ts`, nada de memoria):

1. Por qué los álamos giran de arriba abajo (la mecánica, 3 datos).
2. «Una semana de viento lo acaba»: qué mirar en el pronóstico.
3. Entre semana vs. fin de semana en la franja alta.
4. La franja media es la que aguanta un mal pronóstico.
5. ★ Guanella Pass (foto CC, crédito quemado): 40 millas.
6. ★ Kenosha Pass (foto CC): 60 millas por la US 285.
7. ★ Georgetown Loop (foto CC): la que se recorre en tren.
8. ★ Golden Gate Canyon (foto CC): octubre, al noroeste de Golden.
9. ★ Peak to Peak (foto CC): CO 72 y CO 7.
10. Denver a 5.280 ft: los parques, sin nombrarlos, la última franja.
11. «Seis semanas, no tres»: el otoño de Colorado dura lo que dure la bajada
    por altitud (el dato de la caption de la pieza 18).
12. «Un viaje, dos franjas»: a finales de septiembre la franja alta acaba y la
    media empieza — se ven las dos en una salida.
13. Dos senderos desde el centro (sin nombrarlos): el otoño que no exige coche.
14. Recapitulación (última semana de octubre): «las 12, ordenadas por cuándo
    ir» — la guía entera como cierre, enlace a `/fall/4`.

Calculadora (18 escenarios = 6 rentas × 3 ángulos; el número lo da
`calculator.ts`): rentas **$1,800 · $2,200 · $2,600 · $3,000 · $3,500 · $4,000**
× (a) «ese mismo dinero al mes compra hasta $X», (b) «con $Y ahorrados el
techo baja/sube a $X», (c) «a cinco años, comprar vs. alquilar: $Z». Cada
caption termina en `denverhomestory.com/calculator` y en «assumptions on the
page, and you can change them».

**Terminado (Fase 4):** 4a y 4b con tests en verde y mutaciones en rojo; **una
pieza de otoño y una de calculadora** montadas, subidas como `generated`,
vistas por el dueño y **aprobadas por Natalia en el panel**; luego las 34
restantes en `NEEDS_APPROVAL`. Commits: `feat(content): subir un MP4 terminado
como generated` · `feat(worker): montador de piezas estáticas` ·
`docs(content): los 36 guiones de otoño y calculadora`.

---

### Fase 5 — Versión 0.93.0 y el estado

- `backend/app/config.py:16` `APP_VERSION = "0.93.0"`; `frontend/lib/version.ts:1`
  `CURRENT_VERSION` + entrada nueva al principio de `CHANGELOG` (`:16-30`,
  bilingüe); `CHANGELOG.md:5` `## [0.93.0] — <fecha>`. **Mismo commit**
  ([[feedback_version_badge_muerto]]). `test_version_is_one_number.py` lo
  vigila.
- `PROJECT_STATUS.md`: bloque de la 0.93.0 con las salidas **reales** de §2,
  los números de la Fase 0, los reels borrados, y las decisiones D-1…D-5 con su
  respuesta.
- Si la 0.92.0 de la otra sesión ya está en producción: `git rebase` de
  `feat/otono-2026` sobre su commit **antes** de este bump (los tres ficheros
  de conflicto se resuelven aquí y solo aquí).

**Terminado:** suite completa en verde, commit `chore(release): v0.93.0 —
segundo pase diario, imágenes honestas, piezas de otoño y calculadora`.

---

### Fase 6 — Despliegue **[CRÍTICA]** — *solo con autorización del dueño, en mensaje aparte*

Dos máquinas, dos caminos, en este orden:

**6a — VPS (backend + frontend).** Receta de `PROJECT_STATUS.md:918-935`
(bundle → `git fetch` del bundle → `merge --ff-only` → `docker compose build
backend frontend` → `run --rm -T backend alembic upgrade head` (no hay
migración: `alembic current` debe seguir en `055`) → `up -d backend frontend`).
Antes: `SendMessage` a la otra sesión; confirmar `git rev-parse` del VPS = la
base del bundle (**si no, para y rebasa; nunca force**); `pg_dump` con
`sha256sum` en las dos máquinas; `cp .env .env.bak.$(date +%Y%m%d)_v0930`.
**Editar el `.env` del VPS solo con `sed -i` por línea** (los tres
`CONTENT_SLOT_*` con dos horas), nunca `cat >`
([[feedback_el_instalador_borro_las_claves]]). Reversión: `git reset --hard
<anterior>` + build + `up -d`; **nunca `alembic downgrade`**.

**6b — ROG (obrero).** `tar` del `worker/` de la rama → `~/eko-render/app` →
`systemctl --user restart eko-render-worker`. **No ejecutar
`install-on-rog.sh`** salvo que la Fase 3d ya esté fusionada y se haya probado
que conserva el env. Comprobar longitudes de las 4 claves antes y después.

**Verificación (GET, sin leads de prueba):** `health` → `0.93.0`;
`alembic current` = `055`; `logs --since 5m backend | grep -ci traceback` = 0;
`/` `/fall` `/contact` `/calculator` **200** y `/fall/1` **302** con el
`location` correcto; `ssh pcrug 'systemctl --user is-active eko-render-worker'`
= `active`, y en las 24 h siguientes el log del obrero muestra `scene N: fal|kling`
y **0** `pexels`. Luego `docs(status): v0.93.0 desplegada y verificada`, con la
salida pegada. La release (`gh release create v0.93.0 --latest
--generate-notes`) la corre **el dueño**.

---

## 4. Riesgos y supuestos

- **R-1 — La ventana alta.** La franja de +9.500 ft es *mid to late
  September*. Si la Fase 2 no está en producción el **13-sep**, la pieza 1 sale
  **a mano en Buffer** con `denverhomestory.com/fall` pelado (sin rutas cortas)
  para no perder la franja; el resto espera al pipeline.
- **R-2 — Rutas cortas antes que captions.** Ninguna caption con `/fall/N` se
  publica hasta que `curl -sI …/fall/1` dé 302 en producción. Mientras, `/fall`
  pelado.
- **R-3 — Metraje generado con topónimo.** Un clip de Kling bajo «Kenosha
  Pass» es la falla que la guía rechaza. Solo las 5 ★ nombran sitio, y con la
  foto CC de ese sitio y su crédito en el fotograma (CC BY / BY-SA lo exigen).
- **R-4 — `CONTENT_PUBLISH_MAX_PER_DAY` cuenta por día UTC y por pieza
  reclamada** (`_claimed_today`, `buffer_publisher.py:589-602`), mientras los
  huecos cuentan por día local. Con 2 huecos × 3 canales la capacidad real es
  2 piezas/día y el tope de 4 reclamadas queda por encima; si el dueño quiere
  >14/semana, subirlo es otra decisión.
- **R-5 — El obrero corre código no fusionado.** Cualquier despliegue del
  obrero que no parta de `fix/imagenes-fal` fusionada **revierte fal**. Fase 3a
  antes que 6b, siempre.
- **R-6 — `install-on-rog.sh` sobrescribe el env.** Ya borró claves una vez.
  Fase 3d o no se ejecuta.
- **R-7 — Sin Pexels, sin saldo y sin claves = nada se publica.** Es el
  comportamiento **deseado** («mejor sin vídeo que con vídeo equivocado»), pero
  el dueño tiene que saberlo: la alarma llega por Telegram con el motivo, y la
  cola educativa se para hasta que recargue o ponga claves.
- **R-8 — n=1.** El reel ganador cambió ~7 variables a la vez. Las piezas
  nuevas replican el paquete y mueven **una** (el gancho); el UTM por pieza es
  lo que permite aprender algo. Sin conectar vidIQ no habrá saves/shares.
- **R-9 — Dos sesiones, un frontend.** La Fase 1 y la 0.92.0 de la otra sesión
  se despliegan con el mismo `docker compose build frontend`: quien despliegue
  segundo rebasa sobre el primero. Nunca en paralelo.

## 5. Backlog (no justifican fase propia)

- **B-1** Puerta de visión en el obrero (modelo que mire la foto contra la
  escena): credencial y dependencia nuevas en el ROG. Solo si el dueño quiere
  volver a admitir stock.
- **B-2** Evento `guide_link_click` para medir el salto `/fall` → `/calculator`
  (`track.ts:32-42`, `IMMEDIATE`, frozenset de `models/landing.py`).
- **B-3** `href="#consult"` en `/calculator` si la Fase 1 no pudo tocarlo.
- **B-4** `docs/deploy-rog.md` dice que producción es el ROG: **obsoleto** desde
  el 27-ago; corregir.
- **B-5** `CLAUDE.md` dice «no hay `conftest.py` central»: sí lo hay
  (`backend/tests/conftest.py`).
- **B-6** `_claimed_today` cuenta por UTC y los huecos por día local: unificar.

## 6. Decisiones pendientes para el dueño

| # | Decisión | Propuesta | Bloquea |
|---|---|---|---|
| **D-1** | Horas del segundo hueco | ✅ **Decidido 8-sep:** TikTok `08:30,17:30` · Instagram `11:30,18:30` · YouTube `12:30,20:30` | Fase 2 |
| **D-2** | Modelo de vídeo en fal para los clips de otoño | ✅ **Decidido 8-sep: prueba de UNA pieza con `kling-video/v2.5-turbo/pro` y el dueño decide viendo el clip.** Un solo modelo para las 18 piezas. Del CSV del 6-sep, el más barato que ya se probó es `kling-video/v2.5-turbo/pro/text-to-video` a **$0,07/s**; `veo3.1` cuesta $0,40/s (5,7×). Comparar en la doc con image-to-video (`kling-video/v2.1/standard/image-to-video`, default de `fal-gen`, imagen de `flux/schnell` como arranque: mismo look en los 4 clips) **el día de generar**. El dueño elige viendo el clip de prueba de UNA pieza, no seis modelos | Fase 4c |
| **D-3** | Recargar fal.ai | ✅ Gasto conocido por CSV: **$12,48** — $12,27 en vídeo el 6-sep (comparativa de 6 modelos, 76 s), $0,21 en imágenes. Recargar **y** fijar el presupuesto de los 52 clips: **$18–36 a $0,07/s**, $36–73 a $0,14/s (§1.2) | Fase 3a, 4c |
| **D-4** | Tope diario de imágenes generadas | ✅ **Decidido 8-sep: 30** (`RENDER_KLING_IMAGES_PER_DAY`; ≈ $0,09/día en fal) | Fase 3a |
| **D-5** | Hashtags de calculadora | ✅ **Decidido 8-sep:** `#colorado #denver #denverrealestate #firsttimehomebuyer` | Fase 4d |
| **D-6** | ¿Quién hace la Fase 1? | ✅ **Decidido 8-sep y confirmado por el dueño a la otra sesión: el ejecutor de este plan.** La 0.92.0 ya está en producción (`98c9182`): el frontend es de este plan desde ya; avisar a la otra sesión antes del primer commit que lo toque | Fase 1 |
| **D-7** | ¿Conservar `Dc0Qlx1CLCr` (106 repr.)? | ✅ **Decidido 8-sep: se borra.** Los cuatro | Fase 3c |
| **D-8** | Proveedor de imágenes de DHS | ✅ **Decidido 8-sep: fal ÚNICO, Kling fuera del obrero.** El plan de Kling comparte contador mensual con The Power Unleashed; un solo saldo que vigilar; sin saldo, parar y avisar | Fase 3a, 4c |

## 7. Verificación (resumen ejecutable)

```bash
# Fase 2
./.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_buffer_publisher.py   # verde, 0 skipped
# Fase 3
./backend/.venv/bin/python -m pytest -q -p no:cacheprovider worker/tests
ssh pcrug 'grep -aE "scene [0-9]+: (fal|kling|pexels|none)" ~/eko-render/worker.log | tail -20'   # 0 pexels tras el despliegue
# Fase 1 (tras desplegar el frontend)
curl -sI https://www.denverhomestory.com/fall/1 | grep -iE "^(HTTP|location)"          # 302 + utm_content=band1
curl -s -A "Mozilla/5.0" https://www.denverhomestory.com/fall | grep -c 'id="consult"'   # 1
# Fase 6
curl -s -A "Mozilla/5.0" https://inmo-demo.ekoaiautomation.com/api/v1/health            # "version":"0.93.0"
ssh ender-vps "docker exec eko-realestate-db psql -U eko -d eko_realestate -A -F, -c \"select platform, count(*), min(scheduled_at), max(scheduled_at) from content_publications where status in ('scheduled','publishing') group by 1\""
# A los 7 días
ssh ender-vps "docker exec eko-realestate-db psql -U eko -d eko_realestate -A -F, -c \"select utm_content, count(*), count(lead_id) from landing_sessions where landing_path='/fall' and utm_campaign='fall2026' group by 1\""
```

**Criterio de terminado del plan:** 0.93.0 en producción verificada; dos
huecos por canal visibles en `content_publications`; el obrero rinde con
`fal|kling` y 0 `pexels`; `/fall/1..4` → 302; una pieza de otoño y una de
calculadora aprobadas por Natalia y publicadas por el pipeline; los 4 reels
borrados; punto de revisión con datos el **20-oct-2026**.

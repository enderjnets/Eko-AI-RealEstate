# PLAN — «Después de cada vídeo» con nombre, enlace y hora

> Escrito el 8-sep-2026 por la sesión «Eko Ai Realtors». **Ejecutor: Opus 5.**
> Aprobado por el dueño el 8-sep. `PLAN.md` lleva **un solo plan por rama**: el
> anterior (el CTA de `/calculator`, ya desplegado) vive en su rama y en git.
>
> **Rama y worktree ya creados:** `feat/videos-con-nombre`, nacida de
> **`28953e8`** (= lo que corre el VPS: v0.95.0, `/health` verificado por la
> sesión «Viral Videos DHS» el 8-sep), en el worktree
> `~/eko-videos-con-nombre`. **Trabajar ahí, nunca en `~/Eko-AI-RealEstate`**
> (ese checkout es de otra sesión y cambia de rama sin avisar).
> `origin/main` (4c3574d) **no contiene** 28953e8: producción va por delante de
> `main`; no ramificar desde `main` ni fusionar nada en él.
>
> **Versión: 0.96.0**, libre en todo lo publicado el 8-sep (medido por Viral
> Videos: sin tag, sin rama con ese `APP_VERSION`). **La confirma el dueño en
> el mensaje con el que arranque esta ejecución**; si dice otra, se usa esa.

## 0. Método y reglas que no se negocian

**Método.** Una fase cada vez. Máx. 3 intentos de corrección por fase; al
tercero, parar y reportar con diagnóstico y dos salidas. Un commit convencional
por fase (`docs(plan)`, `feat(analytics)`, …), el bump **en el mismo commit**
que el código de la última fase, push de la rama. **Sin merge, sin PR y sin
despliegue salvo que el dueño lo pida en un mensaje aparte.** Subagentes: máx.
2, solo lectura (auditoría), nunca escriben código ni llaman al advisor.
Advisor: (1) al arrancar, (2) antes de la Fase 2 [CRÍTICA], (3) tras el 2º
intento fallido de cualquier fase, (4) si el plan resulta defectuoso (parar y
reportar con dos opciones: cambiar el plan es decisión del dueño), (5) al
cierre, antes de declarar terminado. Cada consulta se registra en
`PROJECT_STATUS.md` (motivo → decisión).

**«Terminado» solo con salida real:** suite backend en verde **sin saltados**;
`ruff` limpio; `tsc`, `vitest`, `next lint`, `next build` en verde; cada test
nuevo visto en rojo con su mutación y el fichero restaurado con `md5`
idéntico; diff sin secretos, sin `console.log`/`print` de depuración;
`PROJECT_STATUS.md` con el checklist y la salida pegada.

**Convivencia con las otras sesiones** (`DenverHomeStory Calculator`, `Viral
Videos DHS`): avisar por `SendMessage` al arrancar (rama, base, versión,
ficheros) y al cerrar (hash final). El número de versión **se pide, no se
toma**. Base de tests **propia**: `eko_realestate_test_videos`; jamás la de
otra sesión. No tocar el ROG ni `worker/`.

**Herramientas.** El hook `rtk` **omite salida** de `grep` y `cat` en este
repo: contar y citar con `Read`, `sed -n` o `python3`, nunca con `grep`/`cat` a
secas. Restaurar ficheros tras una mutación con la copia (`cp`) y `md5`, nunca
con `git checkout -- .`. Secretos: leerlos a variable, verificar **por forma**
(prefijo/longitud), jamás imprimirlos ni pasarlos por el chat; ningún secreto
dentro de un patrón `sed`. El `.env` del VPS no se toca en esta fase (no hay
variables nuevas).

**Entorno del worktree.** El venv y `node_modules` viven en el checkout
principal; se reutilizan sin copiar:
```
PY=/Users/enderj/Eko-AI-RealEstate/backend/.venv/bin/python
ln -s /Users/enderj/Eko-AI-RealEstate/frontend/node_modules ~/eko-videos-con-nombre/frontend/node_modules
```
Backend (desde `~/eko-videos-con-nombre/backend`):
```
export DATABASE_URL=postgresql+asyncpg://eko:<pw>@localhost:5434/eko_realestate_test_videos
export DATABASE_URL_APP=<igual, con el rol de app que use el checkout principal>
export WHATSAPP_ENABLED=true
$PY -m alembic upgrade head        # OBLIGATORIO en una base nueva, antes de pytest
$PY -m pytest -q -p no:cacheprovider
```
Las dos `DATABASE_URL` y la contraseña se copian **de la forma en que las usa
el checkout principal** (ver `docs/` y `feedback_correr_tests_eko_realestate`
en la memoria del dueño); el contenedor es `eko-realestate-db` en el puerto
5434. Crear la base: `createdb`/`CREATE DATABASE eko_realestate_test_videos`
con el rol dueño. **No leer el recuento de `pytest` de un `tail`:** leerlo de
la línea `N passed` con `python3` o `sed -n`.

## 1. Contexto

En `/analytics`, la tarjeta «After each video» lista una fila por publicación
con la etiqueta `#14 · TikTok` y una fecha corta («Sep 8»). El dueño no sabe a
qué vídeo se refiere cada número. Pidió: **título del vídeo, enlace al post y
fecha y hora de publicación**, y que la sección sea fácil de leer.

Decisiones tomadas con él el 8-sep (no se reabren):
1. **Una tarjeta por vídeo** (agrupada por pieza), con el título arriba.
2. **Fecha y hora en cada línea de plataforma**, en horario de la agencia
   (`AgentSettings.timezone`, hoy `America/Denver`): YouTube y TikTok salen
   con 12-14 h de diferencia y las cifras de 48 h se cuentan desde la hora de
   cada plataforma.
3. **Recuperar de Buffer los enlaces** de las 15 publicaciones viejas (piezas
   3-8, camino `shareNow`) que no lo guardaron.

Lo medido (8-sep; producción en solo lectura y código en 28953e8):

| Hecho | Dónde |
|---|---|
| El título es `ContentPiece.hook` (String(300), nullable); todas las piezas de producción lo tienen | `backend/app/models/content.py:113` |
| `ContentPublication` guarda `external_id` (id del post en Buffer), `published_at`, `scheduled_at`, `external_url`; única por (piece, platform) | `models/content.py:183-244` |
| El payload de analytics **ya lleva `external_url`** pero la tarjeta no lo pinta; **no lleva `hook`** (el select no une `ContentPiece`); `publication_id` se lee (`row[0]`) y no se emite | `backend/app/services/analytics.py:532-629`, `ContentTable.tsx:157-162` |
| La fecha se pinta con `toLocaleDateString` sin `timeZone` ni hora; `data.range.timezone` ya viaja en el payload | `ContentTable.tsx:131-135`, `frontend/lib/api.ts:1146` |
| `exactTime(iso, lang, timezone)` es el formateador con zona que ya usa la cola de contenido | `frontend/lib/format.ts:62-71`, `components/content/ContentQueue.tsx:370` |
| Patrón de enlace ya existente: `<a href={pub.external_url} target="_blank" rel="noopener noreferrer" …>{t("content.watchOn", {platform})}</a>` | `ContentQueue.tsx:378-398` |
| El enlace lo escribe **solo** el reconciliador (`externalLink` de `_POST_STATE`) y **solo** para filas `SCHEDULED`; `shareNow` publica sin enlace y nadie vuelve a mirar una `PUBLISHED` sin url | `buffer_publisher.py:98, 836-837, 866-871, 1007-1012` |
| El reconciliador se llama desde `publish_approved` (`:1097`), bajo `run_for_every_org` (`main.py:580`) y las puertas de publicación | `buffer_publisher.py:1070-1097` |
| Producción: publicadas sin enlace **youtube 5/9, tiktok 5/10, instagram 5/10**; sin `published_at`: 0 | `psql` 8-sep |
| `snapshot_youtube` **salta** las publicaciones sin `external_url` → recuperar el enlace también activa las vistas automáticas de esos 5 YouTube | `backend/app/services/video_metrics.py:237-245` |
| `analyticsPage.test.ts` es un test de **texto fuente** sobre `ContentTable.tsx`. Deben sobrevivir literalmente: `analytics.assoc48`, `r.association.sessions`, `row.views?.count`, `TYPED_BY_HAND = new Set(["tiktok", "instagram"])`, `TYPED_BY_HAND.has(row.platform)`, `count === null`, `analytics.noViews`, `value.trim() === ""`, `analytics.viewsTyped`, `analytics.viewsRead`; y el negativo `not.toMatch(/association\.sessions \+/)` | `frontend/lib/__tests__/analyticsPage.test.ts` |
| No hay jsdom ni testing-library: los tests de frontend son de forma del fuente o de módulos puros (`latestWins.ts` + su test es el precedente) | `frontend/vitest.config.ts` |
| Claves i18n existentes: `analytics.content/contentHint/assoc48/addViews/noViews/viewsTyped/viewsRead/tagged`, `analytics.empty.content`, `platform.youtube/tiktok/instagram`, `content.watchOn`, `content.publishedLabel` | `frontend/lib/i18n.tsx` EN ~230-283, ES ~1195-1248 |
| `i18nParity` exige cada `t("literal")` en EN y ES | `frontend/lib/__tests__/i18nParity.test.ts` |

## 2. Alcance

**Dentro:** título, enlace y fecha-hora por plataforma en la tarjeta;
agrupación por vídeo; cifras de 48 h etiquetadas («visitas · leads»); el
backend expone `hook` y `publication_id`; el límite cuenta vídeos, no
publicaciones; backfill de enlaces desde Buffer para filas `PUBLISHED` sin url;
tests y mutaciones; bump 0.96.0.

**Fuera, dicho en voz alta:** vistas de TikTok/Instagram (siguen a mano); el
obrero del ROG; el camino de envío de Buffer (solo el reconciliador); el modelo
«asociación, no atribución» (se mantiene tal cual, con su texto); el idioma de
los vídeos (propuesta aparte, pendiente de aprobación del dueño); rendimiento
de `content()` (hasta 120 consultas por carga; se anota, no se arregla).

## 3. Fases

### Fase 0 — Medir antes de tocar (solo lectura; sin código)

1. `cd ~/eko-videos-con-nombre && git status` limpio, HEAD 28953e8. Enlazar
   `node_modules`. Crear la base `eko_realestate_test_videos` y correr
   `alembic upgrade head`.
2. **Verde de referencia**, con recuento leído de la salida:
   backend `pytest -q` (esperado ≈ 1798 passed, 0 skipped, la cifra de la
   0.95.0), frontend `npx vitest run` (≈ 383), `npx tsc --noEmit`, `npx next
   lint`, `ruff check app tests`. Anotar en `PROJECT_STATUS.md`.
3. Avisar por `SendMessage` a las dos sesiones: rama, base 28953e8, 0.96.0,
   ficheros que se tocan (lista de §5).
4. **Sonda de Buffer, solo lectura, dentro del contenedor del backend** — usa
   el mismo código y el mismo token sin sacarlo del proceso:
   ```
   ssh ender-vps "docker exec eko-realestate-db psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \
     \"select id, platform, external_id from content_publications where status='published' and external_url is null order by id\""
   ```
   y luego, con 3 `external_id` de esa lista (uno por plataforma), un script
   `python -c` ejecutado con `docker exec eko-realestate-backend python -c '…'`
   que llame a `app.services.buffer_publisher._graphql(query, variables)` con
   una consulta aliasada `p0/p1/p2: post(input:{id:$pN}) { status sentAt
   externalLink error { message } }` y **imprima solo**, por alias: `status`,
   si `externalLink` viene o no, y el `code` del error si lo hay. **Nunca el
   token, nunca la URL completa.** Después, la misma consulta con **20 alias**
   (repitiendo ids si hace falta) para saber si Buffer acepta el tamaño del
   batch (hoy solo hay 6 medidos).
   - Si `externalLink` **no** viene para posts antiguos de `shareNow`: **el
     backfill es un no-op. Parar y reportar** al dueño con dos salidas
     (entrada manual del enlace por pieza en la consola, o dejarlas sin
     enlace) — cambiar el plan es decisión suya.
   - Si Buffer rechaza 20 alias: fijar `_BACKFILL_BATCH` al mayor tamaño que
     aceptó y anotarlo.
5. Commit `docs(plan): la tarjeta de vídeos con nombre, enlace y hora — Fase 0
   medida` con `PROJECT_STATUS.md`. Push.

### Fase 1 — Backend: el payload nombra al vídeo

`backend/app/services/analytics.py`, `content()` (`:532-629`):

- Importar `ContentPiece` del bloque `from app.models import (` (`:32`).
- Sustituir el select de `:547-563` por dos pasos: una subconsulta con los
  `limit` `piece_id` más recientes por `max(published_at)` dentro de la
  ventana, y el select principal con `join(ContentPiece, ContentPiece.id ==
  ContentPublication.piece_id)` que devuelve **todas** las publicaciones en
  ventana de esas piezas:
  ```python
  recent = (
      select(ContentPublication.piece_id)
      .where(ContentPublication.published_at.is_not(None),
             w.within(ContentPublication.published_at))
      .group_by(ContentPublication.piece_id)
      .order_by(func.max(ContentPublication.published_at).desc(),
                ContentPublication.piece_id.desc())
      .limit(limit)
  )
  rows = (await db.execute(
      select(ContentPublication.id, ContentPublication.piece_id,
             ContentPublication.platform, ContentPublication.published_at,
             ContentPublication.external_url, ContentPiece.hook)
      .join(ContentPiece, ContentPiece.id == ContentPublication.piece_id)
      .where(ContentPublication.published_at.is_not(None),
             w.within(ContentPublication.published_at),
             ContentPublication.piece_id.in_(recent))
      .order_by(ContentPublication.published_at.desc(), ContentPublication.id.desc())
  )).all()
  ```
- El bucle pasa a `for publication_id, piece_id, platform, published_at, url,
  hook in rows:` y el dict emitido gana `"publication_id": publication_id` y
  `"hook": hook`. `latest_metrics(db, [row[0] for row in rows])` (`:576`) no
  cambia: el id sigue en la columna 0.
- Docstring: una frase — el límite cuenta vídeos para que ninguna tarjeta se
  corte entre plataformas. Router (`api/v1/analytics.py:110`) y
  `AnalyticsOut.content: list[dict]` no cambian.

**Tests** (`backend/tests/test_analytics.py`; patrón y fixture de `:411-457`,
que ya crea una pieza con `hook="analytics range check"`):
1. `test_each_row_names_its_video_and_its_own_publication`: una pieza, dos
   publicaciones (youtube con `external_url="https://youtube.com/shorts/abc"`
   a ahora−1 d; tiktok sin url a ahora−2 d). `GET /api/v1/analytics?range=7d`
   → 2 filas; cada `row["hook"] == "analytics range check"`;
   `{row["publication_id"]} == {yt_id, tt_id}`; la fila de youtube devuelve la
   url sembrada. Mutaciones: quitar el join → `KeyError`; emitir `piece_id`
   como `publication_id` → los conjuntos no coinciden.
2. `test_the_limit_counts_videos_not_posts`: dos piezas × dos plataformas en
   ventana; `svc.content(db, window, limit=1)` bajo `org_scope(ORG)` +
   `get_session_factory` (patrón `:402-405`) → **2** filas, ambas de la pieza
   más nueva. Mutación: mover `.limit(limit)` al select de publicaciones → 1.
3. Ampliar `test_one_agency_never_reads_anothers_numbers` (`:357`): con una
   publicación de ORG, `svc.content` bajo `org_scope(2)` → `[]` y bajo ORG →
   1 (el join añade una segunda tabla con RLS). Mutación: sesión bypass en la
   aserción de org 2 → rojo.

Criterio: los 3 en rojo antes, verde después, mutaciones vistas; `ruff`
limpio. Commit `feat(analytics): el payload nombra al vídeo y cuenta vídeos,
no publicaciones`.

### Fase 2 [CRÍTICA] — Backfill de enlaces en el reconciliador de Buffer

**Advisor antes de escribir.** Por qué es crítica: `buffer_publisher.py` es el
camino por el que sale cada publicación de producción; un error aquí marca
posts vivos como fallidos o los reenvía.

`backend/app/services/buffer_publisher.py`:
- **Extraer** de `reconcile_scheduled` (`:846`) las líneas `:901-975` (alias,
  variables, consulta, `try/except (BufferRefused, httpx.HTTPError)`, errores
  emparejados por `path`, «sin datos y sin errores» → aviso) a un ayudante:
  ```python
  async def _post_states(rows, what: str
  ) -> list[tuple[ContentPublication, dict | None, dict | None]] | None:
      """Una lectura aliasada por lote: (fila, post, error) por fila; None si no se pudo preguntar."""
  ```
  `reconcile_scheduled` pasa a `answers = await _post_states(due, "scheduled
  posts")`, `if answers is None: return 0`, e itera `for row, post, err in
  answers:` con sus ramas (`:981-1029`) **intactas**. El bloque de comentario
  «Measured against the real API» se va con el ayudante. **Los tests actuales
  del reconciliador (`test_buffer_publisher.py:1353-1700`) son la red de la
  extracción: verdes antes de seguir.**
- **Nuevo** `backfill_links(db) -> int`, debajo de `_close_touched` (`:1051`):
  ```python
  _BACKFILL_BATCH = 20            # o lo que la sonda de la Fase 0 dijo que Buffer acepta
  _BACKFILL_LOOKBACK = timedelta(days=60)

  async def backfill_links(db: AsyncSession) -> int:
      if get_settings().BUFFER_SIMULATED:
          return 0
      missing = (await db.execute(
          select(ContentPublication).where(
              ContentPublication.status == PublicationStatus.PUBLISHED,
              ContentPublication.external_url.is_(None),
              ContentPublication.external_id.is_not(None),
              ContentPublication.published_at >= datetime.now(UTC) - _BACKFILL_LOOKBACK,
          ).order_by(ContentPublication.id.asc()).limit(_BACKFILL_BATCH)
      )).scalars().all()
      if not missing:
          return 0
      answers = await _post_states(missing, "published posts without a link")
      if answers is None:
          return 0
      linked = 0
      for row, post, err in answers:
          if err is not None or post is None:
              continue
          if (post.get("status") or "").lower() != _BUFFER_SENT:
              continue
          link = post.get("externalLink") or None
          if link:
              row.external_url = link
              linked += 1
      if linked:
          await db.commit()
          log.info("Recovered %s publication link(s) from Buffer", linked)
      return linked
  ```
  Reglas que codifica: escribe **solo** `external_url`; nunca `status`,
  `published_at`, `last_error`, ni llama a `_close_touched`; un `NOT_FOUND`
  sobre una fila publicada no escribe nada (que Buffer olvide un post no es un
  veredicto sobre un post que salió). Un solo comentario, el porqué del
  lookback (una fila que Buffer nunca responde no puede costar una petición
  por tick para siempre; lo anterior a 60 días no se recupera solo).
- Llamada en `publish_approved` justo después de `await
  reconcile_scheduled(db)` (`:1097`): misma puerta `CONTENT_PUBLISH_ENABLED`,
  mismo `run_for_every_org` (RLS por organización).
- Barridos AST: `backend/tests/test_content_gate_is_absolute.py` y
  `test_opt_out_is_absolute.py` no deben ver ningún `.post` nuevo; correr los
  dos ficheros y pegar el resultado.

**Tests** (`backend/tests/test_buffer_publisher.py`, sección nueva «The
backfill: links for posts that went out before the queue»; ayudantes
existentes `_cleanup` `:96`, `_brokerage` `:103`, `class _Recorder` `:157`
(responde por id de post), `_sched(piece_id)` `:811`, `_scheduled_row` `:1336`;
crear `_published_row(piece_id, platform, external_id, *, url=None,
age=timedelta(hours=1)) -> int` que inserta una fila `PUBLISHED` con
`published_at = ahora − age`):
4. `test_a_post_that_went_out_without_a_link_gets_one_from_buffer`: fila
   `yt-old`; el recorder responde `sent`, `sentAt` de agosto, `externalLink`
   → `backfill_links(db) == 1`; `_sched` muestra la url; `published_at`
   idéntico al segundo. Mutaciones: escribir `published_at` desde `sentAt` →
   rojo; no asignar `external_url` → rojo.
5. `test_a_post_buffer_holds_no_link_for_is_left_exactly_as_it_was`: `sent`
   sin `externalLink` y otra fila respondida con error `NOT_FOUND` (`path
   ["p1"]`) → 0; ambas siguen `published`, url `None`, `last_error` None.
   Mutación: copiar la rama FAILED del reconciliador → rojo.
6. `test_the_backfill_asks_only_about_published_rows_without_a_link`: (a)
   publicada con url, (b) `SCHEDULED` vencida (`_scheduled_row(...,
   due_minutes=-5)`), (c) publicada sin url → 1 alias en `recorder.queries`;
   (b) sigue `scheduled`. Mutaciones: quitar `external_url.is_(None)` → 2;
   quitar el filtro de estado → 3.
7. `test_the_backfill_is_bounded_per_tick`: `monkeypatch.setattr(…,
   "_BACKFILL_BATCH", 2)`, tres filas → 2 alias. Mutación: quitar `.limit`.
8. `test_a_link_older_than_the_lookback_is_not_asked_for`: `age=61 días` →
   ninguna consulta. Mutación: quitar la cláusula de `published_at`.
9. `test_the_backfill_is_silent_when_buffer_cannot_answer`: `_graphql` que
   lanza (patrón `_boom` existente) → 0, fila intacta.
10. `test_simulation_asks_buffer_nothing_for_links`: `BUFFER_SIMULATED=True`
    → 0 y `recorder.queries == []`. Mutación: quitar la guarda.
11. `test_the_tick_recovers_links_after_reconciling`: `_cleanup()`,
    `_brokerage()`, una publicada sin url, recorder con el enlace;
    `publish_approved(db)` → url puesta. Mutación: borrar la llamada en
    `publish_approved` → rojo.

Criterio: tests 4-11 en rojo antes y verde después; los del reconciliador
verdes tras la extracción; mutaciones vistas y `md5` restaurado; `ruff`
limpio. Commit `feat(publisher): recuperar de Buffer el enlace de los posts
que salieron sin él`.

### Fase 3 — Frontend: la tarjeta

- `frontend/lib/api.ts:1207`: añadir `publication_id: number;` y `/** El hook
  de la pieza: su título en la consola. Null si se escribió sin él. */ hook:
  string | null;`.
- **Nuevo** `frontend/lib/videosByPiece.ts` (puro, sin React; precedente
  `frontend/lib/latestWins.ts`):
  ```ts
  export const PLATFORM_ORDER = ["youtube", "instagram", "tiktok"];
  export interface PublishedRow { piece_id: number; hook: string | null; platform: string; published_at: string }
  export interface Video<R extends PublishedRow> { piece_id: number; title: string; rows: R[] }
  export function videoTitle(row: { hook: string | null; piece_id: number }): string   // hook?.trim() || `#${piece_id}`
  export function groupByPiece<R extends PublishedRow>(rows: R[]): Video<R>[]
  ```
  Semántica: agrupar por `piece_id`; filas dentro del vídeo por
  `PLATFORM_ORDER` (desconocidas al final, orden estable); vídeos por su
  `published_at` **máximo** desc, empate `piece_id` desc.
- `frontend/components/analytics/ContentTable.tsx` (190 líneas hoy):
  - Props `{ rows, timezone }: { rows: Analytics["content"]; timezone: string }`.
  - Importar `exactTime` de `@/lib/format` y `groupByPiece, videoTitle` de
    `@/lib/videosByPiece`. **Borrar `when()` (`:131-135`) y todo
    `toLocaleDateString`.**
  - `Views`, `TYPED_BY_HAND`, el estado `typed` y su clave
    `${piece}-${platform}`: **sin cambios**.
  - Tarjeta por vídeo: `rounded-lg border border-white/5 bg-white/[0.02] p-3
    space-y-2`. Cabecera: `<div className="text-sm text-white leading-snug
    line-clamp-2">{video.title}</div>` (nunca `truncate`: el título es el
    punto).
  - Una línea por plataforma, `flex flex-wrap items-center gap-x-3 gap-y-1
    border-t border-white/5 pt-2`:
    - izquierda (`min-w-0 flex-1 text-xs`): `{t(`platform.${r.platform}`)}`
      · `{exactTime(r.published_at, lang, timezone)}` en gris · si hay
      `r.external_url`: `<a href={r.external_url} target="_blank"
      rel="noopener noreferrer" className="text-eko-violet
      hover:underline">{t("content.watchOn", { platform: t(`platform.${r.platform}`) })}</a>`;
      si no: `{t("analytics.noLink")}` en gris.
    - centro: `<Views row={withTyped} onSaved={…} />` exactamente como hoy.
    - derecha: `{r.association.sessions} {t("analytics.visitsAfter")} ·
      {r.association.leads} {t("analytics.leadsAfter")}` sobre el pie
      `{t("analytics.assoc48")}`; el bloque `leads_tagged` igual que hoy.
      **Ningún `+` junto a `association.sessions`** (regex negativa del test).
  - `flex-wrap` deja caer las cifras a una segunda línea en 390 px en vez de
    desbordar; nada de `overflow-x`.
- `frontend/components/analytics/AnalyticsView.tsx:260` → `<ContentTable
  rows={data.content} timezone={data.range.timezone} />`.
- `frontend/lib/i18n.tsx`, tres claves en EN (tras `analytics.tagged`, ~:238)
  y ES (~:1203), en la forma de una línea `"clave": "valor",` que parsean
  `analyticsPage.test.ts` e `i18nParity`:
  `analytics.visitsAfter` («visits» / «visitas»), `analytics.leadsAfter`
  («leads» / «leads»), `analytics.noLink` («no link yet» / «sin enlace
  todavía»). Se reutilizan `content.watchOn` y `platform.*`.

**Tests:**
12. **Nuevo** `frontend/lib/__tests__/videosByPiece.test.ts` (puro): tres
    filas de una pieza dadas como tiktok/youtube/instagram → un vídeo con
    líneas youtube, instagram, tiktok (mutación: quitar el orden); dos vídeos
    salen del más nuevo al más viejo por su publicación más reciente
    (mutación: asc); `videoTitle` devuelve `#7` para `null` y para `"   "`
    (mutación: `??` en vez de `||` sobre el hook recortado).
13. `analyticsPage.test.ts`, `describe("the card names the video")` sobre el
    fuente de `ContentTable.tsx` y `AnalyticsView.tsx`: contiene
    `groupByPiece(` y `videoTitle(` (mutación: volver a `#{r.piece_id}`);
    `toMatch(/exactTime\([^)]*timezone\)/)` y `not.toContain("toLocaleDateString")`
    (mutación: restaurar `when()`); la vista contiene
    `timezone={data.range.timezone}` (mutación: quitar la prop); contiene
    `href={r.external_url}`, `rel="noopener noreferrer"` y `content.watchOn`
    (mutación: quitar `rel`); las tres claves nuevas están en ambos
    diccionarios y `visitsAfter !== leadsAfter` (mutación: borrar la clave
    ES → también la ve `i18nParity`).
14. **Navegador a 390 px** con Playwright MCP contra el frontend local
    (`npm run dev` en un puerto libre, p. ej. 3011, apuntando al backend
    local o al túnel; **pestaña propia: `browser_tabs` para listar y cerrar
    solo la mía, nunca `browser_close`**): un vídeo con título completo, hora
    por plataforma en Denver, enlace que abre en pestaña nueva, lápiz de
    vistas funcionando, sin scroll horizontal. Captura en
    `PROJECT_STATUS.md` como descripción, no como fichero en el repo.

Criterio: `tsc`, `vitest` (≥ referencia + nuevos; `i18nParity` y
`analyticsPage` verdes), `next lint`, `next build`; mutaciones vistas. Commit
`feat(analytics): cada vídeo con su nombre, su enlace y su hora`.

### Fase 4 — Versión, estado y cierre

- Bump **0.96.0** (o la que el dueño haya dicho) en `backend/app/config.py`
  (`APP_VERSION`), `frontend/lib/version.ts` (`CURRENT_VERSION` + entrada
  CHANGELOG EN/ES: título, enlace y hora por plataforma; recuperación de
  enlaces; 48 h etiquetadas; límite por vídeo) y `CHANGELOG.md` (`## [0.96.0]
  — <fecha>`, `Added`/`Changed`). **En el mismo commit que la Fase 3** (o un
  `chore(release)` inmediato si la Fase 3 ya se commiteó; nunca sin código
  detrás).
- `PROJECT_STATUS.md`: sección nueva **arriba**, sin tocar el histórico:
  checklist con salida real (recuentos, `ruff`, `tsc`, `lint`, `build`),
  tabla de mutaciones (fichero, mutación, test que se puso en rojo, `md5`
  restaurado), sonda de Buffer (Fase 0.4), consultas al advisor, versión,
  y «lo que el despliegue NO debe hacer»: ninguna migración (`alembic
  current` sigue en `055_calculator_snapshot`), ningún cambio en el `.env`.
- **Auditoría independiente**: máx. 2 subagentes de solo lectura sobre el
  diff `28953e8..HEAD`; hallazgos clasificados bloqueante / importante /
  menor, con evidencia; los bloqueantes e importantes se corrigen antes de
  cerrar y se anotan.
- Advisor de cierre. Push de la rama. Avisar a las dos sesiones con el hash
  final. **Parar: merge, tag, release y despliegue los pide el dueño.**

## 4. Riesgos y supuestos

1. Buffer puede no devolver `externalLink` para posts viejos de `shareNow` →
   la Fase 0.4 lo mide **antes** de escribir el backfill; si no, se para.
2. Un batch de 20 alias puede exceder lo que Buffer acepta → medido en 0.4;
   `_BACKFILL_BATCH` toma ese valor.
3. Hasta 20 vídeos × 3 plataformas × 2 cuentas = 120 consultas por carga de
   página (hoy 40). Aceptado; anotar en el estado.
4. El backfill corre dentro de `publish_approved`: si
   `CONTENT_PUBLISH_ENABLED` está apagado no corre. Es lo correcto.
5. `hook` nulo en una pieza futura → `videoTitle` cae a `#id`.
6. `test_buffer_publisher.py:669` ejecuta `publish_approved` sobre una tabla
   que otro test limpió; si un resto `PUBLISHED` sin url lo pone en rojo, se
   añade `await _cleanup()` al inicio de ese test (higiene, no relajación).
7. El obrero del ROG no se re-subió tras la 0.95.0 (solo un docstring): su
   `md5` no coincide con la rama hasta que Viral Videos lo suba. No usar esa
   coincidencia como verificación en esta fase (no hace falta: no se toca).

## 5. Ficheros que se tocan

- `backend/app/services/analytics.py` · `backend/app/services/buffer_publisher.py`
- `backend/tests/test_analytics.py` · `backend/tests/test_buffer_publisher.py`
- `frontend/lib/api.ts` · **nuevo** `frontend/lib/videosByPiece.ts` ·
  `frontend/components/analytics/ContentTable.tsx` ·
  `frontend/components/analytics/AnalyticsView.tsx` · `frontend/lib/i18n.tsx`
- **nuevo** `frontend/lib/__tests__/videosByPiece.test.ts` ·
  `frontend/lib/__tests__/analyticsPage.test.ts`
- `backend/app/config.py` · `frontend/lib/version.ts` · `CHANGELOG.md` ·
  `PROJECT_STATUS.md` · `PLAN.md` (esta sección)

## 6. Verificación (resumen ejecutable)

- Backend, desde `~/eko-videos-con-nombre/backend`, base propia migrada:
  `$PY -m ruff check app tests`; `$PY -m pytest -q -p no:cacheprovider`
  → **0 skipped**, `passed` ≥ referencia + 11; correr aparte
  `tests/test_content_gate_is_absolute.py tests/test_opt_out_is_absolute.py
  tests/test_video_metrics.py`.
- Frontend, desde `~/eko-videos-con-nombre/frontend`: `npx tsc --noEmit`;
  `npx vitest run` (≥ referencia + nuevos); `npx next lint`; `npx next build`.
- Mutaciones: copiar → mutar → rojo en **el** test que corresponde →
  restaurar → `md5` idéntico. Verde limpio **antes** de mutar.
- Diff `28953e8..HEAD`: sin secretos (barrer con `python3`, no con `grep`
  bajo el hook), sin `console.log`/`print`.
- **Tras el despliegue, solo si el dueño lo pide** (bundle → `scp` → `git
  fetch && git merge --ff-only` en el VPS → `docker compose build backend
  frontend` → `up -d`; sin `alembic upgrade`): `/health` = 0.96.0; el
  payload de `GET /api/v1/analytics?range=90d` lleva `hook` y
  `publication_id` en cada fila y tantos `piece_id` distintos como tarjetas;
  en `psql`, publicadas sin enlace antes (5/5/5) y tras dos ticks de
  `CONTENT_PUBLISH_INTERVAL_SECONDS` → 0 (o exactamente las que la sonda
  dijo que Buffer no responde); `published_at` de las piezas 3-8 **idéntico**
  antes y después; `docker logs eko-realestate-backend --since 1h` con líneas
  `Recovered`; en el siguiente `snapshot_youtube`, `content_metrics` de
  YouTube para las piezas 3-8 deja de ser 0.

---

# PLAN — Idioma de los vídeos, una cifra de 48 h por vídeo y la tarjeta a 390 px

> Escrito el 9-sep-2026, tras desplegar v0.97.0. Mismo método que el plan
> anterior (§0): una fase cada vez, máx. 3 intentos, un commit por fase, el
> bump en el último, **sin merge ni despliegue sin pedirlo aparte**. Advisor al
> arrancar y al cierre; cada consulta en `PROJECT_STATUS.md`. Base de tests
> propia `eko_realestate_test_videos`, `alembic upgrade head` antes de `pytest`.

## Contexto (medido en producción, solo lectura, 9-sep)

| Hecho | Dónde |
|---|---|
| El borrador diario alternaba sobre `AgentSettings.languages`, la lista en la que el **chat** responde | `content_writer.py:_language_for` |
| La agencia viva tiene `languages = ["en","es"]`: uno de cada dos borradores salía en español | `agent_settings` id 1 |
| Piezas generadas: 50 `en`, 3 `es` (ids 13, 15, 20) — **las tres `rejected`** por el dueño los días 6, 7 y 8. Ninguna se publicó | `content_pieces` |
| Las 18 piezas 40-57 se crearon en bloque por la API a las 02:20 del 9-sep, en inglés explícito: no pasan por `_language_for` | `content_pieces`, `api/v1/content.py:create_draft` |
| Con 57 piezas generadas (impar), el **siguiente** borrador diario con el código viejo habría salido en español | `count % len(configured)` |
| La cifra de 48 h se calculaba **por publicación**: una visita en el solape de dos ventanas (las plataformas salen 12 h aparte) contaba en las dos filas | `analytics.py:content()` |
| `leads_tagged` ya era por pieza (la etiqueta nombra la pieza) pero se pintaba por fila | `ContentTable.tsx` |
| A 390 px la línea `plataforma · hora · enlace` se partía en tres renglones | captura `tarjeta-390px.png` |

## Decisiones del dueño (8/9-sep)

1. El español sigue siendo posible, **por agencia y desde Ajustes**.
2. Una agencia puede marcar **varios idiomas y alternan**.
3. Solo inglés por defecto.
4. **Una** cifra de 48 h por vídeo (acordado tras desplegar v0.97.0).

## Fases

**Fase 1 — idioma de los vídeos.** Columna `content_languages` (JSON, NOT NULL,
`["en"]`, migración `057_content_languages` con `server_default` porque hay
fila viva). `_language_for` alterna sobre esa lista; inglés en los dos
fallbacks. `PUT /settings` acepta solo `en`/`es` (400 al resto, 422 a la lista
vacía). Ajustes: sección «Idiomas de los vídeos» con su propia lista (no
`KNOWN_LANGS`, que trae `pt`/`fr` sin prompt). Tests: escritor (3), API (3),
agencia nueva (1), forma del formulario (2). `visual_prompt` sigue en inglés
por `not_english_prompt`, sin cambios.

**Fase 2 — una cifra por vídeo y la tarjeta.** `content()` calcula la
asociación por pieza sobre la **unión** de las ventanas de 48 h de sus
publicaciones en rango (`_within_any`: OR de intervalos, no un tramo del primer
post al último) y la estampa idéntica en cada fila: el payload no cambia de
forma. Dos consultas por vídeo en vez de dos por publicación. Tarjeta: cifra y
`leads_tagged` una vez junto al título; cada plataforma en dos renglones
(`plataforma · hora` / enlace). Rótulo: «48h after each post» / «48 h tras cada
publicación». Tests: backend (1, tres piezas: solape, una sola, días aparte),
forma (3). Captura a 390 px y escritorio con los 30 registros reales.

**Fase 3 — versión (se pide), `version.ts` EN/ES, `CHANGELOG.md`,
`PROJECT_STATUS.md`, push. Merge y despliegue: pedirlos.** El despliegue **sí
lleva migración**: el contenedor arranca `uvicorn` a secas, así que tras
`up -d --build` hay que correr `docker compose exec backend alembic upgrade
head` y comprobar `alembic current` = 057 y `content_languages = ["en"]` en la
fila viva.

## Fuera de alcance (anotado)

- El índice de alternancia cuenta **todas** las piezas generadas, incluidas las
  creadas en bloque por la API: `["en","es"]` no alterna limpio en una agencia
  que además crea en bloque.
- Las tres piezas rechazadas en español no se tocan.

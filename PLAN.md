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

---

# PLAN (5) — Del alcance a la conversación

**Escrito el 16-sep-2026, 22:40 UTC, por Fable 5.1. Ejecutor: Claude Opus 5.**
Objetivo del dueño, literal: *«que tengamos el suficiente tráfico en la página
para que nos dé un número decente de gente llenando el formulario y/o
apretando el botón para contactarnos y hablar con Clara»*.

Lo que este plan sostiene, con la medición de abajo: **el alcance ya existe
(≥ 8.760 vistas) y el problema está después** — no hay puerta desde TikTok, la
puerta de YouTube aterriza en un formulario vacío, el instrumento no distingue
personas de robots, y el formato que consigue vistas no consigue que nadie haga
nada. Más vistas por el mismo tubo dan más cero.

Y dos cosas que llegaron el mismo día y cambian el orden: **Natalia dijo que sí
al vídeo de la casa abierta del sábado 19 y sí a las seis cartas restantes**, y
Robbie manda cada viernes la lista de avisos de ejecución hipotecaria de Land
Title — la primera lista de **alta intención** de toda la operación.

## ⛔ Para el ejecutor — no negociable, antes de la primera acción

1. **Confirma «Protocolo Fable activo»** en tu primera respuesta (CLAUDE.md).
2. **Lee estas memorias antes de tocar nada:**
   `feedback_una_cola_llena_no_es_una_pieza_mala`,
   `project_eko_realtors_cola_publicacion`,
   `feedback_idioma_correos_eko_realtors`, `feedback_un_buzon_sin_cartero`,
   `feedback_coordinar_entre_sesiones`.
3. **NUNCA** `cat`, `grep` multi-fichero ni `git diff` para contar o concluir en
   este repo: `rtk` reescribe la salida. `Read`, `sed -n` o `python3`.
4. **NUNCA** toques `eko-frontend`, `eko-backend`, `eko-db`, `eko-redis`,
   `eko-pipeline`, `eko-celery-*`, `eko-*-main`, `eko-frontend-pricing-v2`, ni
   nada `zorros-*` o `blackvolt-*` en el VPS.
5. **Nada se envía sin aprobación explícita de Ender** — correo, SMS, publicación
   fuera de la cola normal. Los correos a socios se dejan **en borrador** en su
   Gmail (`create_draft`, **solo `htmlBody`**, sin URLs sueltas ni `tel:`; releer
   con `get_draft`). Tú no introduces credenciales en ningún sitio.
6. **Hacia fuera, inglés y tono de socio**: nadie es jefe de nadie, ningún
   plazo, «our» donde sea verdad, y siempre el techo honesto. Español solo con
   constancia de que la persona lo habla.
7. **`scratchpad/` sigue en `.gitignore`.** Nombres de clientes, direcciones,
   precios y **cualquier fila de la lista de Land Title** viven ahí o en el
   scratchpad de sesión, nunca en un commit, nunca en un documento a terceros.
8. **Ender no tiene licencia.** Ningún documento a socios menciona porcentajes
   de comisión ni operaciones concretas. Ningún contacto con un cliente o con
   un deudor sale de Ender: lo firma Natalia o Robbie.
9. **Coordinación**: otra sesión Opus 5 ejecuta PLAN (4) sobre **la misma cola y
   el mismo Buffer**. Antes de aprobar, reordenar o insertar en
   `content_pieces`/`content_publications`, avisa por el canal que usa esa
   sesión y espera confirmación. Buffer guarda **10 programados por canal y es
   una cuenta, no un calendario**: mover no libera, solo salir libera.
10. **Migrar antes de arrancar** en cada despliegue; bump de versión + changelog
    en las dos lenguas + tag + push; el `origin` del VPS es `/tmp/eko.bundle`
    (bundle → scp → `fetch` + `reset --hard origin/main` en
    `/home/enderj/Eko-AI-RealEstate`, luego `docker compose up -d --build
    frontend backend`).

**Acceso a datos, tal cual funcionó el 16-sep:**

```
# producción (solo lectura salvo que la fase diga otra cosa)
ssh ender-vps "docker exec eko-realestate-db psql -U eko -d eko_realestate -X -A -F'|' \
  -c \"SET app.current_org_id='1'; <SQL>\""
# tests de backend contra la base de pruebas eko-t3 (al día, 062)
cd backend && DATABASE_URL=postgresql+asyncpg://eko:eko@127.0.0.1:55434/eko_realestate \
  DATABASE_URL_APP=postgresql+asyncpg://eko_app:eko_app_local_pass@127.0.0.1:55434/eko_realestate \
  REDIS_URL=redis://127.0.0.1:6381/0 .venv/bin/python -m pytest -q --tb=short
# frontend
cd frontend && npx vitest run && npx tsc --noEmit
```

**Puertas que vuelven a Ender (no las cruces solo):** cada envío; el go/no-go de
la Fase 5 (lista de Land Title); la reevaluación de pago del 30-sep; cualquier
cambio de cadencia de PLAN (4).

## 🔍 Auditoría del 16-sep-2026 (19:50 Denver) — leer antes de la Fase 0

Revisión de los 17 commits del día (7 con código, 3.612 líneas añadidas),
del VPS, de YouTube, de la rutina y de la cola. Suites: backend **2050
verdes, 0 saltados**, ruff limpio (base `eko-t3`, 062); frontend **vitest
502**, `tsc` limpio. Sin secretos en lo añadido; `scratchpad/` ignorado (0
ficheros trackeados); ningún `get_bypass_session_factory` nuevo fuera de
tests; ningún `print`/`console.log`. Lo que sigue es lo que **no** está sano.

### 🔴 Bloqueante

1. **Buffer tiene una cuota DIARIA de 250 y el código no la conoce.** Sondeado
   desde el contenedor a la 01:42 UTC: `ratelimit: "100-in-15min"; r=98 …
   "250-in-1day"; r=0; t=47729`, cuerpo `window: "24h"`. Se agotó a las
   **18:14 de Denver**; desde entonces **cada tic de `publish_approved` falla**
   en `reconcile_scheduled` con `QuotaReached` («org 1 failed during a sweep»,
   cada 15 min). Vuelve a las **08:57 del 17**. Los 30 posts ya entregados
   (`external_id` puesto) los envía Buffer solo; lo que se para es la
   reconciliación y las entregas nuevas. **Causa raíz en el código:**
   `parse_rate_limit` (`buffer_publisher.py:625`) parte la cabecera por `;` y
   con dos políticas devuelve `(None, None)` — verificado —, así que el freno
   `_QUOTA_FLOOR` **nunca ha saltado**; el test (`test_the_queue_does_not_outrun_buffer.py:79`)
   solo conoce una política. El consumo de base (96 tics × reconcile+backfill)
   ya ronda los 192/día. Arreglo: leer el **mínimo `r`** entre políticas y
   añadir el fixture real; presupuestar el día.
2. **La Fase 0 no tiene hueco el jueves, y el plan cree que sí.** Al volver la
   cuota (08:57), el primer tic de `publish_approved` toma hasta **8 piezas**
   (`CONTENT_PUBLISH_MAX_PER_DAY=8`) por orden de aprobación, y **una pieza sin
   ventana cuenta como «ya»** (`buffer_publisher.py:1771-1777`, a propósito):
   **41, 43, 45 y 72** (sin ventana; 43/45 con enlace a `/calculator` **sin
   semilla**) más **24 en YouTube** (ventana abre el 19) reclaman los primeros
   huecos libres — 17, 18 y 19 — y los de Buffer que liberen 69, 46 y 16. El
   vídeo de la casa abierta llegaría a una cola llena. **Mover un post libera
   una fecha, nunca un hueco de Buffer** (`:1750-1758`): los 10 por canal solo
   bajan cuando un post sale, así que una ventana dentro del horizonte de 10
   días (`CONTENT_SCHEDULE_HORIZON_DAYS`) no retiene nada. Antes de las 08:57
   del 17, **decisión de Ender**: ventana **fuera del horizonte** para
   41/43/45/72 (p. ej. `2026-10-06`, dato reversible; PLAN (6) Fase 0),
   `needs_approval` por el estado, o dejarlas salir y mover la casa abierta; y
   el punto 5 de la Fase 0 se comprueba **justo antes** de aprobar, no la
   víspera ([[feedback_la_cola_es_un_blanco_movil]]).

### 🟠 Importante

3. **Dieciséis rastreadores con etiqueta de comentario, todos `unknown`.**
   Filas 231-246: por cada enlace que edité, dos sesiones en el mismo minuto
   desde dos ciudades distintas (Nueva York/Akron, Boston/Shallotte…), 5
   eventos, 0 scroll. `classify_publish_previews` mira ≤90 s tras la
   **publicación**; estas llegaron ≤90 s tras una **edición**. `unknown` subió
   177 → 193 en una tarde, y la consulta de la rutina del 22 (sin
   `traffic_class`) ya devuelve **`comment = 8`** sin un solo lector.
   Propuesta, que ejecuta quien Ender diga:
   `UPDATE landing_sessions SET traffic_class='automated', traffic_class_reason='link_check_after_edit 16-sep', traffic_classified_at=now() WHERE id BETWEEN 231 AND 246 AND traffic_class='unknown';`
4. **v0.109.0 se desplegó a las 17:59 de Denver** (contenedor arrancado
   23:59:02 UTC, VPS en `a22d3cc`), **fuera** de la «ventana tranquila de las
   21:00» que la nota de la Fase 3.1 fijaba, y la nota siguió diciendo «NO
   desplegada». Corregida abajo. El reinicio cayó 31 min antes de la franja
   de la 69 en Instagram (18:30): Buffer la envía igual; **verificar mañana**
   con la reconciliación ya viva.
5. **La ficha del socio (`/brief/<token>`), tres cosas pre-existentes que el
   trabajo de hoy hace más usadas:** el token no caduca ni se revoca
   (`partner_brief.py:78`, sin `expires_at`); uvicorn arranca sin
   `--no-access-log` (`Dockerfile:20`), así que la ruta con el token va al
   log del contenedor; y cada pulsación de «terminar» manda correo + Telegram
   sin tope (`public.py:1180`, `:1242`; el botón solo se bloquea mientras
   guarda). Ninguna es de hoy; anotadas para cuando se toque ese camino.
6. **La rutina del 22 está activa** (`trig_01RgALb3zNHEbhLeRwUgso1B`, 08:07
   Denver) pero su texto es del 15-sep: nombra 2 vídeos de 4, baseline 411 vs
   402, su SQL no filtra `traffic_class` (ver 3; también entran las filas
   `test` 230 y 247, que son nuestras: hoy leería **`comment = 9` con cero
   personas**) y llama centro de datos a Boydton, que el clasificador excluye
   a propósito. Lo decide Ender.
7. **`realign_windows` no comprueba que el hueco nuevo caiga DENTRO de la
   ventana.** `next_free_slot` (`buffer_publisher.py:951-980`) camina hacia
   delante hasta 370 días y en `:1646-1649` solo se descarta «el mismo hueco».
   Con la ventana llena — justo el estado que motivó el arreglo — el post se
   mueve **más allá de `publish_window_end`** y se queda ahí (el tic siguiente
   recalcula el mismo hueco y hace `continue`). Ningún test afirma `<= end`
   (`test_the_window_moved_after_the_post_was_queued.py:173` solo `>= opens`).
   Latente hoy: 42 y 44 se movieron bien. Arreglo: comparar la fecha local del
   hueco con `start`/`end` antes del `editPost`, y un test con la ventana llena.
8. **El carril calculado ya produce y su enlace es la portada.** Desde las
   11:01 (`CONTENT_CALCULATED_EVERY=2`) cada pieza calculada promete una cifra
   y su caption termina con `CONTENT_CTA_URL` a secas (`content_writer.py:294-296`;
   en producción `https://www.denverhomestory.com`): ni `/calculator` ni
   `rent=`/`savings=`. Es la omisión que la Fase 4 planifica, pero el carril
   está vivo antes que la Fase 4. Hasta arreglarlo, revisar el enlace de cada
   pieza calculada **antes de aprobarla**.

### 🟡 Menor

7. `sitemap.xml` lista `/start` y `/start` declara `robots: { index: false }`
   (`frontend/app/start/page.tsx:17`): contradicción, no riesgo.
8. `next lint`: dos avisos nuevos en `brief/[token]/page.tsx:439,441`
   (`useMemo` deps).
9. La Fase 1.3 decía `utm_content=p<id>`; el backend asocia por
   `piece-<id>` (`landing_analytics.py:458`) y así están los enlaces.
   Corregido en el texto.
10. Tres ramas con commits que `main` no tiene: `fix/la-puerta-de-la-marca`
    (5, del 3-4 sep, incluye un `fix(worker)`), `feature/google-signin` (1,
    mayo), `fix/voz-promesa-sin-respaldo` (1, 24-ago). Fusionar o borrar;
    ninguna toca lo de hoy.
11. `content_publications` conserva una fila `failed` de la pieza 14 en
    Instagram (8-sep, «post no longer exists in Buffer») con la pieza
    `published`: residuo.
12. `CONTENT_CALCULATED_EVERY` no está en el `.env` del VPS: corre con el
    default 2 del compose, que es el valor querido. Solo una pieza generada
    desde el despliegue (la 74, prosa): el carril calculado **aún no ha
    producido nada en producción**.
13. El primer GET de una ficha estampa `opened_at` y llama a Telegram
    (`public.py:1132-1147`): una vista previa de enlace puede marcarla abierta.
14. Ningún test cubre el cableado `publish_approved → realign_windows`: los
    8 tests nuevos llaman a `realign_windows` directamente; borrar la llamada
    de `:1741` deja la suite verde.
15. `frontend/lib/__tests__/bioLinks.test.ts:106-112` («no short path is
    claimed twice») compara una lista literal consigo misma; nunca lee
    `redirects()`. No puede fallar.
16. `calculator/page.tsx:260-266`: el cleanup del efecto cancela el salto de
    respaldo de 150 ms si `result` cambia en ese intervalo (tocar un preset);
    la ruta de la semilla no cae ahí.

### ✅ Verificado sano

- **Fase 4, comprobación previa hecha y POSITIVA:** `link_the_text_chose` y
  `with_platform_utm` **conservan** `rent=2600&savings=40000` (ejecutadas con
  el módulo del worktree; `_tag_site_link` solo sustituye las cuatro `utm_*`,
  `buffer_publisher.py:269-280`, y normaliza `utm_content` a `piece-<id>`).
- Calculadora: 16 constantes idénticas front/back (`calculator.ts:76-93` vs
  `calculator.py:28-45`); `build_snapshot(2600, 40000)` = 343.475.
- `lower()` de Postgres (`en_US.utf8`) baja `LuleÃ¥` a la forma que espera la
  lista y esa fila **quedó clasificada** (1 de las 21).

- VPS en `a22d3cc`; `/health` 0.109.0 en local y por Cloudflare; alembic 062
  head; 4 contenedores arriba. `origin/main` = `3cd6175` (3 commits de
  `PLAN.md` por delante, solo docs).
- Clasificador: bajo RLS por organización, cada 300 s, solo sobre
  `unknown`, SQL parametrizado; **21** marcados en el primer tic.
- `/calculator?rent=2600&savings=40000` → **$343.000** en escritorio y en
  390 px (desplaza hasta la cifra, `scrollY` 979). Mi visita con `eko_qa=1`
  quedó `test/persistent_qa` (fila 247).
- Sitemap servido = las 5 rutas públicas, sin `/brief`; `robots.txt` correcto;
  `/n` `/r` `/e` → 307 con su `utm_content`.
- Las 5 descripciones de YouTube siguen con la semilla (leídas del
  `shortDescription` público a las 19:30).

## Contexto medido — 16-sep-2026, producción, con su fuente

| hecho | valor | de dónde sale |
|---|---|---|
| Alcance registrado | YouTube 4.935 · TikTok 3.751 · **Instagram sin medir** (una sola lectura manual) | `content_metrics` última lectura por publicación; vidIQ `channel_stats` @denverhomestory = 4.775/24 vídeos/**4 suscriptores**, todo entre el 13 y el 16-sep |
| Sesiones en la página | **212** | `landing_sessions` |
| … con scroll > 0 | 73 | ídem, `max_scroll_pct>0` |
| … formularios enviados / leads | **0 / 0**, nunca | `form_submitted_at`, `lead_id` |
| TikTok → página | **0 sesiones** | `utm_source='tiktok'` = 0; `in_app='tiktok'` = 0 en 212; el detector sí reconoce `bytedancewebview\|musical_ly\|tiktok` (`landing_analytics.py::_IN_APP`) |
| Por qué | bio de TikTok = **texto plano**, 9 seguidores | perfil público leído en Chrome; `/tt` → 307 → `/start?utm_source=tiktok&utm_medium=bio` → 200 (la ruta funciona) |
| YouTube → página | 28 sesiones; **23 con un solo evento y 0 % scroll, en navegador normal** | `in_app IS NULL AND source='youtube'`, bucket `event_count=1` |
| A dónde aterrizan | piezas 47-57 → `/calculator`; piezas 3-14, 19, 68 → `/` (portada); 18 → `/fall` | `content_pieces.caption` regexp `denverhomestory\.com[^ ]*` |
| `/calculator` lee `?rent=` | **no** — ningún `searchParams` en `frontend/app/calculator` ni `lib/calculator*` | grep del 16-sep |
| Google orgánico | 11 sesiones, 9 con scroll ≥ 50 %, 2 de los 5 toques de CTA del sitio | `referrer_host='google.com' AND utm_source IS NULL` |
| … pero | todas de Denver/Wheat Ridge, **4 huellas de dispositivo**, anteriores a `?eko_qa=1` | `browser,os,screen_w` → 4 combos. **No se puede afirmar que sean extraños.** El 8-sep se midió la misma forma (3 sesiones, 83 %) |
| Facebook 11-sep | 26 sesiones, 9 con scroll ≥ 50 %, ciudades reales del metro | `source='facebook'` por día. **Nadie sabe quién compartió.** |
| Instrumento | **197 de 212 = `unknown`**; 6 IPs de centros de datos de Facebook (Forest City, Clonee, Luleå, Prineville, Boardman, Springfield) contadas como «empezó el formulario», scroll 0, 38-41 eventos | `traffic_class`; `form_started_at IS NOT NULL` |
| Formato | local (18, 21): 1.081 vistas, **16 comentarios**; calculadora (51-57): ~5.600 vistas, 5 comentarios | `content_metrics`. **n = 2 piezas locales, y sus vistas de IG no están.** Dirección sólida; multiplicador blando: «aproximadamente un orden de magnitud, sobre dos piezas» |
| Cola próximos 10 días | 18-sep **vacío en los tres canales**; 19-sep solo IG (24); luego 33, 40, 25, 26, 27, 42, 44 | `content_publications` `status='scheduled'` por día y canal |
| Google Business | **no existe**; al buscar «Denver Home Story» sale el panel de **Story Home Group** (otra correduría, 4,9★/174) | búsqueda en Chrome 16-sep |
| SEO básico | `sitemap.xml` → 404; `robots.txt` no bloquea nada; Google indexa `/` y `/fall` | curl + `site:` |
| Instagram | 15 seguidores, 21 posts, **enlace de bio pulsable** a `/ig` | vidIQ `ig_profile` |
| Clara | la agente de voz que contesta llamadas (`webhooks/voice.py`, `lead_notify.py`) | código |
| PDF | **no hay generador** en el repo; `pypdf` solo lee | `pip list`, grep |
| Cartas | **un solo cuerpo escrito** (Andrew, #3); datos de calle y mes para los 7 en `scratchpad/cartas-a-los-siete.md` | conteo de «Dear» = 1 |
| Land Title | 92 avisos NED la semana del 11-sep, ~67 en el metro (Denver 23, Aurora 17, Commerce City 9, Littleton 5, Thornton 5, Arvada 3, Brighton 3, Westminster 2); 44 prestamistas; tipos C 42 / F 36 / M 8 / V 6 | `ned.xlsx` del correo de Robbie `1a09373c79eb0a71`, leído en scratchpad de sesión, **sin copiar** |

## Decisiones del dueño — 16-sep-2026

- **Google Business Profile: no, por ahora.** Queda el riesgo del panel ajeno.
- **TikTok → cuenta Business: sí.** Lo hace **Ender en la app** (Perfil → ☰ →
  Ajustes y privacidad → Cuenta → Cambiar a cuenta Business → Real Estate). El
  cambio no existe en la web de TikTok (comprobado en su sesión).
- **Solo orgánico.** *«Que quede anotado: si en dos semanas no vemos progreso,
  volver a hacer la evaluación de una posible inversión en publicidad»* →
  **30-sep-2026**.
- **Facebook del 11-sep: no sabe quién compartió.** Se pregunta a los socios.
- **Inventario:** existe la lista de correos de clientes pasados de Natalia
  (es suya; ella manda). No sabe si tienen Zillow/Realtor.com/Nextdoor.
- **Natalia, por correo (21:28 y 21:30 UTC):** sí al vídeo del sábado; sí a
  las seis cartas. No contestó los nombres ni el #6.
- **p2 queda fuera de las cartas** (su tecla manda sobre su texto).

## Fases

### Fase 0 [CRÍTICA — sale el viernes 18] — El vídeo de la casa abierta

**Qué:** una pieza de 20-30 s, 1080×1920, para los tres canales, sobre
**1560 S Quebec Way #56, Denver — sábado 19 de septiembre, 11:00-14:00**.

**El bloqueo que nadie ha nombrado: las fotos.** Natalia dijo sí y no adjuntó
nada. Ender no tiene REcolorado; Redfin es exposición IDX, no fuente. **La
petición ya salió**: Ender le escribió el 16-sep a las 22:31 UTC (16:31 Denver)
en el hilo `1a0abf3fa082dbe8`, mensaje `1a0ac58634929941`, pidiéndole 6-8 fotos
adjuntas a una respuesta. **No se le vuelve a pedir**; lo que toca es mirar el
hilo con `get_thread` (nunca `in:sent`) y descargar los adjuntos cuando
lleguen. Si las fotos llegan el jueves por la mañana, sale el 18; si llegan el
jueves por la tarde, sale el 19 en YouTube y TikTok (el 19 solo tiene Instagram
ocupado). Si no llegan el jueves, **no se publica nada** y se le dice a Ender.

**Cómo:**
1. Espera las fotos. Guárdalas en el scratchpad de sesión, nunca en el repo.
2. Monta el vídeo **fuera del generador**: Ken Burns suave sobre 6-8 fotos, un
   solo texto estático por plano, **sin voz sintética**, piano
   `worker/assets/bgm/01-piano.mp3` (licencia Pixabay, en el repo). Herramienta a
   tu criterio (ffmpeg es suficiente). En pantalla, obligatorio:
   - «Open House · Saturday Sept 19 · 11 AM – 2 PM»
   - «1560 S Quebec Way #56, Denver»
   - «Natalia Kanonerova · Engel & Völkers Aspen» — Regla 6.10.A.4, nombre de
     la correduría claro y conspicuo.
   - «Each office independently owned and operated» — 6.10.A.6.a.
   - El teléfono que contesta Clara (léelo de `agent_settings`, no de memoria).
3. **`kind`:** son fotos reales sin narración sintética → `kind=RECORDED` con
   `media_path` puesto (así el renderizador no la reclama, y `isAiGenerated`
   va en `false`, que es verdad). Antes, **lee el enum `ContentKind`**: si
   existe un valor más honesto para «montaje de fotos reales», úsalo. Nunca
   `GENERATED` para fotos reales, nunca `RECORDED` para material de fal.ai.
4. Alta sin panel, como documenta `project_eko_realtors_cola_publicacion`:
   script en `eko-realestate-backend` (`PYTHONPATH=/app`, sesión de bypass,
   `org_id=1` explícito, `advance()` por transición, `find_violations` antes).
   `publish_window_start = 2026-09-18`, `publish_window_end = 2026-09-19`.
   Caption en inglés con el enlace **corto y medible** de la Fase 1 si ya
   existe; si no, `denverhomestory.com/start`.
5. **Antes de aprobar**, verifica con una consulta que el 18 sigue vacío en
   los tres canales y que Buffer tiene < 10 programados por canal (46 y 69
   salen el 16, 16 el 17 → 7-8 el jueves). Avisa a la sesión de PLAN (4).
   🔴 **Corregido el 16-sep (auditoría, punto 2):** esa aritmética ignoraba
   que el primer tic tras volver la cuota entrega las piezas **sin ventana**
   (41, 43, 45, 72) y rellena los 10. Sin la retención de **PLAN (6) Fase 0**
   no hay hueco el jueves; la comprobación se hace **justo antes** de aprobar.
6. Aprueba. El tick de `publish_approved` la programa en los tres canales (es lo
   que el correo prometió: **sin exclusiones manuales**). Verifica `dueAt` en
   Buffer, no solo la fila.
7. **Los comentaristas de Colorado**: responde a mano (Ender, no tú) a los seis
   que escribieron «Fall» en TikTok con la casa abierta — información útil, no
   anuncio. Deja el texto listo en el scratchpad.

**Verificación:** la pieza sale en los tres canales el 18 (o 19); `external_url`
rellenado por `backfill_links`; una sesión con `utm_source` de cada canal
llega el sábado antes de las 11.

### Fase 1 — Las puertas y el aterrizaje (esta semana)

> ✅ **DESPLEGADA el 16-sep a las 17:13 de Denver — v0.108.0, commit `a3a6920`.**
> Puntos 2, 4 y 5 hechos y verificados a través de Cloudflare. El punto 3 quedó
> **sin objeto**: las once piezas 47-57 están *todas* `published`, ninguna
> programada, así que no hay nada que editar por Buffer. El punto 1 sigue en el
> tejado de Ender ↓.
>
> **TikTok: la cuenta ya es Business y el enlace SIGUE sin ser pulsable.** Leído
> del perfil público el 16-sep: la URL vive dentro de `<h2 data-e2e="user-bio">`
> como **texto**, y no existe ningún elemento `user-link`. El enlace pulsable lo
> pinta el campo **Website** de «Editar perfil», que está vacío: la URL se
> escribió en el texto de la bio. Es lo que anticipaba el punto 1.
>
> **Avería encontrada de camino, ya corregida:**
> `scrollIntoView({behavior:"smooth"})` **no hace nada y no lo dice** en un
> navegador con el desplazamiento suave apagado. Medido en producción, Chrome
> 152, `prefers-reduced-motion` en **falso**: `smooth` dejaba `scrollY` en 0 y
> `auto` lo movía 954px. Ahí **todo v0.102.8 era inerte**. No es la mayoría de
> visitantes, pero sí **el navegador desde el que verificamos**.

1. **TikTok — CERRADO el 16-sep. No reabrir como si fuera un olvido.**

   La cuenta **ya es Business** y el enlace **sigue sin ser pulsable**: leído
   del perfil público, la URL vive dentro de `<h2 data-e2e="user-bio">` como
   texto y no existe ningún elemento `user-link`. TikTok ahora pide
   **«Become a Verified Business Account»**, que exige documentación legal de
   empresa, o **1.000 seguidores**. Hay 9.

   **Decisión del dueño, 16-sep:** no registrar la empresa en el IRS hasta que
   haya ingresos. Es la decisión correcta y está medida, no es una corazonada:

   | vía | exige | compra |
   |---|---|---|
   | verificar empresa | registro IRS | **2 sesiones en 3 semanas** |
   | 1.000 seguidores | tiene 9 | proyecto aparte |
   | texto sin pulsar | ya puesto | **3.751 visionados → 0 sesiones** |

   Las «2 sesiones en 3 semanas» no son una estimación: es lo que ha producido
   el enlace de bio de **Instagram**, que **sí** es pulsable, en una cuenta del
   mismo tamaño (15 seguidores, 21 posts). `utm_medium='bio'`: instagram 2,
   youtube 4. Ese es el techo real de un enlace de bio aquí.

   **Consecuencia para el contenido:** TikTok es el **segundo canal por
   alcance** y no es un canal de captación. La llamada a la acción que funciona
   ahí sin enlace es **el teléfono de Clara** (`agent_settings.agency_phone`),
   no un dominio que nadie teclea. Ponerlo en pantalla; quitar la URL de las
   piezas de TikTok cuando se revise el formato en la Fase 4.

   Se vuelve a mirar el **30-sep** junto con el resto, no antes.
2. **`/calculator?rent=2600`**: que la página lea `rent` (y `savings` si el
   vídeo lo nombra) de la URL y muestre el resultado **ya calculado** al
   cargar, sin pedir nada. Un vídeo que promete un número tiene que aterrizar
   en el número. Regla de la casa: la cifra sale de la calculadora con los
   mismos supuestos (`docs/content/calculator-consistency.md`). Test de
   `resultInView` sigue valiendo: el resultado tiene que estar en pantalla.
3. **Captions de las piezas 47-57**: reescribir el enlace a
   `denverhomestory.com/calculator?rent=<la renta del vídeo>&utm_source=youtube&utm_medium=social&utm_content=piece-<id>`
   (`piece-<id>`, no `p<id>`: es la forma que el backend asocia,
   `landing_analytics.py:458`).
   ✅ **Hecho el 16-sep para las piezas 47-51.** Seis enlaces en total (la 48
   lleva dos, uno con `utm_medium=comment`), editados conduciendo Chrome sobre
   YouTube Studio — no por Buffer: las cinco están `published`, y vidIQ rechaza
   el canal `UC9wpgdqHHpGRTqF5pSR7wgA` por no estar autorizado.
   Verificado **leyendo el `shortDescription` de las cinco páginas públicas**,
   no el editor, que en un caso mostraba algo que el público no tenía: la 51
   llevaba el cambio hecho pero **sin guardar** en Studio, y su descripción
   pública seguía en 597 caracteres; guardarla fue lo que lo publicó.
   Las piezas 52-57 quedan como estaban: nombran la renta en el título pero no
   el ahorro, y la calculadora necesita los dos campos para dar un número.
   Se revisan con el texto entero en la Fase 4.
   No toques TikTok/IG: la caption no enlaza.
4. **Enlaces cortos por persona que comparte**: `/n` (Natalia), `/r` (Robbie),
   `/e` (Ender) → `/start?utm_source=partner&utm_medium=share&utm_content=<letra>`.
   Mismo patrón que `/tt`, `/ig`. Así la próxima vez que alguien comparta en
   Facebook se sabe quién. Se les da en el correo de la Fase 2.
5. **`sitemap.xml`**: generar con `/`, `/start`, `/calculator`, `/fall`,
   `/contact`, `/guides` y lo que exista público. Es media hora y hoy da 404.

### Fase 2 — Las seis cartas, siete PDF y el sobre (esta semana, tras la Fase 0)

Natalia: *«I like it. Let's get the other letters ready»*. Está pidiendo.

1. **Generar las seis** a partir de la plantilla y la tabla de
   `scratchpad/cartas-a-los-siete.md` (calle + mes + saludo por persona; versión
   A para #4, #5, #6, #8; versión B para #7, #9). **#6 con el saludo en blanco**
   — se lo preguntamos, no lo adivinamos. Firma de Natalia literal, las dos
   líneas de pie (6.10.A.6.a + NAR Art. 16). «We closed on the house on…»,
   nunca «I sold you».
2. **Renderizador de PDF** — no existe. A tu criterio: plantilla HTML + Playwright
   `page.pdf()` (ya hay Playwright en el proyecto) o `reportlab`. Una carta por
   página, carta US Letter, márgenes de impresión, y **una hoja aparte con las
   siete direcciones** para los sobres. Los PDF van a `scratchpad/cartas/`,
   nunca al repo.
3. **Correo de entrega — en borrador**, respuesta al hilo `1a0abc83315c5be9`:
   los siete PDF adjuntos, la hoja de direcciones, y **una sola pregunta**: los
   nombres (sobre todo #6). Corto; sin repetir nada del correo anterior. Cierre
   cálido de una línea. Incluye los enlaces `/n` y `/r` con una frase: «if you
   ever share the site, this one tells us it was you».
4. **No mezcles** la Fase 5 en este correo. Una propuesta por correo.

### Fase 3 — El instrumento (esta semana, en paralelo)

> ✅ **3.1 ESCRITA, PROBADA Y DESPLEGADA — commit `d843643` + `bf576a1`,
> v0.109.0, contenedor arrancado a las 17:59 de Denver** (fuera de la ventana
> tranquila de las 21:00 que esta nota fijaba; ver auditoría, punto 4). 2050
> tests verdes, ruff limpio, 6 mutantes muertos, **sin migración**:
> `traffic_classified_at` ya existía. Primer tic en producción: 21 sesiones
> marcadas `datacenter_city`.
>
> **Se implementó `datacenter_city`. NO se implementó `one_shot_no_scroll`, y
> la razón está medida.** Esa regla habría marcado como `automated` unas **33
> sesiones del área de Denver** — Aurora, Denver, Parker, Wheat Ridge — y
> **trece dentro de la app de Facebook**, cosa que no hace ningún rastreador.
> **Lo que son no se puede zanjar**: parte somos casi seguro nosotros (antes de
> `?eko_qa=1` no había forma de distinguirnos), y parte viene del compartido
> del 11-sep. Esa incertidumbre **es** el argumento: `unknown` es la etiqueta
> honesta para una fila que nadie puede identificar, y marcarla convertiría una
> suposición en un dato. La métrica del 30-sep ya las excluye al exigir scroll
> ≥ 50 %.
>
> 🔴 **Un error mío, corregido, que conviene que quede escrito.** Reporté que
> una de las ocho sesiones que empezaron el formulario era **una persona real**
> de The Pinery. **No lo es.** La sesión 208 lleva `traffic_class = 'test'`,
> razón «playwright verificacion formulario 15-sep»: es **nuestro propio
> Playwright** de una sesión anterior. Consulté `form_started_at` sin leer
> `traffic_class`.
>
> Lo cierto: **siete de las ocho eran infraestructura y la octava éramos
> nosotros. Nadie de fuera ha tocado nunca el formulario.** El cero era cero
> antes de ir a mirar, y el plan ya lo decía bien.
>
> Es la ficha [[feedback-de-donde-sale-el-numero]] repitiéndose: el único dato
> del embudo que parecía una persona lo había escrito nuestra propia
> herramienta. **Cualquier consulta sobre el embudo filtra `traffic_class`
> antes de concluir.**
>
> 🔴 **`is_publish_preview` no tiene ni un llamador** fuera de sus tests: el
> barredor `classify_publish_previews` reimplementa la regla en SQL. Dos copias
> de la misma lógica que pueden separarse. No tocado hoy; anotado.
>
> 🔴 **Luleå está guardada como `LuleÃ¥`** (bytes `4c756c65c383c2a5`): la
> cabecera de ciudad de Cloudflare se decodifica como Latin-1. Afecta a toda
> ciudad no ASCII. Se emparejan las dos grafías; el defecto de origen sigue.
>
> ⏳ **3.2, 3.3 y 3.4 pendientes.** La 3.3 (rutina del 22-sep) la verifica Ender
> en `/routines`; yo no la toco.
>
> ℹ️ **El publicador consulta cada 15 min** (`CONTENT_PUBLISH_INTERVAL_SECONDS
> = 900`) y **duerme antes de trabajar**. Tras un reinicio, el primer tic cae
> 15 min después, así que una franja puede publicarse hasta 15 min tarde. No es
> avería: es el pulso. Tenerlo en cuenta al desplegar cerca de una franja.

Sin esto, lo que mida el sábado no vale.

1. **`classify_traffic`**: 197 de 212 quedan `unknown`. Añadir dos señales,
   ambas medidas el 16-sep:
   - **Sesión de un solo evento y 0 % scroll con `settled`** (ya existe
     `SETTLED_MINUTES`) → `automated`, razón `one_shot_no_scroll`. Control: las
     11 sesiones de Google y las 12 de Facebook con 4+ eventos no deben caer.
   - **Ciudad de centro de datos** (Boardman, Prineville, Clonee, Luleå, Forest
     City, Springfield NE, Ashburn, Council Bluffs, Altoona, The Dalles…) con
     scroll 0 → `automated`, razón `datacenter_city`. La lista en un módulo,
     con la fuente de cada ciudad comentada.
   - Reclasificar el histórico con un script idempotente (`traffic_classified_at`).
2. **Un cuadro semanal** (consulta guardada, no UI): sesiones humanas
   (`traffic_class NOT IN ('automated','test')` y scroll ≥ 50 %) por fuente, y
   formularios/llamadas. Es el número que se lee el 30-sep.
3. **La rutina del 22-sep** que mide los comentarios con enlace en YouTube:
   verificar en `/routines` que existe y está activa; no recrearla.
   🔴 **Mediría cero.** Ender confirma el 16-sep que **no ha pegado ni un solo
   comentario** en dos semanas, aunque `publish_followup` se los manda por
   Telegram con el texto ya hecho. Así que `utm_medium=comment` tiene cero
   sesiones porque no existe el comentario, no porque no funcione.
   ✅ **Resuelto el 16-sep, conduciendo Chrome.** Y la premisa de arriba era
   falsa a medias: al ir a mirar, **dos comentarios sí existían** (piezas 51 y
   57, puestos el 15-sep), con el enlace **sin** `rent=`/`savings=`. Lo que no
   tenía ninguno era el *Pin* — lo que yo había leído como «fijado» era el
   hueco vacío que YouTube pinta siempre.
   Estado final, verificado **recargando cada página**, no mirando el editor:
   piezas **47 y 48** con comentario nuevo y semilla; **51** editada con la
   semilla; **57** editada sin semilla — ese vídeo no nombra renta ni ahorro y
   ponerle cifras sería inventarlas — pero se le quitó la frase *«Nothing to
   fill in to see it»*, que con un enlace vacío era falsa. **Las cuatro
   fijadas.** Los dos comentarios nuevos llevan la línea de correduría que pide
   la 6.10.A.4; el texto del generador no la tiene.
   🔴 **El prompt de la rutina quedó viejo y nadie lo ha tocado:** dice que
   solo dos vídeos tienen comentario (son cuatro: se le escapan la 47 y la 48) y
   usa 411 vistas del 15-sep para la 51, cuando la página muestra 402 — si el
   agente resta, le sale crecimiento negativo. Se arregla con
   `RemoteTrigger update`; es configuración permanente, así que lo decide Ender.
4. **Lectores de TikTok e Instagram**: siguen siendo manuales (decisión del
   dueño, aplazada). Antes del 30-sep hay que hacer **una** lectura manual de
   los dos para que el cuadro no compare YouTube con ceros.

### Fase 4 — El formato (a partir de la semana que viene)

PLAN (4) fijó 7 educativas + 3 otoño + 3 calculadora por semana. La medición
dice que las locales producen comentarios y las de calculadora vistas sin
nadie detrás. **Propuesta, que Ender decide** (cambia la cadencia de otra
sesión): 3 educativas + 5 locales/estacionales + 2 calculadora **con
`?rent=` en el enlace**. ✅ **Comprobación previa hecha el 16-sep (auditoría): `with_platform_utm` / `link_the_text_chose` conservan un `rent=`/`savings=` que ya venga en la caption** (ejecutado, no solo leído). Lo que falta es al revés: el generador **no pone** la semilla (auditoría, punto 8) y la CTA apunta a la portada. Las locales: sitios concretos, fechas concretas, una
sola promesa por post (nunca «Comment FALL» y el enlace en la misma caption).

### Fase 5 — La lista de los viernes (propuesta a los socios; **no se ejecuta sin go**)

**Qué es:** el *Weekly Foreclosure Report* de Land Title Guarantee (Jackson
Smith, `jasmith@ltgc.com`) que Robbie recibe como cliente. La lista de **Notice
of Election and Demand** — el primer paso público de la ejecución hipotecaria en
Colorado — con dirección, deudor, prestamista, importe y fecha. Registro
público. ~67 direcciones del metro **cada semana**.

**Por qué importa, dicho una vez:** es la primera lista de **alta intención**.
8.760 vistas dieron cero; aquí son 67 hogares/semana con una decisión
inmobiliaria delante, y **Natalia es CDPE** — es literalmente su certificación.

**Por qué no se ejecuta sin go:**
- Es gente en apuros. El tono lo es todo: una carta **útil** con la línea de
  tiempo de Colorado, el teléfono del asesor HUD y, si vender es una de las
  opciones, qué vale la casa. Nunca «we can save your home».
- **Colorado Foreclosure Protection Act**: regula a «foreclosure consultants» y
  «equity purchasers». La actividad ordinaria de un corredor con licencia al
  listar es la exención relevante — **eso lo confirma el bróker, no tú ni
  Ender**. No cites artículos de memoria: nadie los ha leído en esta sesión.
- Ender no tiene licencia: compila, no contacta. Firma Natalia.
- La lista es de Robbie como cliente de Land Title: uso interno, nunca
  reenviada, nunca en el repo.

**Higiene de datos, no opinión:** fuera `Y=Ind N=Bus = N` (empresas); fuera o
aparte las hipotecas inversas (Fin Am Reverse, Onity); filtro por ciudad del
metro; `Orig Loan Amt` vs `Loan Amt` orienta sobre el capital. 92 → ~67 → menos.

**Qué se propone** (correo **en borrador**, a los dos Gmail personales, la
semana que viene, **después** de que salgan el vídeo y las cartas): reutilizar
el mismo generador de cartas + PDF de la Fase 2; una carta a la semana por
dirección del metro; lo firma Natalia; el bróker ve el formato antes del
primer sobre. Y una pieza de contenido local: «What a Notice of Election and
Demand means in Colorado, and the 110 days that follow» — la página a la que
la carta puede apuntar.

### Fase 6 — 30-sep: la reevaluación

**«Progreso» es un número, no una sensación.** Con el cuadro de la Fase 3:
sesiones humanas con scroll ≥ 50 % desde redes por semana, y formularios +
llamadas a Clara. Hoy: ≈ 0 humanas desde redes, 0 formularios. Si el 30-sep
sigue en ese orden con las puertas abiertas y el sábado publicado, se reabre la
pregunta del pago con el dueño, con esos números delante.

## Fuera de alcance (anotado)

- **Google Business Profile** — el dueño dijo no. Riesgo: la búsqueda de marca
  muestra a Story Home Group.
- **Google orgánico como canal** — 11 sesiones sin resolver (4 huellas, todas
  Denver). Se vuelve a mirar el 30-sep con dos semanas de `?eko_qa=1`.
- **Lectores automáticos de TikTok/Instagram** — aplazados por el dueño.
- **Publicidad de pago** — hasta el 30-sep.
- **El «Instagram 74» del correo a Natalia** — es una nota de medición aquí,
  no una corrección a ella.
- **La estructura de cobro** — sigue pendiente y es de Ender
  (`pending_estructura_de_cobro_eko_realtors`).

## Verificación (resumen ejecutable)

```
-- Fase 0: el 18 sigue vacío y Buffer tiene sitio
SET app.current_org_id='1';
SELECT platform, count(*) FROM content_publications
 WHERE status='scheduled' AND (scheduled_at AT TIME ZONE 'America/Denver')::date='2026-09-18' GROUP BY 1;
SELECT platform, count(*) FROM content_publications WHERE status='scheduled' GROUP BY 1;  -- < 10

-- Fase 1: la puerta de TikTok existe
SELECT count(*) FROM landing_sessions WHERE utm_source='tiktok' AND created_at > '2026-09-17';

-- Fase 3: el instrumento ve personas
SELECT traffic_class, count(*) FROM landing_sessions GROUP BY 1;   -- unknown debe bajar de 197

-- Fase 6: el número del 30-sep
SELECT date_trunc('week', created_at) AS semana, source, count(*) AS humanas
  FROM landing_sessions
 WHERE coalesce(traffic_class,'') NOT IN ('automated','test') AND max_scroll_pct >= 50
 GROUP BY 1,2 ORDER BY 1,2;
```

## Ficheros que se tocan

- `frontend/app/calculator/**` — leer `?rent=`/`?savings=` y calcular al cargar.
- `frontend/next.config.js` — ahí viven `/tt`, `/ig`, `/yt` y los `/fall/N`, en
  `redirects()`, **no** en `middleware.ts`. Verificado el 16-sep: esos redirects
  ganan al 308 del middleware.
- `frontend/app/sitemap.ts` — nuevo.
- `backend/app/services/landing_analytics.py` — `classify_traffic` + módulo de
  ciudades de centro de datos; script de reclasificación en `backend/scripts/`.
- `backend/scripts/` — alta de la pieza del sábado; generador de cartas + PDF
  (salida a `scratchpad/`, nunca al repo).
- `CHANGELOG.md`, `frontend/lib/version.ts`, `backend/app/config.py` — por
  despliegue.

---

# PLAN (6) — Las correcciones de la auditoría del 16-sep

**Escrito el 16-sep-2026, 20:45 de Denver, por Fable 5.1. Ejecutor: Claude Opus 5.**
Origen: el bloque «🔍 Auditoría del 16-sep-2026» de PLAN (5), que lleva la
evidencia (fichero y línea) de cada punto; aquí se apunta a ella, no se repite.
PLAN (5) sigue vivo: el orden entre los dos está en §1.

## 0. Reglas (no negociables)

Las diez del «⛔ Para el ejecutor» de PLAN (5) aplican tal cual: Protocolo
Fable en la primera respuesta, las memorias listadas, nada de `cat`/`grep`
multi-fichero/`git diff` para contar, los contenedores prohibidos, nada se
envía sin Ender, inglés y tono de socio hacia fuera, `scratchpad/` ignorado,
Ender sin licencia, coordinación con la sesión de PLAN (4) antes de tocar la
cola, migrar antes de arrancar. Además:

- **Método.** Una fase cada vez; máx. 3 intentos por fase y al tercero parar y
  reportar con diagnóstico y dos salidas. Un commit convencional por fase; el
  bump de versión en el último commit antes de cada despliegue. **Sin
  despliegue sin que Ender lo pida en un mensaje aparte.** Subagentes: máx. 2,
  solo lectura. Advisor: al arrancar, antes de la Fase 1 (toca el carril de
  producción), tras el 2.º intento fallido de cualquier fase y al cierre.
- **«Terminado» solo con salida real:** backend `pytest -q` verde sin saltados
  (hoy 2050), `ruff` limpio; frontend `vitest`, `tsc`, `next lint`, `next
  build`; cada test nuevo visto en rojo con su mutación y el fichero
  restaurado con `md5` idéntico; diff sin secretos ni `print`/`console.log`.
- **Toda escritura en producción (base o Buffer) es una puerta:** pre-imagen
  al scratchpad de sesión, el SQL exacto a la vista, se ejecuta solo con el
  «sí» de Ender y se verifica releyendo.
- **Versiones propuestas, las confirma Ender (G6):** **0.110.0** backend
  (Fases 1-4 y 5.1), **0.111.0** backend con migración 063 (Fase 5.2-5.3),
  **0.112.0** frontend (Fase 6).
- **Ventana de despliegue:** desde las 21:00 de Denver y nunca a menos de 20
  min de una franja (08:30, 11:30, 12:30, 17:30, 18:30, 20:30): el publicador
  duerme 15 min tras reiniciar.
- **Entorno:** worktree en `main` desde `origin/main`; base de tests `eko-t3`
  (127.0.0.1:55434, en 062); los comandos de PLAN (5) «Acceso a datos».

## 1. Orden respecto a PLAN (5)

1. **PLAN (6) Fase 0 va antes que PLAN (5) Fase 0** (la casa abierta): sin la
   retención no hay hueco el jueves.
2. La release backend 0.110.0 sale en la ventana de las 21:00 cuando Ender la
   pida; si la casa abierta ya está en Buffer, el reinicio no la afecta.
3. Las Fases 4 y 7 tienen que estar antes del **22-sep a las 08:07 de Denver**
   para que la rutina no lea rastreadores.
4. La release frontend 0.112.0 es independiente.
5. El punto 5 de PLAN (5) Fase 0 ya lleva la corrección (la aritmética «7-8 el
   jueves» era falsa).

## 2. Puertas de Ender (decisiones; el ejecutor las presenta, no las cruza)

| puerta | pregunta | recomendación | cuándo |
|---|---|---|---|
| G1 | Retener 41/43/45/72 fuera de la selección hasta que la casa abierta esté en Buffer | ventana `2026-10-06 → 2026-10-31` (dato, reversible) | antes de las 08:57 del 17 |
| G2 | Clasificar las filas 231-246 como `automated` | sí, con el UPDATE de la auditoría (punto 3) | cuando quiera |
| G3 | Actualizar el texto de la rutina del 22 | sí, con el texto de la Fase 7 | antes del 22, 08:07 |
| G4 | Caducidad de las fichas de socio | 90 días para las nuevas; las vivas sin caducidad; revocación por script | Fase 5 |
| G5 | Borrar tres ramas con commits huérfanos | sí, tras leer sus 7 commits | cuando quiera |
| G6 | Versiones 0.110 / 0.111 / 0.112 | — | antes de cada bump |

## 3. Fases

### Fase 0 — Reloj: la cola antes de que vuelva la cuota (antes de las 08:57 del 17)

**Por qué esa hora.** A las 08:57 vuelve la cuota diaria de Buffer y el primer
tic de `publish_approved` entrega hasta 8 piezas por orden de aprobación
(`buffer_publisher.py:1757-1810`, `CONTENT_PUBLISH_MAX_PER_DAY=8`). Una pieza
**sin ventana** entra siempre (`:1774-1777`, a propósito) y una con ventana
entra si abre dentro de `CONTENT_SCHEDULE_HORIZON_DAYS = 10`. **Mover un post
libera una fecha, nunca un hueco de Buffer** (`:1750-1758`): los 10 por canal
solo bajan cuando un post sale. Con 41/43/45/72 entregadas (12 posts) el cupo
se rellena y la casa abierta choca con `LimitReachedError` el jueves.

**0.1 Retener (G1).** Avisar a la sesión de PLAN (4). Pre-imagen al scratchpad:
```
SET app.current_org_id='1';
SELECT id, status, publish_window_start, publish_window_end, approved_at
  FROM content_pieces WHERE id IN (41,43,45,72);
```
(el 16-sep: 41 `approved`, 43 y 45 `publishing`, 72 `approved`; ventana NULL
en las cuatro). Con el sí:
```
UPDATE content_pieces
   SET publish_window_start='2026-10-06', publish_window_end='2026-10-31', updated_at=now()
 WHERE id IN (41,43,45,72) AND org_id=1;
```
El 6-oct queda fuera del horizonte hasta el 26-sep, con la casa abierta ya
resuelta. Comprobación: reproducir la selección del tic en SQL (§4) y que
devuelva **solo la 24**. La 24 sí sale y está bien: su ventana (19-30 sep) es
la que comparte con la casa abierta, YouTube tiene dos franjas al día y el
cupo queda 8 → 9 con ella. Cuando la casa abierta esté en Buffer, Ender decide
si adelantar la ventana de las cuatro.
Alternativas descartadas: `needs_approval` por SQL salta la máquina de estados
(`advance()`); una ventana ≤ 27-sep no retiene nada.
**Si la Fase 0 llega tarde** (después del primer tic): nada en el código
libera un hueco de Buffer. Queda esperar a que salgan posts o cancelar en la
interfaz de Buffer, que es lo único que anula uno. Decirlo así.

**0.2 Verificar el barrido vivo (desde las 09:15 del 17).** `docker logs
eko-realestate-backend --since 1h` sin `QuotaReached` ni «failed during a
sweep»; en `content_publications`, 69 IG (18:30 del 16), 46 YT (20:30 del 16)
y 69 TT (08:30 del 17) en `published` con `external_url`. Si alguna sigue
`scheduled` una hora después, leer `last_error` y Buffer antes de tocar nada.

**0.3 Las 16 filas (G2).** Pre-imagen: `SELECT id, traffic_class,
traffic_class_reason FROM landing_sessions WHERE id BETWEEN 231 AND 246;`
(todas `unknown`). Con el sí, el UPDATE del punto 3 de la auditoría. Verificar:
`unknown` baja 16 y la consulta de §4 devuelve 0 para `comment`.

Commit `docs(plan): PLAN (6) Fase 0 — cola retenida y filas clasificadas`, con
las salidas pegadas bajo esta fase (ids y estados, nada personal).

### Fase 1 — Buffer: el parser ve las dos ventanas y el tic no se cae (backend)

**Advisor antes de escribir:** es el carril por el que sale cada publicación.

`backend/app/services/buffer_publisher.py`:
1. `parse_rate_limit` (`:625-643`): partir primero por `,` (una política por
   trozo) y dentro por `;`; devolver el `r` **mínimo** y el `t` de esa misma
   política. Con la cabecera real del 16-sep,
   `"100-in-15min"; r=98; t=146, "250-in-1day"; r=0; t=47729` → `(0, 47729)`.
   Un trozo ilegible → `(None, None)` como hoy. Docstring: dos ventanas, y la
   diaria es la que se agotó.
2. `_graphql` (`:646-693`), al 429: `_quota_remaining = 0` y
   `_quota_refills_at = monotonic() + int(Retry-After)` si es entero; el
   mensaje de `QuotaReached` nombra `extensions.window` del cuerpo si existe.
   Los tics siguientes paran en la comprobación previa **sin petición**.
3. `publish_approved` (`:1700`): `try/except QuotaReached` alrededor de
   `reconcile_scheduled`, `backfill_links` y `realign_windows` → **un**
   `log.warning("Buffer quota reached; skipping this tick: %s", exc)` y
   `return 0`. Hoy la excepción sube a `run_for_every_org` y se registra como
   «org 1 failed during a sweep» con traceback cada 15 min: es presupuesto,
   no una avería del inquilino.
4. **Medir antes de presupuestar.** 24 h después del despliegue, en el VPS y a
   fichero: `docker logs eko-realestate-backend --since 24h 2>&1 | grep "POST
   https://api.buffer.com" | cut -c1-13 | uniq -c`, contado con `python3`. El
   consumidor de las 250 del 16-sep **no está identificado** (el log anterior
   se perdió con el rebuild; reconcile y backfill retornan sin llamar cuando no
   hay filas). Ninguna lógica de presupuesto sin ese número.

**Tests** (`backend/tests/test_the_queue_does_not_outrun_buffer.py`):
- `test_the_daily_window_is_the_one_that_binds`: la cabecera literal →
  `(0, 47729)`; una política → como hoy; `"100-in-15min"; r=3; t=5,
  "250-in-1day"; r=200; t=10` → `(3, 5)`.
- `test_a_429_stops_the_next_request_before_it_leaves`: `httpx.AsyncClient.post`
  stubeado → 429 con `Retry-After: 100`; la segunda `_graphql` lanza
  `QuotaReached` **sin** llamar al stub (contador en 1).
- `test_a_quota_out_is_a_quiet_tick_not_an_org_failure`: `reconcile_scheduled`
  stubeado lanza `QuotaReached` → `publish_approved` devuelve 0 sin lanzar;
  `caplog` con un WARNING y ningún ERROR.
Mutaciones: quitar la partición por `,` → rojo; no fijar `_quota_refills_at`
→ rojo; quitar el `except` → rojo. Commit `fix(publisher): Buffer tiene dos
ventanas y la diaria es la que manda`.

### Fase 2 — `realign_windows`: dentro de la ventana o no se mueve (backend)

`buffer_publisher.py:1644-1690`:
1. Tras `due_at = await next_free_slot(...)` (`:1646`): `local_new =
   due_at.astimezone(zone).date()`; si `local_new < start` o (`end` y
   `local_new > end`) → `log.warning("Piece %s: no free %s slot inside its
   window %s-%s; left at %s", …)` y `continue`.
2. Tras `current = await read_scheduled_post(post_id)`: si
   `(current.get("status") or "").lower() not in _BUFFER_IN_FLIGHT` (`:115`)
   → `continue`: ya salió o Buffer lo cerró; el reconciliador lo verá.
3. Test de cableado: `publish_approved` con `read_scheduled_post` y
   `edit_scheduled_text` stubeados y una fila drifted → los dos llamados.
   Borrar la llamada de `:1741` → rojo.

Tests en `test_the_window_moved_after_the_post_was_queued.py`:
`test_a_full_window_leaves_the_post_where_it_was` (todos los huecos entre
`start` y `end` ocupados → 0 movidos, fila intacta, warning);
`test_a_post_buffer_already_sent_is_not_moved` (`status: sent` → ningún
`editPost`); `test_the_tick_realigns_before_claiming`. Mutaciones: quitar la
cota → rojo; quitar el `status` → rojo. Commit `fix(publisher): un post no
sale de su ventana por el otro lado`.

### Fase 3 — El carril calculado enlaza con la cifra (backend)

`backend/app/services/content_writer.py`:
1. `_with_cta(draft, language, cta_index, plan=None)` (`:273`): con `plan`,
   la URL es `f"{url}/calculator?rent={plan.rent}&savings={SAVINGS}"`
   (`SAVINGS` de `content_calculated.py:60`, el mismo con el que se calculó la
   cifra) y la línea es de quien alquila, no la de vender: EN «Run your own
   number — nothing to fill in to see it: {url}», ES «Haz tu propio número —
   no hay nada que rellenar para verlo: {url}». `_ask` (`:214`) le pasa
   `plan`. El orden `_with_plan` → `_with_cta` no cambia (`:162-165`).
2. La regla de la casa se cumple por construcción: la cifra del texto y la
   del enlace salen de los mismos `inputs` (`content_calculated.py:270`), y
   `find_violations` sigue viendo la caption final.

**Tests:** en `test_the_figure_the_generator_computed.py`,
`test_a_calculated_caption_lands_on_its_own_number` (la caption contiene
`calculator?rent=2600&savings=60000`) y
`test_a_prose_caption_keeps_the_selling_cta`; en `test_buffer_publisher.py`,
junto a `:1911-1924`, `test_the_seed_survives_the_utm_tagging` con
`rent=2600&savings=60000` literal (ejecutado a mano el 16-sep; falta el
fixture). Mutación: construir la URL sin `savings` → rojo.

**Las tres que ya existen (41, 43, 45), puerta dentro de G1:** verificar cada
cifra con `build_snapshot({"rent": R, "savings": 60000, "credit": "good"},
None, lang=None)["result"]["price"]` (lectura del 16-sep: 2.200 → 313k,
3.000 → 408k, 4.000 → 527k; **recalcular, no copiar**); si cuadra, editar la
caption por `PATCH /api/v1/content/{piece_id}` (`content.py:434`) o `psql`,
cambiando `denverhomestory.com/calculator` por
`denverhomestory.com/calculator?rent=R&savings=60000`; `find_violations`
después; releer. Están `pending`, no en Buffer: el enlace viaja entero con
`link_the_text_chose`. Commit `feat(content): la pieza calculada enlaza con el
número que promete`.

### Fase 4 — El clasificador ve las parejas (backend, antes del 22)

`backend/app/services/landing_analytics.py`, junto a `classify_publish_previews`
(`:424`) y con su forma: `classify_paired_link_checks(db) -> int`. Dos filas
`unknown` de la misma org con el mismo `utm_source` y `utm_content`,
`first_seen_at` a ≤ 60 s una de otra, **las dos** con
`coalesce(max_scroll_pct,0) = 0`, `cta_clicks = 0`, `tel_clicks = 0`,
`form_started_at IS NULL`, **ciudades distintas** (`city IS NOT NULL` y
`a.city <> b.city`) y las dos asentadas (`last_seen_at < now -
SETTLED_MINUTES`) → `automated`, razón `paired_link_check`. Self-join
`a.id < b.id`, `distinct`, se marcan las dos. Registrado en `_llm_monitor_loop`
(`main.py:545-550`) con su propio `try`, como las otras dos.

**La puerta de esta fase es el backtest, no el test.** Antes de escribir
código, la misma regla en SQL sobre producción (solo lectura):
```
SET app.current_org_id='1';
WITH s AS (SELECT * FROM landing_sessions WHERE traffic_class='unknown')
SELECT a.id, b.id, a.utm_content, a.city, b.city FROM s a JOIN s b
  ON a.id<b.id AND a.utm_source=b.utm_source AND a.utm_content=b.utm_content
 AND abs(extract(epoch from a.first_seen_at-b.first_seen_at))<=60
 AND coalesce(a.max_scroll_pct,0)=0 AND coalesce(b.max_scroll_pct,0)=0
 AND a.cta_clicks=0 AND b.cta_clicks=0 AND a.tel_clicks=0 AND b.tel_clicks=0
 AND a.form_started_at IS NULL AND b.form_started_at IS NULL
 AND a.city IS NOT NULL AND b.city IS NOT NULL AND a.city<>b.city
ORDER BY a.id;
```
Debe devolver **exactamente las 8 parejas 231-246** (si la 0.3 aún no corrió)
y **ninguna** fila del área de Denver ni de la app de Facebook. Si devuelve
otra cosa, la regla no se escribe: se reporta. Es la misma disciplina con la
que este repo rechazó `one_shot_no_scroll`.
Alternativas descartadas: (a) ampliar los 90 s a «tras una edición» — no hay
registro de ediciones, se hacen a mano en YouTube Studio; (b) marcar toda
sesión de YouTube con 5 eventos y 0 scroll — es `one_shot_no_scroll` con otro
nombre.

**Tests** (nuevo `test_the_pair_that_fetched_the_same_link.py`, con los
ayudantes de `test_the_datacenter_is_not_a_neighbour.py`): la pareja se marca;
una sola fila no; una pareja donde una deslizó no; una pareja de la misma
ciudad no; a 61 s no; nunca sobre `test`. Mutación: quitar `a.city<>b.city` →
rojo.

**El lado que mide:** `docs/analytics/weekly-funnel.sql` ya filtra; la
consulta de la rutina (Fase 7) pasa a filtrar. Commit `feat(api): el
clasificador ve la pareja que buscó el mismo enlace`. **Bump 0.110.0** (G6),
`CHANGELOG.md` EN/ES y `version.ts` en el último commit de la release.

**Despliegue 0.110.0** (cuando Ender lo pida; ventana 21:00; sin migración):
bundle → scp → `fetch` + `reset --hard origin/main` en
`/home/enderj/Eko-AI-RealEstate` → `docker compose up -d --build backend`;
`/health` = 0.110.0; a los 15 min ni `QuotaReached` ni «failed during a
sweep»; primer tic del monitor con `Classified N … paired` y N = lo que dijo el
backtest (0 si la 0.3 ya corrió).

### Fase 5 — La ficha del socio (backend)

**5.1 (va en 0.110.0).** `backend/app/logging_redact.py`: patrón
`_BRIEF_TOKEN_PATH = re.compile(r"(/api/v1/public/brief/)[A-Za-z0-9_-]{16,64}")`
→ `\1<redacted>` en `_PATTERNS`; el filtro ya está en `uvicorn.access`
(`:96-106`). Test en `test_log_redaction.py`: la línea de acceso `GET
/api/v1/public/brief/<43 chars> HTTP/1.1` sale redactada; `/brief/` sin token
no se toca. Commit `fix(logging): el token de la ficha no se escribe en el log
de acceso`.

**5.2 (0.111.0, migración 063).** `partner_briefs.expires_at` y `revoked_at`
(`DateTime(timezone=True)`, nullable; las filas vivas quedan NULL = sin
caducidad, nadie vivo se queda fuera). `_brief_org` (`public.py:1076`) añade
`revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())`.
`backend/scripts/create_brief.py` pone `expires_at = now + BRIEF_TTL_DAYS`
(G4, 90) y un `revoke_brief.py <id>` nuevo estampa `revoked_at`. Tests en
`test_partner_brief.py`: caducada → 404 con el mismo cuerpo; revocada → 404;
viva → 200; el de aislamiento no cambia. **Migrar antes de arrancar**
(`alembic upgrade head` → `063_partner_brief_expiry`).
**5.3 (0.111.0).** `brief_save` (`public.py:1200-1245`): si `body.notify`,
`answers` es igual a lo guardado y `answered_at` está dentro de
`BRIEF_NOTIFY_QUIET`, no llamar a `notify_finished`. Test: dos pulsaciones
idénticas → un `send_operator_telegram`. Commit `feat(brief): la ficha caduca,
se revoca y no repite el timbre`. Bump 0.111.0.
**No se toca:** el GET que estampa `opened_at` (auditoría, punto 13): cambiar
el significado de «abierta» es decisión de producto; queda anotado.

### Fase 6 — Frontend menor (0.112.0)

1. `frontend/lib/sitemap.ts`: `SITEMAP_EXCLUDED = ["/start"] as const` y
   `sitemapUrls` lo filtra; `sitemap.test.ts`: `/start` fuera, y un test de
   texto fuente que `app/start/page.tsx` contiene `index: false` (la razón).
2. `bioLinks.test.ts:106-112`: `const all = (await
   nextConfig.redirects()).map((r) => r.source)`. Mutación: duplicar `/n` en
   `next.config.js` → rojo.
3. `app/brief/[token]/page.tsx:439-441`: `people` y `rows` en su propio
   `useMemo`; `next lint` sin avisos.
4. `app/calculator/page.tsx:229-266`: el id del temporizador en un `useRef`; el
   efecto no devuelve cleanup; un efecto aparte `useEffect(() => () =>
   window.clearTimeout(ref.current), [])`. `resultInView.test.ts` sigue verde;
   test de forma: el fuente no contiene `return () => window.clearTimeout(id)`.
Criterio: `vitest` ≥ 502 + nuevos, `tsc`, `next lint` **sin avisos**, `next
build`. Bump 0.112.0. Commit `fix(frontend): sitemap sin /start, tests que
pueden fallar y el salto que no se cancela`. Despliegue: `docker compose up -d
--build frontend`; leer `sitemap.xml` **servido**.

### Fase 7 — La rutina del 22 (G3)

Con el sí, `RemoteTrigger update` sobre `trig_01RgALb3zNHEbhLeRwUgso1B`.
**Las vistas de referencia se leen de vidIQ al actualizar** (`vidiq_video_stats`
de `6hWbM1jDzIM`, `bHobGs2DkLE`, `ided3DCAv90`, `dSGptSU4dcE`), no se copian
de hoy. Cambios al prompt: cuatro vídeos con comentario **fijado** (47, 48, 51,
57; el 57 sin cifras a propósito); la consulta:
```
SELECT coalesce(utm_medium,'(ninguno)') AS medio, count(*) AS sesiones
  FROM landing_sessions
 WHERE first_seen_at >= '2026-09-16 18:35-06' AND utm_source = 'youtube'
   AND coalesce(traffic_class,'') NOT IN ('automated','test')
 GROUP BY 1 ORDER BY 2 DESC;
```
(el reloj arranca tras la última edición, 18:33 del 16); la advertencia de
ciudades pasa a «`traffic_class` ya descuenta lo identificado; Boydton no está
en nuestra lista de centros de datos»; el resto igual. Verificar con `get`:
`enabled: true`, `next_run_at` = `2026-09-22T14:07:00Z`.

### Fase 8 — Limpieza (G5)

- Ramas: `fix/la-puerta-de-la-marca` (5 commits, 3-4 sep; leer el
  `fix(worker)` `9127947` y comprobar si `main` ya lleva ese arreglo en el
  instalador del worker), `feature/google-signin` (mayo; superada por
  v0.16.0), `fix/voz-promesa-sin-respaldo` (24-ago; comprobar contra la ficha
  `feedback_una_respuesta_vacia_no_es_una_respuesta`). Con el sí: `git branch
  -D` y `git worktree remove` de los que existan. Nunca `git checkout -- .`.
- La fila `failed` de la pieza 14 (IG, 8-sep) y `CONTENT_CALCULATED_EVERY`
  ausente del `.env`: anotados, no se tocan.
- Tras cada despliegue, marcar los puntos del bloque de auditoría (✅/⏳): es
  lo que la siguiente sesión lee.

## 4. Verificación (resumen ejecutable)

```
-- Fase 0: la selección del tic solo ve la 24
SET app.current_org_id='1';
SELECT id, status, publish_window_start FROM content_pieces
 WHERE status IN ('approved','publishing') AND media_path IS NOT NULL
   AND (publish_window_start IS NULL OR publish_window_start <= current_date + 10)
 ORDER BY id;
-- Fase 0.3 / 4 / 7: lo que leerá la rutina
SELECT coalesce(utm_medium,'-') medio, count(*) FROM landing_sessions
 WHERE first_seen_at >= '2026-09-16 18:35-06' AND utm_source='youtube'
   AND coalesce(traffic_class,'') NOT IN ('automated','test') GROUP BY 1;
-- Fase 1: sin cuota no hay traceback
docker logs eko-realestate-backend --since 2h 2>&1 | grep -c "failed during a sweep"   # 0
```
Suites: backend `pytest -q` ≥ 2050 + nuevos y 0 saltados; frontend `vitest`
≥ 502 + nuevos; `tsc`; `next lint` sin avisos; `next build`. Antes de cada
despliegue, la sonda de Buffer de la ficha
`project_eko_realtors_buffer_250_al_dia` (imprime `r` de las dos ventanas,
nunca el token).

## 5. Ficheros que se tocan

- `backend/app/services/buffer_publisher.py` (F1, F2) ·
  `backend/app/services/content_writer.py` (F3) ·
  `backend/app/services/landing_analytics.py` + `backend/app/main.py` (F4) ·
  `backend/app/logging_redact.py` (F5.1) · `backend/app/models/partner_brief.py`
  + **nueva** `backend/migrations/versions/2026MMDD_HHMM_partner_brief_expiry.py`
  (063) + `backend/app/api/v1/public.py` + `backend/scripts/create_brief.py` +
  **nuevo** `backend/scripts/revoke_brief.py` (F5.2-5.3)
- Tests: `test_the_queue_does_not_outrun_buffer.py`,
  `test_the_window_moved_after_the_post_was_queued.py`,
  `test_the_figure_the_generator_computed.py`, `test_buffer_publisher.py`,
  **nuevo** `test_the_pair_that_fetched_the_same_link.py`,
  `test_log_redaction.py`, `test_partner_brief.py`
- Frontend: `lib/sitemap.ts`, `lib/__tests__/sitemap.test.ts`,
  `lib/__tests__/bioLinks.test.ts`, `app/brief/[token]/page.tsx`,
  `app/calculator/page.tsx`, `lib/__tests__/resultInView.test.ts`
- `backend/app/config.py`, `frontend/lib/version.ts`, `CHANGELOG.md`,
  `PLAN.md` — por despliegue.

## 6. Riesgos

1. La Fase 0 llega después del tic → ninguna retención por código; drenar o
   cancelar en Buffer.
2. El consumidor de las 250 del 16-sep sigue sin identificar; si es otra
   sesión con el mismo token, la Fase 1 no lo evita, solo lo hace visible.
3. La regla de parejas puede marcar a dos personas que pulsaron el mismo
   enlace en el mismo minuto sin deslizar: el backtest es la defensa, y el
   coste para el 30-sep es cero porque esa métrica ya exige scroll ≥ 50 %.
4. Migración 063 sobre una tabla pequeña; migrar antes de arrancar.
5. El test de forma del sitemap depende del texto de `start/page.tsx`; si
   cambia la metadata, el test avisa, que es lo que se quiere.

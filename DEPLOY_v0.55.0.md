# Despliegue v0.55.0 — preparado, SIN EJECUTAR

Rama `feat/estudio-visible` (`b78aba5` + `1955d0f`), subida a GitHub.
Producción está en **v0.54.4**. **Esperando autorización del dueño.**

## Lo que hace esta versión más fácil de lo normal

| | |
|---|---|
| **Migraciones nuevas** | **NINGUNA.** `git diff main...HEAD -- backend/migrations/` → 0 ficheros. Producción ya está en `042_alerted_state`, la última |
| **Variables de entorno nuevas** | **NINGUNA.** El diff de `config.py` solo toca `APP_VERSION` |
| **Cambios de esquema** | ninguno |

Es un despliegue **solo de código**. La reversión no tiene que deshacer datos,
que es lo que complicó la v0.54.4.

## Antes de tocar nada

- [ ] `curl https://inmo-demo.ekoaiautomation.com/api/v1/health` → confirmar
      `"version":"0.54.4"` (el punto de partida, para saber a qué se vuelve).
- [ ] `ssh pcrug "df -h / | tail -1"` → **por debajo del 90%**. El 24-ago el
      disco al 99% ya corrompió objetos de git una vez.
- [ ] Árbol limpio y rama subida (ya verificado: `git status` vacío).

## Orden de pasos

1. **Fusionar a `main` y etiquetar** — el tag se crea AQUÍ, no antes: etiquetar
   una rama sin fusionar deja el tag apuntando a un commit huérfano si la
   fusión no es directa.
   ```
   git checkout main && git merge --ff-only feat/estudio-visible
   git tag -a v0.55.0 -m "v0.55.0 — el Estudio de Contenido, encontrable y usable"
   git push origin main && git push origin v0.55.0
   ```
2. **Llevar el código al ROG** (bundle + `scp` a `pcrug`, `git fetch` +
   `merge --ff-only`), como en la v0.54.4.
3. **Construir**: `docker compose build backend frontend`.
   Comprobar que la imagen lleva la versión: debe decir `0.55.0`.
4. **NO hay `alembic upgrade`.** No hay migraciones. Si alguien lo ejecuta por
   costumbre, es un no-op inofensivo.
5. **Levantar**: `docker compose up -d backend frontend`.
   ⚠️ Si el clasificador bloquea `up -d`, pedírselo al dueño con el prefijo `!`.

## Verificación posterior (romperlo, no mirarlo)

- [ ] `/api/v1/health` → `"version":"0.55.0"` y `llm_fallback:"ok"`.
- [ ] **Menú**: aparece «Contenido»; a 375 px está en el tab-bar inferior.
- [ ] **Ajustes**: el campo «Identificación de la brokerage» existe.
      **Escribir `Engel & Völkers Aspen`** — confirmado por el dueño el 26-ago;
      es el texto de la firma de Natalia y el único de los tres candidatos que
      cabe en el ancho del vídeo. Guardar, recargar, y comprobar **en Postgres**
      que persistió, no en pantalla.
- [ ] **Validar el instrumento**: en `/content`, la causa «no hay identificación
      de la brokerage» debe **desaparecer** tras el paso anterior. Si no
      desaparece, el diagnóstico es decoración y hay que investigar.
- [ ] **Subir un clip corto de verdad** desde el móvil → aparece en Borradores
      con reproductor. Y un fichero que no sea vídeo → **415 nombrando los
      formatos**, sin dejar huérfanos en el volumen.
- [ ] **Regresión del Inbox**: abrir el desplegable de Inbox en escritorio y
      comprobar que se ve entero. Se rompió durante la Fase 2 por un
      `overflow-x` y no se ve en ningún test.
- [ ] **«Hoy»** sigue mostrando la consola de llamadas.
- [ ] Y lo que NO debe cambiar: **`CONTENT_STUDIO_ENABLED` y
      `CONTENT_RENDER_ENABLED` siguen en `false`.** Esta versión no enciende
      nada; hace visible y usable lo que ya existía.

## Reversión

Sin datos que deshacer, así que es volver el código:

```
git checkout v0.54.4        # en el ROG
docker compose build backend frontend
docker compose up -d backend frontend
```

**No hay `alembic downgrade`**: no se aplicó ninguna migración. Un valor escrito
en `brokerage_line` sobrevive a la reversión, y no molesta: la v0.54.4 lo lee
igual (la columna existe desde la 037), simplemente no tiene campo para editarlo.

Verificar tras revertir: `/api/v1/health` → `"version":"0.54.4"`.

## Riesgo residual, dicho en voz alta

- **Cloudflare puede cortar el cuerpo de la petición muy por debajo de 500 MB**
  en planes no-Enterprise, y el dashboard va por túnel. Si pasa, la usuaria ve
  el 413 del proxy. No está verificado contra el plan real: **compruébalo antes
  de prometerle 500 MB a Natalia**. Un clip corto de móvil (decenas de MB) no
  debería acercarse.
- El nav de escritorio no cabe entre 768 y 1279 px. Preexistente y 20 px mejor
  que antes de esta rama, pero sigue ahí.

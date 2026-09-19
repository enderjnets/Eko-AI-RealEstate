#!/usr/bin/env bash
# Copia nocturna de la base de Eko AI Realtors (formato personalizado), con
# retención.
#
# Corre EN EL VPS, donde vive producción desde la mudanza del 27-ago-2026:
#   crontab -e →  15 4 * * *  /home/enderj/Eko-AI-RealEstate/deploy/backup-db.sh >> /home/enderj/eko-realtors-backup.log 2>&1
#
# Por qué existe: hasta el 27-ago-2026 este producto no tenía copia de ninguna
# clase. Ni en el ROG (timeshift excluye `/var/lib/docker/*` por una regla
# interna que `timeshift.json` no puede sobrescribir — medido en el propio
# `exclude.list` de la instantánea), ni en el VPS. 38 leads y 72 mensajes de
# clientes reales de una correduría con licencia vivían en un único volumen sin
# segunda copia.
#
# ── RESTAURAR (el orden importa, y el paso 2 es el que se salta todo el mundo) ─
#   1. Levantar un postgres:16-alpine vacío y crear la base.
#   2. Aplicar el fichero de ROLES PRIMERO, y darle contraseña a eko_app:
#        psql -U eko -d postgres -f eko-roles-<marca>.sql
#        psql -U eko -d postgres -c "ALTER ROLE eko_app WITH PASSWORD '<nueva>'"
#      Saltárselo restaura todas las filas y NINGUNA de las políticas de
#      aislamiento, y nada avisa: pg_restore imprime los errores y sale 0.
#   3. pg_restore -U eko -d eko_realestate --no-owner eko-realtors-<marca>.dump
#   4. Esa misma contraseña va en DATABASE_URL_APP del `.env`.
#   5. Comprobar con recuentos de filas Y con una prueba de inquilino — que una
#      sesión atada a una organización no vea los leads de otra —, no solo con
#      que la aplicación arranque.
#
# ── Qué cambió el 18-sep-2026, y por qué no era una manía ─────────────────────
#
# Este guion ya verificaba antes de rotar, tenía suelo de tamaño y aparcaba los
# volcados malos: de los tres del VPS, era con diferencia el mejor. Pero
# compartía con los otros dos el agujero de fondo: `docker exec ... pg_dump >
# "$OUT"` escribía sobre el NOMBRE DEFINITIVO. El `>` crea el fichero antes de
# que pg_dump diga una palabra, así que un volcado que muere a la mitad deja un
# `.dump` truncado con la fecha de hoy. `set -e` aborta el guion, sí — pero el
# fichero se queda, con nombre de copia buena, y `_usable` no llegó a mirarlo.
# A la noche siguiente la retención lo cuenta como una de las catorce y el Mac
# se lo lleva como la más nueva.
#
# Ahora el nombre definitivo se lo gana al final. Y tres cosas más, medidas en
# el guion gemelo de Zorros:
#
#   - **`docker exec` se bebe la entrada estándar.** Llamado desde otro guion
#     que llega por una tubería (`ssh vps 'bash -s' < guion.sh`), lo que se bebe
#     es el resto del guion que lo llamó. Cada `docker exec` lleva `< /dev/null`.
#   - **Verificar sobre un flujo da falsos negativos.** `pg_restore -l < "$f"`
#     lee una tubería; `pg_restore` quiere un fichero con posición. Ahora el
#     volcado se hace y se verifica DENTRO del contenedor, sobre un fichero.
#   - **`printf ... | grep -q` bajo `pipefail` MIENTE**: grep sale al encontrar
#     la coincidencia, printf muere con SIGPIPE y pipefail devuelve ese fallo
#     aunque la tabla estuviera. Se comprueba con `case`.
#
# Y el volcado y sus roles se promueven JUNTOS, al final. Antes, si el
# `pg_dumpall` fallaba, el `.dump` ya tenía nombre bueno y quedaba una copia sin
# sus roles: restaurable en filas, y sin una sola política de aislamiento. Media
# copia es peor que ninguna, porque parece entera.
set -euo pipefail

CONTAINER="${EKO_DB_CONTAINER:-eko-realestate-db}"
DB_USER="${POSTGRES_USER:-eko}"
DB_NAME="${POSTGRES_DB:-eko_realestate}"
OUT_DIR="${EKO_BACKUP_DIR:-$HOME/eko-realtors-backups}"
KEEP="${EKO_BACKUP_KEEP:-14}"

# Un volcado por debajo de esto no es una base pequeña, es un volcado roto. El
# real anda por 112 KB; uno válido pero solo-esquema, por 30 KB. El suelo está
# deliberadamente muy por debajo del tamaño real para que una base que encoge de
# verdad (una purga, un cliente que se va) no lo dispare: esto atrapa «el
# contenedor arrancó sobre un volumen vacío», no vigila el tamaño.
MIN_BYTES="${EKO_BACKUP_MIN_BYTES:-20000}"

# Las tablas sin las cuales esto no sirve de nada: los leads son el producto,
# las propiedades y las organizaciones son de quién es cada cosa, y las cuentas
# son quién entra. Si el índice no las nombra, el volcado es de otra base.
MUST_HAVE="${EKO_BACKUP_TABLES:-leads properties organizations accounts}"

say() { echo "$(date -Is) $*"; }

# Este volcado lleva los clientes de las agencias, sus direcciones y sus
# operaciones. Iba en claro mientras sus hermanos (estado, repos) sí se cifraban,
# y el disco del VPS no está cifrado: cualquiera con una instantánea del volumen
# leía la cartera entera. Misma frase que todo el sistema de copias, para que una
# restauración de emergencia siga necesitando UNA sola.
KEYFILE="${EKO_BACKUP_KEYFILE:-$HOME/.config/vps-backup.key}"

# Sin frase no hay copia. Un aviso en lugar de una parada sería volver a escribir
# los datos en claro la primera noche que falte el fichero, sin que nadie se entere.
[ -r "$KEYFILE" ] || { say "ABORTADO: no hay frase de cifrado en $KEYFILE"; exit 1; }

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# El temporal lleva PID además de la marca: la marca tiene resolución de
# segundo y dos corridas del mismo segundo se pisarían.
UNIQ="$STAMP-$$"
TMP_DUMP="$OUT_DIR/.eko-realtors-$UNIQ.part"
TMP_ROLES="$OUT_DIR/.eko-roles-$UNIQ.part"
TMP_CIF="$OUT_DIR/.eko-realtors-$UNIQ.part.gpg"
OUT="$OUT_DIR/eko-realtors-$STAMP.dump.gpg"
ROLES="$OUT_DIR/eko-roles-$STAMP.sql"
IN_BOX="/tmp/eko-backup-$UNIQ.dump"

limpiar() {
  rm -f "$TMP_DUMP" "$TMP_ROLES" "$TMP_CIF"
  docker exec "$CONTAINER" rm -f "$IN_BOX" < /dev/null > /dev/null 2>&1 || true
}
trap limpiar EXIT

# ── el volcado, dentro del contenedor ────────────────────────────────────────
docker exec "$CONTAINER" sh -c "pg_dump -U $DB_USER -Fc $DB_NAME > $IN_BOX" < /dev/null

# (1) ¿se puede leer el índice? Si no, no es restaurable.
TOC="$(docker exec "$CONTAINER" pg_restore --list "$IN_BOX" < /dev/null)"

# (2) ¿trae el producto? Un volcado de una base vacía supera el paso anterior.
for tbl in $MUST_HAVE; do
  case "$TOC" in
    *"TABLE DATA public $tbl "*) ;;
    *)
      say "ABORTADO: el volcado no contiene la tabla '$tbl' — no se promueve"
      exit 1
      ;;
  esac
done

docker cp "$CONTAINER:$IN_BOX" "$TMP_DUMP" > /dev/null
SIZE="$(wc -c < "$TMP_DUMP" | tr -d ' ')"
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
  # El malo se aparca, no se borra: es la prueba de qué salió mal. Y se aparca
  # con un nombre que NO casa con ningún patrón de copia buena, así que ni la
  # retención ni el Mac lo confunden con una.
  # Se cifra también: «rechazado» significa ilegible o corto, que no es lo mismo
  # que vacío — puede llevar filas de clientes de verdad.
  gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$KEYFILE" \
      -o "$OUT_DIR/eko-realtors-$STAMP.rechazado.gpg" "$TMP_DUMP" 2>/dev/null || true
  rm -f "$TMP_DUMP"
  say "ABORTADO: el volcado pesa $SIZE bytes, por debajo del suelo de $MIN_BYTES — aparcado, y la retención NO corre"
  exit 1
fi

# ── los roles, que el volcado de datos NO contiene ───────────────────────────
#
# Medido, no supuesto: restaurar este volcado en un clúster limpio produce
# exactamente 36 errores, y los 36 son `role "eko_app" does not exist`. El
# volcado lleva 49 entradas POLICY/ACL —todas las políticas de aislamiento entre
# agencias están ahí dentro— pero una política que nombra un rol que Postgres
# nunca ha oído no se puede aplicar. `pg_dump` de una base es de ámbito base;
# los roles son de ámbito clúster y viven en `pg_dumpall`. Sin este fichero, una
# recuperación a las 3 de la mañana restaura las filas y pierde en silencio el
# aislamiento entre agencias, que es lo único que este esquema no puede perder.
#
# `--no-role-passwords` a propósito: esto escribe nombres, atributos y
# pertenencias, NO los hashes. La recuperación crea `eko_app` con una contraseña
# nueva y la pone en DATABASE_URL_APP — un fichero de copia es el sitio
# equivocado para guardar credenciales que ya están en el `.env`.
docker exec "$CONTAINER" pg_dumpall -U "$DB_USER" --roles-only --no-role-passwords < /dev/null > "$TMP_ROLES"
if ! grep -q 'CREATE ROLE eko_app' "$TMP_ROLES"; then
  say "ABORTADO: el fichero de roles no define eko_app — una restauración de este juego volvería sin RLS"
  exit 1
fi

# ── promover los dos JUNTOS ──────────────────────────────────────────────────
# Hasta aquí no existe ningún fichero con nombre de copia buena. Los dos se
# ganan el nombre a la vez, porque para restaurar Eko hacen falta los dos y una
# pareja descabalada se lee desde fuera como una copia entera.
# Cifrar, y comprobar que el descifrado vuelve a ser el original byte a byte. Un
# gpg que sale con cero dice que escribió un fichero, no que ese fichero se pueda
# volver a abrir — y una copia que no abre se ve idéntica a una buena hasta el
# día que hace falta.
gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-file "$KEYFILE" -o "$TMP_CIF" "$TMP_DUMP"
if [ "$(sha256sum "$TMP_DUMP" | cut -d' ' -f1)" != \
     "$(gpg --batch --quiet --decrypt --passphrase-file "$KEYFILE" "$TMP_CIF" 2>/dev/null | sha256sum | cut -d' ' -f1)" ]; then
  say "ABORTADO: el volcado cifrado no vuelve a ser el original — no se promueve"
  exit 1
fi
rm -f "$TMP_DUMP"

# El fichero de roles NO se cifra, y es deliberado: se escribe con
# `--no-role-passwords`, así que lleva nombres, atributos y pertenencias y
# ninguna credencial. Comprobado sobre el fichero vivo: cero líneas con
# PASSWORD. Cifrarlo solo añadiría una frase más que recordar a las 3 de la
# mañana sin proteger nada.

mv "$TMP_CIF" "$OUT"
chmod 600 "$OUT"
mv "$TMP_ROLES" "$ROLES"

TABLAS="$(printf '%s\n' "$TOC" | grep -c 'TABLE DATA' || true)"
say "escrito $OUT ($(du -h "$OUT" | cut -f1)), $TABLAS tablas con datos"
say "escrito $ROLES ($(wc -l < "$ROLES" | tr -d ' ') líneas)"

# Retención: solo sobre ficheros ya verificados. Ni los `.part` ni los
# `.rechazado` casan con estos patrones, así que una racha de fallos no puede
# rotar fuera a la última copia buena — solo acumula pruebas hasta que alguien
# mire.
ls -1t "$OUT_DIR"/eko-realtors-*.dump.gpg 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$OUT_DIR"/eko-roles-*.sql 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
say "retención: se guardan las $KEEP más nuevas ($(ls -1 "$OUT_DIR"/eko-realtors-*.dump.gpg 2>/dev/null | wc -l | tr -d ' ') presentes)"

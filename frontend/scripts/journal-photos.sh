#!/usr/bin/env bash
#
# Pone las fotografias del Journal en `public/blog/img/`.
#
# POR QUE ESTO EXISTE, Y NO UN `git add`.
# Las cuarenta y ocho fotografias del articulo "Twelve houses" son de OCHO
# corredurias ajenas —ninguna es de la nuestra— y la politica del MLS de
# REcolorado lo dice sin rodeos: «Use of a photograph from another Subscriber's
# listing is strictly prohibited unless you have written permission from the
# owner of the copyright». Este repositorio es PUBLICO: meterlas aqui es
# redistribuirlas, y el historial de git no se deshace. Se quedan fuera hasta
# que exista el permiso escrito, y entonces entran los ORIGINALES SIN RECORTAR
# —los que hay hoy llevan recortado el 11% inferior, que es justo donde iba la
# marca de agua de copyright—. El encuadre lo hace el CSS, como ya hace /fall.
#
# El despliegue no necesita nada mas: el Dockerfile hace `COPY . .` sobre el
# directorio de trabajo y el runner copia `public` a la imagen, asi que basta
# con correr esto en la maquina que construye.
#
#   frontend/scripts/journal-photos.sh [carpeta-de-origen]
#
# Sin argumento usa la copia maestra en la carpeta de marca.
set -euo pipefail

SRC="${1:-$HOME/Documents/Denver Home Story - Brand/journal/photos-originales}"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/public/blog"

if [ ! -d "$SRC" ]; then
  echo "no encuentro el origen: $SRC" >&2
  echo "es la copia maestra, fuera del repositorio. Sin ella no hay fotos." >&2
  exit 1
fi

# `sips` viene con macOS. No se usa `sharp` porque el proyecto no lo tiene
# instalado ni usa `next/image`: anadir una dependencia para redimensionar
# cuarenta y nueve ficheros una vez seria pagar mantenimiento para siempre.
if ! command -v sips >/dev/null 2>&1; then
  echo "hace falta \`sips\` (macOS). En Linux: usa \`convert -resize\`." >&2
  exit 1
fi

mkdir -p "$DEST/img"

# La principal de cada ficha se ve a todo el ancho de la columna (1120px como
# mucho, el doble en pantalla retina); las tres miniaturas van a un tercio.
# Redimensionar aqui y no en el navegador es lo que separa 30 MB de 3.
n=0
for f in "$SRC"/*.jpg; do
  base="$(basename "$f")"
  case "$base" in
    denver-skyline.jpg)
      # Esta la entrego el cliente y sus derechos estan limpios: va versionada.
      sips --resampleWidth 2240 "$f" --out "$DEST/$base" >/dev/null
      ;;
    *-0.jpg)
      sips --resampleWidth 1600 "$f" --out "$DEST/img/$base" >/dev/null
      ;;
    *)
      sips --resampleWidth 800 "$f" --out "$DEST/img/$base" >/dev/null
      ;;
  esac
  n=$((n + 1))
done

echo "$n ficheros procesados"
echo "  $DEST/img  -> $(du -sh "$DEST/img" | cut -f1)  ($(ls "$DEST/img" | wc -l | tr -d ' ') fotos, IGNORADAS por git)"
echo "  $DEST/denver-skyline.jpg -> $(du -h "$DEST/denver-skyline.jpg" | cut -f1)  (versionada)"

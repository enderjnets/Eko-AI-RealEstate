#!/usr/bin/env bash
#
# Pone las fotografias del Journal en `private/journal/img/`.
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
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/private/journal"

if [ ! -d "$SRC" ]; then
  echo "no encuentro el origen: $SRC" >&2
  echo "es la copia maestra, fuera del repositorio. Sin ella no hay fotos." >&2
  exit 1
fi

mkdir -p "$DEST/img"

# LAS FOTOS SE COPIAN TAL CUAL. No se redimensionan.
#
# Antes esto las reducia: la principal de cada ficha a 1600px y las otras tres
# a 800, "porque eso separa 30 MB de 3". Era un ahorro medido en el sitio
# equivocado. Medido en el bueno, sobre la pagina servida a 1827px de ancho:
# la principal se pinta a 1129 CSS px, que en una pantalla retina son 2258
# pixeles reales. Con 1600 le faltan 658, y eso se VE — doce de las quince
# fotos que carga el articulo salian blandas en el Mac de Ender, y lo leyo,
# con razon, como que la pagina no era la que el habia disenado.
#
# El diseno las trae a 2000px de ancho. Sigue siendo menos de 2258, pero es lo
# que hay: son las fotos que nos entregaron, y la alternativa es inventarse
# pixeles. Lo que NO se hace es empeorarlas al copiarlas.
#
# Y hay una segunda razon, independiente de como se vea: estas cuarenta y ocho
# fotografias son de ocho corredurias ajenas. Cada transformacion que les
# aplicamos es una obra derivada mas sobre material que ya llega con la marca
# de agua recortada. Copiar y no tocar es tambien la postura correcta ahi.
n=0
for f in "$SRC"/*.jpg; do
  base="$(basename "$f")"
  case "$base" in
    denver-skyline.jpg)
      # El skyline SI se recodifica, y es la excepcion que confirma la regla de
      # arriba. Es del cliente, con los derechos limpios, y va VERSIONADA en un
      # repositorio publico. Se pinta al mismo ancho que las demas (1129 CSS px
      # -> 2258 reales en retina), asi que 2240 le llega: el original de 2480px
      # pesa 2,0 MB y el recodificado 707 KB para el mismo resultado en
      # pantalla. Ahi el ahorro si esta en el sitio correcto, porque el limite
      # que importa es el del repositorio y no el de la vista.
      command -v sips >/dev/null 2>&1 || { echo "hace falta \`sips\` (macOS)" >&2; exit 1; }
      sips --resampleWidth 2240 "$f" --out "$DEST/$base" >/dev/null
      ;;
    *)
      cp "$f" "$DEST/img/$base"
      ;;
  esac
  n=$((n + 1))
done

echo "$n ficheros procesados"
echo "  $DEST/img  -> $(du -sh "$DEST/img" | cut -f1)  ($(ls "$DEST/img" | wc -l | tr -d ' ') fotos, IGNORADAS por git)"
echo "  $DEST/denver-skyline.jpg -> $(du -h "$DEST/denver-skyline.jpg" | cut -f1)  (versionada)"

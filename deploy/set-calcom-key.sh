#!/usr/bin/env bash
# Guardar la API key de Cal.com para que las citas se reserven DE VERDAD.
#
#   ssh -t ender-vps '~/Eko-AI-RealEstate/deploy/set-calcom-key.sh'
#
# El valor se TECLEA: no entra en el historial del shell, ni en los argumentos,
# ni en `ps` de una maquina que corre los productos de otros dos clientes.
#
# La comprobacion NO es la forma de la cadena: es que Cal.com deje LISTAR los
# event types con ella. Esa es la capacidad que el producto va a ejercer, y de
# paso devuelve el id que hay que configurar. Verificar la existencia de una
# credencial en vez de su capacidad ya nos costo dos rechazos de un token bueno
# de Cloudflare; la regla vive aqui para no repetirlo.
#
# Esta clave SI va al .env de la aplicacion (a diferencia del token de
# Cloudflare, que es de operacion): el backend la necesita en caliente.
set -euo pipefail

ENV_FILE="$HOME/Eko-AI-RealEstate/.env"
[ -f "$ENV_FILE" ] || { echo "No encuentro $ENV_FILE" >&2; exit 1; }

echo "Cal.com -> Settings -> Developer -> API keys."
echo "Las claves empiezan por 'cal_live_' (o 'cal_test_')."
read -rs -p "API key (no se vera): " KEY
echo
[ -n "${KEY}" ] || { echo "RECHAZADO: no se escribio nada. No se ha tocado nada." >&2; exit 1; }

echo "Preguntando a Cal.com si la clave puede listar los event types..."
RESP=""
VER_OK=""
for VER in 2024-06-14 2024-08-13 ""; do
  if [ -n "$VER" ]; then
    R="$(curl -s --max-time 20 "https://api.cal.com/v2/event-types" \
        -H "Authorization: Bearer ${KEY}" -H "cal-api-version: ${VER}")" || R=""
  else
    R="$(curl -s --max-time 20 "https://api.cal.com/v2/event-types" \
        -H "Authorization: Bearer ${KEY}")" || R=""
  fi
  if printf '%s' "$R" | jq -e '.status == "success"' >/dev/null 2>&1; then
    RESP="$R"; VER_OK="${VER:-<sin cabecera>}"; break
  fi
done

if [ -z "$RESP" ]; then
  echo "RECHAZADO: Cal.com no acepta la clave. No se ha tocado nada." >&2
  echo "  longitud de lo tecleado: ${#KEY} caracteres" >&2
  printf '%s' "$R" | jq -r '"  respuesta: \(.error.message // .message // .)"' 2>/dev/null \
    | head -3 >&2 || echo "  (respuesta no legible)" >&2
  case "$KEY" in
    cal_live_*|cal_test_*) echo "  La forma es la correcta, asi que el problema no es de donde la copiaste: puede estar revocada, ser de otra cuenta, o haber llegado incompleta." >&2 ;;
    *) echo "  No empieza por cal_live_ / cal_test_: revisa que sea una API key, no otro identificador." >&2 ;;
  esac
  unset KEY; exit 1
fi

echo "  Cal.com responde: success (cabecera de version: ${VER_OK})"
echo
echo "=== EVENT TYPES DISPONIBLES (los ids no son secretos) ==="
printf '%s' "$RESP" | jq -r '
  (.data // [])[] |
  "  id=\(.id)  \(.lengthInMinutes // .length // "?") min  \"\(.title)\"  slug=\(.slug)  oculto=\(.hidden // false)"'
echo

cp -a "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d-%H%M%S)"
umask 077
if grep -q '^CALCOM_API_KEY=' "$ENV_FILE"; then
  # sed con la clave en el patron de sustitucion la expondria en `ps`: se hace
  # con un fichero temporal y python leyendo la variable del entorno.
  KEY="$KEY" python3 - "$ENV_FILE" <<'PY'
import os, sys, pathlib
p = pathlib.Path(sys.argv[1])
out = []
for line in p.read_text().splitlines():
    out.append(f"CALCOM_API_KEY={os.environ['KEY']}" if line.startswith("CALCOM_API_KEY=") else line)
p.write_text("\n".join(out) + "\n")
PY
else
  KEY="$KEY" python3 - "$ENV_FILE" <<'PY'
import os, sys, pathlib
p = pathlib.Path(sys.argv[1])
p.write_text(p.read_text().rstrip("\n") + f"\nCALCOM_API_KEY={os.environ['KEY']}\n")
PY
fi
chmod 600 "$ENV_FILE"
unset KEY

echo "Guardada en $ENV_FILE (permisos $(stat -c '%a' "$ENV_FILE"))."
echo "Longitud del valor guardado: $(sed -n 's/^CALCOM_API_KEY=//p' "$ENV_FILE" | wc -c | tr -d ' ') bytes."
echo
echo "FALTA: elegir el event type de la lista de arriba y apagar CALENDAR_SIMULATED."
echo "Eso lo hago yo; dime que id es el de las visitas a propiedades."

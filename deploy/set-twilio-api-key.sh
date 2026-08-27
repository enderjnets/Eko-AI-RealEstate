#!/usr/bin/env bash
# Put a Twilio API Key into the live .env, so that SENDING stops depending on
# the account Auth Token.
#
# Run it ON THE HOST WHERE PRODUCTION LIVES (since 27-ago-2026, the VPS):
#   ssh -t ender-vps '~/Eko-AI-RealEstate/deploy/set-twilio-api-key.sh'
#
# Both values are typed, never passed as arguments and never echoed: they do not
# reach the shell history, this script's arguments, or `ps` on a machine that
# also runs two other clients' products.
#
# This does NOT restart anything. The code that reads these variables ships in
# the same deploy that will restart the backend, and restarting now would only
# reload a build that ignores them — which looks like the change did nothing.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
[ -f "$ENV_FILE" ] || { echo "No hay $ENV_FILE en $(pwd)" >&2; exit 1; }

echo "Twilio → Account → API keys & tokens → la clave que creaste."
read -rs -p "SID de la API Key (empieza por SK, no se verá): " SID
echo
read -rs -p "Secret de la API Key (no se verá): " SECRET
echo

# An API Key SID is `SK` + 32 hex. The Account SID is `AC` + 32 hex and is the
# single most likely thing to paste here by mistake — it is on the same screen,
# it is the same length, and using it as the basic-auth username with an API
# key secret as the password fails every send with a 401.
if ! printf '%s' "$SID" | grep -Eq '^SK[0-9a-f]{32}$'; then
  echo "RECHAZADO: el SID no tiene la forma de una API Key (SK + 32 hex)." >&2
  case "$SID" in
    AC*) echo "  Empieza por AC: eso es el Account SID, no la API Key." >&2 ;;
  esac
  echo "  No se ha tocado nada." >&2
  unset SID SECRET
  exit 1
fi

# The secret is 32 characters, mixed case and digits. Checked mostly to catch a
# truncated paste — the shape is not as distinctive as the SID's.
if ! printf '%s' "$SECRET" | grep -Eq '^[A-Za-z0-9]{32}$'; then
  echo "RECHAZADO: el secreto no tiene 32 caracteres alfanuméricos." >&2
  echo "  Longitud recibida: ${#SECRET}. No se ha tocado nada." >&2
  unset SID SECRET
  exit 1
fi

if [ "$SID" = "$SECRET" ]; then
  echo "RECHAZADO: has pegado el mismo valor dos veces." >&2
  unset SID SECRET
  exit 1
fi

BACKUP="$ENV_FILE.bak.apikey-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$ENV_FILE" "$BACKUP"
chmod 600 "$BACKUP"
echo "Copia previa: $BACKUP"

# Through the environment, so neither value appears in a command line.
SID="$SID" SECRET="$SECRET" python3 - "$ENV_FILE" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
vals = {"TWILIO_API_KEY_SID": os.environ["SID"], "TWILIO_API_KEY_SECRET": os.environ["SECRET"]}
lines = path.read_text().splitlines()
for key, val in vals.items():
    hits = [i for i, l in enumerate(lines) if l.startswith(f"{key}=")]
    if len(hits) > 1:
        print(f"FATAL: {key} aparece {len(hits)} veces; arréglalo a mano", file=sys.stderr)
        sys.exit(1)
    if hits:
        lines[hits[0]] = f"{key}={val}"
    else:
        # Appended next to the rest of the Twilio block would be nicer, but
        # correctness first: a duplicate key later in the file would silently
        # win over an earlier one, so we only ever write one line per key.
        lines.append(f"{key}={val}")
path.write_text("\n".join(lines) + "\n")
print("Escritas 2 claves.")
PY
unset SID SECRET

# Verified by shape, never by value.
for k in TWILIO_API_KEY_SID TWILIO_API_KEY_SECRET; do
  n=$(grep -c "^$k=" "$ENV_FILE")
  v=$(grep -m1 "^$k=" "$ENV_FILE" | cut -d= -f2- | tr -d '\n')
  echo "  $k: $n línea(s), longitud ${#v}"
  [ "$n" = "1" ] || { echo "Algo salió mal; restaura: cp $BACKUP $ENV_FILE" >&2; exit 1; }
done

cat <<'FIN'

Escrito, y NADA se ha reiniciado — a propósito: el build que corre ahora mismo
todavía no lee estas variables, así que hasta que se despliegue el código nuevo
se sigue enviando con el Auth Token, exactamente como hasta ahora. Sin ventana
de caída y sin cambio de comportamiento.

Avísale al agente para que despliegue. La verificación de que la clave funciona
es un SMS real DESPUÉS del despliegue, no antes.
FIN

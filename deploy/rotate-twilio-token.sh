#!/usr/bin/env bash
# Rotate TWILIO_AUTH_TOKEN in the live .env and restart the backend.
#
# Run it ON THE HOST WHERE PRODUCTION LIVES (since 27-ago-2026 that is the VPS):
#   ssh -t ender-vps '~/Eko-AI-RealEstate/deploy/rotate-twilio-token.sh'
#
# The token is typed, never passed as an argument and never echoed: it does not
# reach your shell history, this script's arguments, or `ps` on the machine.
# That matters here more than usual — this rotation exists BECAUSE the previous
# token was found in plain text in `~/.bash_history` on the ROG.
#
# ── What this token is, and what it is NOT ───────────────────────────────────
# `TWILIO_AUTH_TOKEN` does two jobs in this codebase:
#   - outbound: HTTP basic auth as (ACCOUNT_SID, token)   — services/sms.py:160
#   - inbound:  validates the webhook signature           — channel_identity.py:263-264
# A Twilio **API Key** (`SK…` + a mixed-case secret) cannot do the second one:
# Twilio signs webhooks with the account's Auth Token, and there is no setting
# that changes that. Pasting an API Key secret here would keep the page up and
# make every inbound SMS and call return 403 — the funnel goes deaf while
# looking healthy. Hence the shape check below, which is not a formality.
#
# The right thing to rotate with is a SECONDARY AUTH TOKEN: Twilio keeps both
# valid at once, so you update this file first and only then promote it, and
# there is no window where inbound is broken.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
[ -f "$ENV_FILE" ] || { echo "No hay $ENV_FILE en $(pwd)" >&2; exit 1; }

read -rs -p "Pega el Auth Token nuevo (no se verá al escribir) y pulsa Enter: " TOK
echo

# 32 lowercase hex characters. An API Key secret is the same length but mixes
# case, so length alone would let it through — the character class is the half
# that actually catches the mistake this script was written for.
if ! printf '%s' "$TOK" | grep -Eq '^[0-9a-f]{32}$'; then
  echo "RECHAZADO: no tiene la forma de un Auth Token (32 caracteres 0-9a-f)." >&2
  echo "  Longitud recibida: ${#TOK}. No se ha tocado nada." >&2
  echo "  Si empieza por SK o lleva mayúsculas, es una API Key y NO sirve:" >&2
  echo "  no valida la firma de los webhooks entrantes." >&2
  unset TOK
  exit 1
fi

BACKUP="$ENV_FILE.bak.rotacion-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$ENV_FILE" "$BACKUP"
chmod 600 "$BACKUP"
echo "Copia previa: $BACKUP"

# Rewritten in python with the value coming through the environment, so the
# token never appears in a command line that `ps` could show to another user on
# the box — and this box also runs two other clients' products.
TOK="$TOK" python3 - "$ENV_FILE" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
tok = os.environ["TOK"]
lines = path.read_text().splitlines()
hits = 0
for i, line in enumerate(lines):
    if line.startswith("TWILIO_AUTH_TOKEN="):
        lines[i] = "TWILIO_AUTH_TOKEN=" + tok
        hits += 1
if hits == 0:
    # Appending would "work" and hide a real problem: the wrong file, or a key
    # that was renamed. Better to stop than to leave two sources of truth.
    print("FATAL: no existe una línea TWILIO_AUTH_TOKEN= en el fichero", file=sys.stderr)
    sys.exit(1)
if hits > 1:
    print(f"FATAL: hay {hits} líneas TWILIO_AUTH_TOKEN=; arréglalo a mano", file=sys.stderr)
    sys.exit(1)
path.write_text("\n".join(lines) + "\n")
print("Sustituida 1 línea.")
PY
unset TOK

# Verified by shape, never by value.
LEN=$(grep -m1 '^TWILIO_AUTH_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '\n' | wc -c | tr -d ' ')
echo "Comprobación: longitud del valor guardado = $LEN (debe ser 32)"
[ "$LEN" = "32" ] || { echo "Algo salió mal; restaura con: cp $BACKUP $ENV_FILE" >&2; exit 1; }

# Settings are read at import time, so the process must be replaced. Only the
# backend: the frontend does not use this value, and restarting it would darken
# the public landing for no reason.
echo "Reiniciando el backend…"
docker compose up -d backend

for i in $(seq 1 30); do
  sleep 2
  if curl -fsS --max-time 5 http://127.0.0.1:8011/api/v1/health >/dev/null 2>&1; then
    echo "Backend en pie: $(curl -fsS --max-time 5 http://127.0.0.1:8011/api/v1/health)"
    break
  fi
  [ "$i" = "30" ] && { echo "El backend no responde. Restaura: cp $BACKUP $ENV_FILE && docker compose up -d backend" >&2; exit 1; }
done

cat <<'FIN'

Hecho en esta máquina. Faltan DOS comprobaciones que este script no puede hacer
por ti, y hay que hacer las dos — la salida y la entrada usan el token en
sitios distintos, así que una puede funcionar con la otra rota:

  1. SALIDA: que el sistema envíe un SMS real a tu móvil.
  2. ENTRADA: responde a ese SMS. Si el mensaje aparece en el panel, la firma
     del webhook valida. Si no aparece, el backend está devolviendo 403 y la
     mitad entrante del embudo está muerta.

Y sólo cuando las dos funcionen, vuelve a Twilio y promociona el token
secundario a primario. Hasta ese momento el antiguo sigue vivo, que es
exactamente la red que hace segura esta rotación.
FIN

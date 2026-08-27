#!/usr/bin/env bash
# Guardar un API token de Cloudflare para las tareas de DNS de denverhomestory.com.
#
# Se ejecuta EN EL HOST DONDE VIVE PRODUCCIÓN (desde el 27-ago-2026, el VPS):
#   ssh -t ender-vps '~/Eko-AI-RealEstate/deploy/set-cloudflare-token.sh'
#
# El valor se TECLEA, nunca se pasa como argumento y nunca se imprime: no llega
# al historial del shell, ni a los argumentos de este script, ni a `ps` en una
# máquina que además corre los productos de otros dos clientes.
#
# El fichero NO va dentro del repo ni dentro del .env de la aplicación: la
# aplicación no necesita este token, es una credencial de operación. Vive en
# ~/.eko-cloudflare.env con permisos 600, como ~/.eko-heartbeat.env.
#
# La comprobación de que el token sirve NO es su forma: es la respuesta del
# propio Cloudflare a /user/tokens/verify. Un token con la forma correcta y los
# permisos equivocados pasa cualquier expresión regular y falla en el primer
# uso real.
set -euo pipefail

DEST="$HOME/.eko-cloudflare.env"

echo "Cloudflare → My Profile → API Tokens → el token que creaste."
echo "Ámbito esperado: Zone:Read + DNS:Edit, SOLO sobre denverhomestory.com."
read -rs -p "Token (no se verá): " TOKEN
echo

if [ -z "${TOKEN}" ]; then
  echo "RECHAZADO: no se escribió nada. No se ha tocado nada." >&2
  exit 1
fi

# Forma orientativa, no un veredicto: los tokens de Cloudflare son ~40
# caracteres de [A-Za-z0-9_-]. Si el formato cambia, avisa pero no bloquea —
# quien decide es el verify de abajo.
if ! printf '%s' "$TOKEN" | grep -Eq '^[A-Za-z0-9_-]{30,60}$'; then
  echo "AVISO: la forma no es la habitual (longitud ${#TOKEN}). Sigo y pregunto a Cloudflare." >&2
fi

echo "Preguntando a Cloudflare si el token vale…"
RESP="$(curl -s --max-time 20 \
  "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  -H "Authorization: Bearer ${TOKEN}")" || {
    echo "RECHAZADO: no se pudo hablar con Cloudflare. No se ha tocado nada." >&2
    unset TOKEN; exit 1; }

# Solo se imprime el veredicto y el estado. Nunca el token, nunca la respuesta
# entera (que lleva el id del token).
if printf '%s' "$RESP" | grep -q '"success":true'; then
  STATUS="$(printf '%s' "$RESP" | sed -n 's/.*"status":"\([a-z]*\)".*/\1/p')"
  echo "  Cloudflare responde: success, status=${STATUS:-desconocido}"
  if [ "${STATUS:-}" != "active" ]; then
    echo "RECHAZADO: el token existe pero no está activo. No se ha tocado nada." >&2
    unset TOKEN; exit 1
  fi
else
  echo "RECHAZADO: Cloudflare no lo acepta. No se ha tocado nada." >&2
  printf '%s' "$RESP" | sed -n 's/.*"message":"\([^"]*\)".*/  motivo: \1/p' >&2
  unset TOKEN; exit 1
fi

umask 077
printf 'CLOUDFLARE_API_TOKEN=%s\n' "$TOKEN" > "$DEST"
chmod 600 "$DEST"
unset TOKEN

echo "Guardado en $DEST con permisos $(stat -c '%a' "$DEST" 2>/dev/null || stat -f '%Lp' "$DEST")."
echo "Longitud del valor guardado: $(sed -n 's/^CLOUDFLARE_API_TOKEN=//p' "$DEST" | wc -c | tr -d ' ') bytes (verificación por forma, no por valor)."

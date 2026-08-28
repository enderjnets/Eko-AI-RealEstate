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
  printf '%s' "$RESP" | sed -n 's/.*"code":\([0-9]*\).*/  codigo: \1/p' >&2
  # Diagnóstico por FORMA, nunca por valor: longitud y clase de caracteres, que
  # es exactamente lo que este script ya imprime cuando el token SÍ vale.
  #
  # "Invalid API Token" sobre una cadena bien formada casi nunca es un token
  # caducado. El fallo real es que la lista de API Tokens muestra el ID del
  # token —32 hex, que pasa cualquier comprobación de forma— y el VALOR solo se
  # enseña una vez, al crearlo. Sin esta pista, el segundo intento repite el
  # primero: por eso el diagnóstico vive aquí y no en la cabeza de quien lo usa.
  echo "  longitud de lo tecleado: ${#TOKEN} caracteres" >&2
  if printf '%s' "$TOKEN" | grep -Eq '^[0-9a-f]{32}$'; then
    echo "  --> ESO ES EL ID DEL TOKEN, NO EL TOKEN." >&2
    echo "      32 caracteres hex es lo unico que enseña la LISTA de tokens." >&2
    echo "      El valor real son ~40 caracteres y solo se ve al crearlo:" >&2
    echo "      entra en ese token y pulsa 'Roll' para que te enseñe uno nuevo." >&2
  elif printf '%s' "$TOKEN" | grep -Eq '^[0-9a-f]{37}$'; then
    echo "  --> ESO PARECE LA GLOBAL API KEY, NO UN TOKEN acotado." >&2
    echo "      La clave global no sirve aqui: crea un token con Zone:Read +" >&2
    echo "      DNS:Edit limitado a denverhomestory.com." >&2
  fi
  unset TOKEN; exit 1
fi

umask 077
printf 'CLOUDFLARE_API_TOKEN=%s\n' "$TOKEN" > "$DEST"
chmod 600 "$DEST"
unset TOKEN

echo "Guardado en $DEST con permisos $(stat -c '%a' "$DEST" 2>/dev/null || stat -f '%Lp' "$DEST")."
echo "Longitud del valor guardado: $(sed -n 's/^CLOUDFLARE_API_TOKEN=//p' "$DEST" | wc -c | tr -d ' ') bytes (verificación por forma, no por valor)."

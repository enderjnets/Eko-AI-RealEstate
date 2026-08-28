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
# La comprobación de que el token sirve NO es su forma: es que Cloudflare le
# deje LEER la zona denverhomestory.com. Un token con la forma correcta y los
# permisos equivocados pasa cualquier expresión regular y falla en el primer
# uso real.
#
# Este script comprobaba antes contra /user/tokens/verify, y eso era un error
# de medida con consecuencias: ese endpoint solo acepta tokens de USUARIO, y
# devuelve 1000 "Invalid API Token" ante un token account-owned perfectamente
# válido. Rechazó dos veces un token bueno del dueño y le echó la culpa a él.
# La regla que queda: verifica la capacidad que vas a usar, no la existencia de
# la credencial.
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

# La pregunta correcta NO es "¿existe este token?", es "¿puede hacer el
# trabajo?". Se comprueba LEYENDO la zona que vamos a editar. Tres razones, y
# la segunda es una avería que este script ya provocó:
#
#  1. Zone:Read sobre denverhomestory.com es exactamente la capacidad que hace
#     falta. Probarla es mejor que probar un proxy de ella.
#  2. `/user/tokens/verify` SOLO sirve para tokens de USUARIO. Un token
#     "account-owned" (Manage Account → Account API Tokens) es perfectamente
#     válido y ese endpoint lo rechaza con **1000 "Invalid API Token"** — es
#     decir, el instrumento declaraba malo un token bueno, que es el peor tipo
#     de error de medida: el que culpa a quien lo usa.
#  3. De paso devuelve el zone id, que hace falta para escribir el DNS después.
ZONE_NAME="denverhomestory.com"

RESP="$(curl -s --max-time 20 \
  "https://api.cloudflare.com/client/v4/zones?name=${ZONE_NAME}" \
  -H "Authorization: Bearer ${TOKEN}")" || {
    echo "RECHAZADO: no se pudo hablar con Cloudflare. No se ha tocado nada." >&2
    unset TOKEN; exit 1; }

OK="$(printf '%s' "$RESP" | jq -r '.success // false' 2>/dev/null || echo false)"
ZONE_ID="$(printf '%s' "$RESP" | jq -r '.result[0].id // empty' 2>/dev/null || true)"
ZONE_STATUS="$(printf '%s' "$RESP" | jq -r '.result[0].status // empty' 2>/dev/null || true)"

if [ "$OK" = "true" ] && [ -n "$ZONE_ID" ]; then
  echo "  Cloudflare responde: success — el token LEE la zona ${ZONE_NAME}."
  echo "  Estado de la zona: ${ZONE_STATUS:-desconocido}"
else
  echo "RECHAZADO: el token no sirve para esta zona. No se ha tocado nada." >&2

  if [ "$OK" = "true" ]; then
    # Existe y responde, pero no ve la zona: el fallo está en el ÁMBITO.
    echo "  El token es válido, pero NO alcanza ${ZONE_NAME}." >&2
    echo "  Revisa en el token: Zone Resources → Include → Specific zone →" >&2
    echo "  ${ZONE_NAME}, y el permiso Zone:Read (además de DNS:Edit)." >&2
    echo "  Si lo creaste en otra cuenta de Cloudflare, tampoco la verá." >&2
  else
    printf '%s' "$RESP" | jq -r '.errors[]? | "  error \(.code): \(.message)"' >&2 2>/dev/null || \
      echo "  (Cloudflare no devolvió un error legible)" >&2
    # Diagnóstico por FORMA, nunca por valor.
    echo "  longitud de lo tecleado: ${#TOKEN} caracteres" >&2
    if printf '%s' "$TOKEN" | grep -q '^cfut_'; then
      echo "  La forma es la del token NUEVO de Cloudflare (prefijo 'cfut_')," >&2
      echo "  así que el problema no es de dónde lo copiaste: o se rodó/borró" >&2
      echo "  después, o el valor llegó incompleto. Pulsa 'Roll' y repite." >&2
    elif printf '%s' "$TOKEN" | grep -Eq '^[0-9a-f]{32}$'; then
      echo "  --> ESO ES EL ID DEL TOKEN, NO EL TOKEN." >&2
      echo "      32 hex es lo único que enseña la LISTA de tokens; el valor" >&2
      echo "      solo se ve al crearlo. Pulsa 'Roll' para que te enseñe uno." >&2
    elif printf '%s' "$TOKEN" | grep -Eq '^[0-9a-f]{37}$'; then
      echo "  --> ESO PARECE LA GLOBAL API KEY, NO UN TOKEN acotado." >&2
      echo "      Crea un token con Zone:Read + DNS:Edit sobre ${ZONE_NAME}." >&2
    fi
  fi
  unset TOKEN; exit 1
fi

umask 077
{
  printf 'CLOUDFLARE_API_TOKEN=%s\n' "$TOKEN"
  # El zone id NO es un secreto; se guarda para no volver a preguntarlo.
  printf 'CLOUDFLARE_ZONE_ID=%s\n' "$ZONE_ID"
} > "$DEST"
chmod 600 "$DEST"
unset TOKEN

echo "Guardado en $DEST con permisos $(stat -c '%a' "$DEST" 2>/dev/null || stat -f '%Lp' "$DEST")."
echo "Longitud del valor guardado: $(sed -n 's/^CLOUDFLARE_API_TOKEN=//p' "$DEST" | wc -c | tr -d ' ') bytes (verificación por forma, no por valor)."

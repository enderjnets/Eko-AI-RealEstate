#!/usr/bin/env bash
# Install the render worker on the render machine. Idempotent: run it again
# after a code change and it updates in place.
#
# Run it FROM THE MAC, not on the ROG:
#
#     worker/install-on-rog.sh
#
# What it touches, and nothing else: a virtualenv of its own, a directory of
# its own, one environment file at mode 600, and one systemd USER unit named
# after this product. It never touches the crontab — a self-heal on that
# machine rewrites the whole crontab from a backup every fifteen minutes, so a
# line added there disappears without warning — and it never touches another
# project's services, models or GPU.
set -euo pipefail

ROG="${ROG_HOST:-pcrug}"
VPS="${VPS_HOST:-ender-vps}"
APP_DIR="eko-render/app"
VENV="\$HOME/.venvs/eko-render"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/7 · ¿está la máquina?"
if ! ssh -o ConnectTimeout=20 "$ROG" true 2>/dev/null; then
    echo "El ROG no responde por '$ROG'. Probando la tailnet…"
    ROG="${ROG}-ts"
    ssh -o ConnectTimeout=20 "$ROG" true || {
        echo "Tampoco por la tailnet. No se instala nada a ciegas."
        echo
        echo "Para saber QUÉ pasa, y son diagnósticos distintos:"
        echo "  ping 10.0.0.240          # ¿está en la red?"
        echo "  nc -z -v -w 6 10.0.0.240 22   # ¿acepta el TCP?"
        echo
        echo "Si el ping va y el TCP acepta pero ssh dice \"banner exchange\","
        echo "la máquina NO está apagada: está asfixiada — sshd acepta y no"
        echo "puede avanzar. Mirar el disco antes que nada; esta máquina ya"
        echo "estuvo al 99% y corrompió objetos de git."
        exit 1
    }
fi
ssh "$ROG" 'hostname; python3 --version; command -v ffmpeg >/dev/null || { echo "FALTA ffmpeg"; exit 1; }'

say "2/7 · el código"
cd "$(dirname "$0")/.."
tar -czf /tmp/eko-worker.tgz worker/
scp -q /tmp/eko-worker.tgz "$ROG:/tmp/"
ssh "$ROG" "mkdir -p ~/$APP_DIR && tar -xzf /tmp/eko-worker.tgz -C ~/$APP_DIR && rm /tmp/eko-worker.tgz"
rm -f /tmp/eko-worker.tgz

say "3/7 · el entorno de Python (suyo, no el de nadie más)"
ssh "$ROG" "python3 -m venv $VENV 2>/dev/null || true; $VENV/bin/pip install -q --upgrade pip; $VENV/bin/pip install -q -r ~/$APP_DIR/worker/requirements.txt; $VENV/bin/python -c 'import httpx, faster_whisper, num2words, jwt, PIL; print(\"dependencias ok\")'"

say "4/7 · el secreto compartido, sin que pase por ninguna pantalla"
# Generated on the VPS, written on both sides, never printed and never held in
# a file on this laptop. The same pattern the Cloudflare and Twilio secrets use.
ssh "$VPS" '
  set -e
  cd ~/Eko-AI-RealEstate
  if ! grep -q "^RENDER_WORKER_TOKEN=.\{16,\}" .env; then
    T=$(openssl rand -hex 32)
    sed -i "/^RENDER_WORKER_TOKEN=/d" .env
    printf "RENDER_WORKER_TOKEN=%s\n" "$T" >> .env
    echo "token nuevo generado en el VPS"
  else
    echo "el VPS ya tenía token; se reutiliza"
  fi'
ssh "$VPS" 'sed -n "s/^RENDER_WORKER_TOKEN=//p" ~/Eko-AI-RealEstate/.env | head -1' \
  | ssh "$ROG" "cat > /tmp/.tok && chmod 600 /tmp/.tok"

say "5/7 · la configuración del obrero"
# MINIMAX_API_KEY comes from the VPS by pipe, for the same reason.
ssh "$VPS" 'sed -n "s/^MINIMAX_API_KEY=//p" ~/Eko-AI-RealEstate/.env | head -1' \
  | ssh "$ROG" "cat > /tmp/.mm && chmod 600 /tmp/.mm"
ssh "$ROG" '
  set -e
  TOK=$(cat /tmp/.tok); MM=$(cat /tmp/.mm); rm -f /tmp/.tok /tmp/.mm
  umask 077
  cat > ~/.eko-render.env <<EOF
# Denver Home Story — obrero de render. NO commitear, NO imprimir.
EKO_API_BASE=https://inmo-demo.ekoaiautomation.com
RENDER_WORKER_TOKEN=$TOK
RENDER_WORKER_NAME=rog-1
# Horas libres en esta máquina, acordadas con el otro proyecto que la usa.
# Se comprueban en cada tick, no se declaran a un timer: OnCalendar con
# Persistent dispara tarde tras un corte de luz, y eso es un render metiéndose
# en la ventana de otro.
RENDER_WORKER_HOURS=13,15,16,17,21,23,1,2
RENDER_WORKER_DIR=$HOME/eko-render/tmp
RENDER_CACHE_DIR=$HOME/eko-render/cache

# El locutor. Voz elegida por el dueño el 30-ago entre cuatro variantes.
MINIMAX_API_KEY=$MM
RENDER_TTS_VOICE_ID=English_CalmWoman
RENDER_TTS_SPEED=1.06
RENDER_TTS_EMOTION=happy

# Imágenes. VACÍAS a propósito: sin ellas el carril generado cae a tarjetas de
# marca, que es un vídeo correcto. El paquete de Kling es un saldo COMPARTIDO
# con otros dos proyectos de esta máquina, así que la clave se pone cuando el
# dueño lo diga y el tope se calibra antes.
FAL_KEY=
KLING_ACCESS_KEY=
KLING_SECRET_KEY=
PEXELS_API_KEY=
RENDER_KLING_IMAGES_PER_DAY=8
EOF
  chmod 600 ~/.eko-render.env
  mkdir -p ~/eko-render/tmp ~/eko-render/cache
  echo "configuración escrita (600)"'

say "6/7 · el servicio (unidad de USUARIO, nunca cron)"
ssh "$ROG" "
  set -e
  mkdir -p ~/.config/systemd/user
  cp ~/$APP_DIR/worker/eko-render-worker.service ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --now eko-render-worker
  sleep 4
  systemctl --user is-active eko-render-worker
  loginctl enable-linger \$USER 2>/dev/null || true"

say "7/7 · encender la cola en el panel"
ssh "$VPS" '
  set -e
  cd ~/Eko-AI-RealEstate
  # Replace it if it is there, add it if it is not. `sed` alone silently does
  # nothing on a missing line, and the next check would then fail with no clue
  # as to why.
  if grep -q "^RENDER_WORKER_ENABLED=" .env; then
    sed -i "s/^RENDER_WORKER_ENABLED=.*/RENDER_WORKER_ENABLED=true/" .env
  else
    printf "RENDER_WORKER_ENABLED=true\n" >> .env
  fi
  grep -q "^RENDER_WORKER_ENABLED=true" .env
  docker compose up -d backend >/dev/null
  echo "cola abierta"'

say "listo · comprobación"
sleep 20
ssh "$ROG" "tail -5 ~/eko-render/worker.log 2>/dev/null || journalctl --user -u eko-render-worker -n 5 --no-pager"
ssh "$VPS" 'docker exec eko-realestate-db psql -U eko -d eko_realestate -tAc \
  "select key, state, last_heartbeat_at from monitor_state where key = '"'"'render_worker'"'"'"'

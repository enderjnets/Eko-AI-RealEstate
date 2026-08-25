#!/usr/bin/env bash
#
# Layer 2 of the watch: the one that survives the machine it watches.
#
# The monitor inside the backend re-measures the LLM safety net and emails when
# it moves. What it cannot do is notice its own death: if the container stops,
# the host reboots into a broken state, or the Cloudflare tunnel drops, the loop
# that was supposed to complain is the thing that is gone. A process cannot
# report its own absence, so this runs somewhere else entirely.
#
# It talks to the email provider DIRECTLY, never through the backend. A
# watchman who phones home through the building he is guarding is not a
# watchman.
#
# Install (on a host that is actually up all the time — not a laptop that
# sleeps):
#
#   cp deploy/heartbeat.sh ~/eko-heartbeat.sh && chmod +x ~/eko-heartbeat.sh
#   cat > ~/.eko-heartbeat.env <<'ENV'
#   RESEND_API_KEY=re_xxx
#   OPS_ALERT_FROM=alertas@tu-dominio-verificado
#   OPS_ALERT_TO=tu-correo@gmail.com
#   ENV
#   chmod 600 ~/.eko-heartbeat.env
#   ( crontab -l 2>/dev/null; echo '*/15 * * * * $HOME/eko-heartbeat.sh >/dev/null 2>&1' ) | crontab -
#
set -uo pipefail

URL="${HEALTH_URL:-https://inmo-demo.ekoaiautomation.com/api/v1/health}"
ENV_FILE="${HEARTBEAT_ENV:-$HOME/.eko-heartbeat.env}"
STATE_DIR="${HEARTBEAT_STATE_DIR:-$HOME/.eko-heartbeat}"

# Two consecutive bad checks before we call it an outage. Every deployment
# restarts the backend, and a watchdog that pages on every deploy is a watchdog
# that gets ignored on the day it matters. At */15 this means ~30 minutes of
# real downtime before the phone buzzes, which is the right trade for a service
# whose failure mode is "leads get a holding line", not "money moves".
FAILS_BEFORE_ALERT="${FAILS_BEFORE_ALERT:-2}"

# Same reasoning as the in-process monitor: a loop must be capped rather than
# delivered. Shares the provider quota with real customer email.
MAX_ALERTS_PER_DAY="${MAX_ALERTS_PER_DAY:-3}"

[ -f "$ENV_FILE" ] && . "$ENV_FILE"
mkdir -p "$STATE_DIR"

STATE_FILE="$STATE_DIR/state"        # up | down
FAILS_FILE="$STATE_DIR/fails"        # consecutive bad checks
COUNT_FILE="$STATE_DIR/count"        # YYYY-MM-DD:n

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

send_alert() {
  local subject="$1" body="$2" today n stored
  today="$(date -u +%F)"
  stored="$(cat "$COUNT_FILE" 2>/dev/null || echo "")"
  if [ "${stored%%:*}" = "$today" ]; then n="${stored##*:}"; else n=0; fi
  if [ "$n" -ge "$MAX_ALERTS_PER_DAY" ]; then
    log "budget spent ($n/$MAX_ALERTS_PER_DAY today) — not sending: $subject"
    return 1
  fi
  if [ -z "${RESEND_API_KEY:-}" ] || [ -z "${OPS_ALERT_FROM:-}" ] || [ -z "${OPS_ALERT_TO:-}" ]; then
    # Said out loud. A heartbeat that cannot reach anyone is decoration, and
    # decoration that looks like coverage is worse than nothing.
    log "NOT CONFIGURED (need RESEND_API_KEY, OPS_ALERT_FROM, OPS_ALERT_TO in $ENV_FILE) — would have sent: $subject"
    return 1
  fi

  # Built with python3 rather than string-glued in shell: the body carries a
  # server response we did not write, and a stray quote in it would otherwise
  # produce malformed JSON exactly when the alert matters most.
  local payload
  payload="$(SUBJ="$subject" BODY="$body" FROM="$OPS_ALERT_FROM" TO="$OPS_ALERT_TO" python3 -c '
import json, os
print(json.dumps({
    "from": os.environ["FROM"],
    "to": [t.strip() for t in os.environ["TO"].split(",") if t.strip()],
    "subject": os.environ["SUBJ"],
    "text": os.environ["BODY"],
}))')" || { log "could not build payload"; return 1; }

  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 25 \
      -X POST https://api.resend.com/emails \
      -H "Authorization: Bearer $RESEND_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$payload" 2>/dev/null)" || code=000

  if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
    printf '%s:%s' "$today" "$((n + 1))" > "$COUNT_FILE"
    log "alert sent: $subject"
    return 0
  fi
  log "alert REJECTED by provider (HTTP $code): $subject"
  return 1
}

# ── the check ──────────────────────────────────────────────────────────────
# One request, not two: asking twice doubles the load and, worse, lets the body
# and the status code come from different moments — a service failing right then
# could hand back a healthy body with a failing code and read as either.
raw="$(curl -sS --max-time 20 -w '\n%{http_code}' "$URL" 2>/dev/null)" || raw=$'\n000'
code="${raw##*$'\n'}"
body="${raw%$'\n'*}"
case "$code" in ''|*[!0-9]*) code=000 ;; esac
compact="$(printf '%s' "$body" | tr -d ' \n\t')"

verdict="ok"; reason=""
if [ "$code" != "200" ]; then
  verdict="bad"; reason="El endpoint de salud no responde (HTTP ${code:-000}) en $URL."
elif ! printf '%s' "$compact" | grep -q '"llm_fallback":"ok"'; then
  state_word="$(printf '%s' "$compact" | sed -n 's/.*"llm_fallback":"\([^"]*\)".*/\1/p')"
  verdict="bad"
  reason="Responde, pero llm_fallback=${state_word:-ausente}. La red de seguridad LLM no puede responder."
fi

# ── debounce ───────────────────────────────────────────────────────────────
fails="$(cat "$FAILS_FILE" 2>/dev/null || echo 0)"
case "$fails" in ''|*[!0-9]*) fails=0 ;; esac

if [ "$verdict" = "ok" ]; then fails=0; else fails=$((fails + 1)); fi
printf '%s' "$fails" > "$FAILS_FILE"

if [ "$verdict" = "ok" ]; then
  new_state="up"
elif [ "$fails" -ge "$FAILS_BEFORE_ALERT" ]; then
  new_state="down"
else
  log "check failed ($fails/$FAILS_BEFORE_ALERT) — waiting for confirmation: $reason"
  exit 0   # one bad check is a deploy, not an outage
fi

# ── report only what changed ───────────────────────────────────────────────
old_state="$(cat "$STATE_FILE" 2>/dev/null || echo "")"
if [ "$new_state" = "$old_state" ]; then
  exit 0
fi

# First run ever with everything healthy is not a recovery. Announcing one would
# mean every fresh install greets its owner by reporting an outage that never
# happened — and an alert you learn to disbelieve is worse than none. A first
# run that finds the service DOWN still speaks: that is news.
if [ -z "$old_state" ] && [ "$new_state" = "up" ]; then
  printf '%s' "$new_state" > "$STATE_FILE"
  log "first run — baseline recorded as up, nothing to report"
  exit 0
fi

if [ "$new_state" = "down" ]; then
  send_alert "[Eko Realtors] El vigia externo no ve el servicio" \
"$reason

Comprobado desde fuera del ROG, $fails veces seguidas ($(date -u +%Y-%m-%dT%H:%M:%SZ) UTC).
URL: $URL

Que mirar, en este orden:
  ssh pcrug 'docker ps | grep realestate'
  ssh pcrug 'docker logs --tail 50 eko-realestate-backend'
  ssh pcrug 'systemctl status ollama-bridge ollama'

Si el backend esta vivo pero llm_fallback no es ok, el aviso detallado
deberia haber llegado del propio backend. Si no llego, el que esta roto
es el canal de correo, no solo el modelo."
else
  send_alert "[Eko Realtors] El vigia externo vuelve a ver el servicio" \
"$URL responde 200 y llm_fallback=ok de nuevo ($(date -u +%Y-%m-%dT%H:%M:%SZ) UTC)."
fi

# Written last and unconditionally: if the email failed, re-sending on the next
# tick would spend the whole budget re-reporting one outage instead of leaving
# room for the next one. The state is what is true; delivery is best-effort.
printf '%s' "$new_state" > "$STATE_FILE"

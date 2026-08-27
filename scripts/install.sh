#!/usr/bin/env bash
#
# Eko AI Realtors — single-customer installer.
#
# Run this on the machine (or VPS) that will host ONE real-estate office's
# instance. It checks prerequisites, generates a .env with strong random
# secrets, builds + starts the Docker Compose stack, applies DB migrations,
# and sets the agency branding. Channels (WhatsApp / email / calendar) ship in
# SIMULATED mode by default — flip them on once the office has the accounts.
#
#   curl -fsSL .../install.sh | bash      # not recommended (no prompts)
#   ./scripts/install.sh                  # interactive (recommended)
#   AGENCY_NAME="Sunset Realty" APP_ENV=production ./scripts/install.sh --no-prompt
#
# Safe to re-run: an existing .env is backed up, never silently overwritten.
set -euo pipefail

# ── pretty output ────────────────────────────────────────────────────────
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()    { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m!\033[0m %s\n' "$*"; }
err()   { printf '\033[31m✗\033[0m %s\n' "$*" >&2; }
step()  { printf '\n\033[1;35m▸ %s\033[0m\n' "$*"; }

PROMPT=1
for arg in "$@"; do
  case "$arg" in
    --no-prompt|-y) PROMPT=0 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed -n '2,30p'
      exit 0 ;;
  esac
done
# Non-interactive stdin (piped) also disables prompting.
[ -t 0 ] || PROMPT=0

# ── locate repo root ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
[ -f docker-compose.yml ] || { err "docker-compose.yml not found in $ROOT — run from the repo."; exit 1; }

bold "Eko AI Realtors — installer"
echo  "Repo: $ROOT"

# ── 1. prerequisites ───────────────────────────────────────────────────────
step "Checking prerequisites"
command -v docker >/dev/null 2>&1 || { err "docker not found — install Docker first: https://docs.docker.com/get-docker/"; exit 1; }
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  err "Docker Compose not found — install the Compose plugin."; exit 1
fi
docker info >/dev/null 2>&1 || { err "Docker daemon not reachable — is Docker running?"; exit 1; }
ok "docker + compose present ($DC)"

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 24
  else head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 48; fi
}

ask() { # ask "Prompt" "default" -> echoes the answer
  local prompt="$1" def="${2:-}" ans
  if [ "$PROMPT" -eq 0 ]; then echo "$def"; return; fi
  if [ -n "$def" ]; then read -r -p "$prompt [$def]: " ans; else read -r -p "$prompt: " ans; fi
  echo "${ans:-$def}"
}
ask_secret() { # ask_secret "Prompt" -> echoes typed value without echoing keystrokes
  local prompt="$1" ans
  if [ "$PROMPT" -eq 0 ]; then echo ""; return; fi
  read -r -s -p "$prompt: " ans; echo "" >&2; echo "$ans"
}
yesno() { # yesno "Question" "Y|N" -> returns 0 for yes
  local q="$1" def="${2:-N}" ans
  if [ "$PROMPT" -eq 0 ]; then [ "$def" = "Y" ]; return; fi
  read -r -p "$q $( [ "$def" = Y ] && echo '[Y/n]' || echo '[y/N]' ): " ans
  ans="${ans:-$def}"; [[ "$ans" =~ ^[Yy] ]]
}

# ── 2. .env ─────────────────────────────────────────────────────────────────
step "Configuration (.env)"
if [ -f .env ]; then
  warn ".env already exists."
  if yesno "Back it up and create a fresh one?" "N"; then
    cp .env ".env.bak.$(date +%s)"; ok "backed up existing .env"
  else
    ok "keeping existing .env — skipping generation"
    SKIP_ENV=1
  fi
fi

if [ "${SKIP_ENV:-0}" -ne 1 ]; then
  AGENCY_NAME="${AGENCY_NAME:-$(ask 'Agency name (shown to leads)' 'My Realty Office')}"
  APP_ENV="${APP_ENV:-$(ask 'Environment (development|production)' 'production')}"
  KIMI_API_KEY="${KIMI_API_KEY:-$(ask_secret 'Kimi API key (sk-kimi-…) — blank to set later')}"
  MINIMAX_API_KEY="${MINIMAX_API_KEY:-$(ask_secret 'MiniMax API key (sk-cp-…) — blank to set later')}"

  # Where this dashboard will be reached. Google and Apple sign-in refuse raw
  # IP addresses, so an install answered only on a LAN address can never offer
  # them — the login page says so and names this address instead.
  CANONICAL_URL="${CANONICAL_URL:-$(ask 'Public URL of the dashboard (https://…) — blank if local only' '')}"

  # Cloudflare Turnstile for the public capture form. Both halves or neither:
  # the site key is baked into the frontend BUILD, the secret is read by the
  # backend at container start, and setting only the secret means the server
  # demands a token the page cannot produce — every visitor is refused and
  # every lead is lost. Blank on both is a fine answer; the form still has its
  # honeypot, per-IP limit and global ceiling.
  TURNSTILE_SITE_KEY="${TURNSTILE_SITE_KEY:-$(ask 'Cloudflare Turnstile SITE key for the contact form (blank = no captcha)' '')}"
  if [ -n "$TURNSTILE_SITE_KEY" ]; then
    TURNSTILE_SECRET="${TURNSTILE_SECRET:-$(ask_secret 'Cloudflare Turnstile SECRET key')}"
    if [ -z "$TURNSTILE_SECRET" ]; then
      echo "  → No secret given, so the captcha would be decorative: the widget"
      echo "    would render and the server would accept every submission"
      echo "    unverified. Turning it off entirely instead."
      TURNSTILE_SITE_KEY=""
    fi
  else
    TURNSTILE_SECRET=""
  fi

  PG_PASS="$(gen_secret)"
  APP_DB_PASS="$(gen_secret)"
  WA_VERIFY="$(gen_secret)"
  AUTH_SECRET="$(gen_secret)"

  # Dashboard auth: prompt for a password. If set → AUTH_ENABLED=true (secure by
  # default for a real install). Empty → open dashboard (dev / demo).
  DASHBOARD_PASSWORD="${DASHBOARD_PASSWORD:-$(ask_secret 'Dashboard password (protects /leads; blank = open)')}"
  AUTH_ENABLED=false
  [ -n "$DASHBOARD_PASSWORD" ] && AUTH_ENABLED=true

  # Channels stay SIMULATED unless the operator opts in (they need external accounts).
  WHATSAPP_SIMULATED=true; EMAIL_SIMULATED=true; CALENDAR_SIMULATED=true
  yesno "Enable WhatsApp now? (needs a Meta Business app — see docs/setup-whatsapp.md)" "N" && WHATSAPP_SIMULATED=false
  yesno "Enable email now? (needs a Resend account)" "N" && EMAIL_SIMULATED=false
  yesno "Enable Cal.com calendar now? (needs a Cal.com account — see docs/setup-calcom.md)" "N" && CALENDAR_SIMULATED=false

  bold "Writing .env (secrets are generated locally, never printed)…"
  umask 077
  cat > .env <<EOF
# Generated by scripts/install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
APP_NAME=Eko AI Realtors
APP_ENV=${APP_ENV}
DEBUG=$( [ "$APP_ENV" = production ] && echo false || echo true )
LOG_LEVEL=INFO

# Dashboard auth (Phase 11)
AUTH_ENABLED=${AUTH_ENABLED}
DASHBOARD_PASSWORD=${DASHBOARD_PASSWORD}
AUTH_SECRET=${AUTH_SECRET}
AUTH_TTL_HOURS=168

POSTGRES_USER=eko
POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_DB=eko_realestate
DATABASE_URL=postgresql+asyncpg://eko:${PG_PASS}@db:5432/eko_realestate
# The role the request path connects as. It has no BYPASSRLS, which is what
# makes the per-agency row-level policies bind. Generated per install: the
# default in docker-compose is a literal published in this repository.
APP_DB_PASSWORD=${APP_DB_PASS}
DATABASE_URL_APP=postgresql+asyncpg://eko_app:${APP_DB_PASS}@db:5432/eko_realestate
REDIS_URL=redis://redis:6379/0
INTERNAL_API_URL=http://backend:8000
# Not read by the app — `lib/api.ts` uses relative paths and next.config.js
# rewrites them — kept only so an older value cannot leak into a build.
NEXT_PUBLIC_API_URL=/api
# The address this dashboard is reached at. Shown to anyone who opens it
# somewhere Google and Apple sign-in cannot work — an IP, or plain http — so
# they are told where to go instead of hitting the provider's error page.
# Inlined at build time: changing it needs a rebuild, not a restart.
NEXT_PUBLIC_CANONICAL_URL=${CANONICAL_URL}

# Public capture form captcha. The SITE key is inlined into the frontend at
# BUILD time — changing it later needs `docker compose build frontend`, not a
# restart. The SECRET is read by the backend when the container is created.
TURNSTILE_SECRET=${TURNSTILE_SECRET}
NEXT_PUBLIC_TURNSTILE_SITE_KEY=${TURNSTILE_SITE_KEY}

# WhatsApp is off. A US brokerage reaches clients by text, call and email.
# Do not set this true with empty WhatsApp secrets: the same flag that stops
# simulating also turns on inbound HMAC verification, so every inbound webhook
# would return 403. The backend refuses to start in that state.
WHATSAPP_ENABLED=false

LLM_PRIMARY=kimi
LLM_FALLBACK=minimax
KIMI_API_KEY=${KIMI_API_KEY}
KIMI_BASE_URL=https://api.kimi.com/coding
KIMI_MODEL=kimi-for-coding
MINIMAX_API_KEY=${MINIMAX_API_KEY}
MINIMAX_BASE_URL=https://api.minimax.io/anthropic
MINIMAX_MODEL=MiniMax-M2.7

WHATSAPP_SIMULATED=${WHATSAPP_SIMULATED}
WHATSAPP_VERIFY_TOKEN=${WA_VERIFY}
WHATSAPP_APP_SECRET=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_BUSINESS_ACCOUNT_ID=
WHATSAPP_GRAPH_API_VERSION=v20.0

EMAIL_SIMULATED=${EMAIL_SIMULATED}
RESEND_API_KEY=
RESEND_FROM=${AGENCY_NAME} <noreply@example.com>
RESEND_WEBHOOK_SECRET=

CALENDAR_SIMULATED=${CALENDAR_SIMULATED}
CALENDAR_PROVIDER=calcom
CALCOM_BASE_URL=https://api.cal.com
CALCOM_API_KEY=
CALCOM_EVENT_TYPE_ID=
EOF
  ok ".env written (mode 600)"

  if [ "$APP_ENV" = production ] && [ "$WHATSAPP_SIMULATED" = true ]; then
    warn "APP_ENV=production but WhatsApp is SIMULATED — outbound will only be LOGGED."
    warn "Complete docs/setup-whatsapp.md and set WHATSAPP_SIMULATED=false before going live."
  fi
fi

# ── 3. build + start ─────────────────────────────────────────────────────
step "Building images (first run can take a few minutes)…"
$DC build
step "Starting the stack…"
$DC up -d
ok "containers up"

# ── 4. wait for backend, run migrations ─────────────────────────────────
step "Waiting for the backend to become healthy…"
HEALTH_URL="http://localhost:8011/api/v1/health"
for i in $(seq 1 40); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then ok "backend healthy"; break; fi
  [ "$i" -eq 40 ] && { err "backend did not become healthy — check: $DC logs backend"; exit 1; }
  sleep 3
done

step "Applying database migrations…"
$DC exec -T backend alembic upgrade head
ok "schema up to date"

# ── 5. branding ────────────────────────────────────────────────────────────
if [ "${SKIP_ENV:-0}" -ne 1 ] && [ -n "${AGENCY_NAME:-}" ]; then
  step "Setting agency branding to: $AGENCY_NAME"
  curl -fsS -X PUT "http://localhost:8011/api/v1/settings" \
    -H 'Content-Type: application/json' \
    -d "{\"agency_name\": $(printf '%s' "$AGENCY_NAME" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    >/dev/null && ok "branding set (edit more at /settings)" || warn "could not set branding — do it in the dashboard /settings"
fi

# ── done ─────────────────────────────────────────────────────────────────
step "Done 🎉"
cat <<EOF

  Dashboard   →  http://localhost:3004/leads
  Settings    →  http://localhost:3004/settings   (branding, persona, languages, hours)
  API (docs)  →  http://localhost:8011/docs
  Health      →  http://localhost:8011/api/v1/health

  Those are localhost on THIS machine — the ports are bound to 127.0.0.1 so a
  server with a public IP does not put the dashboard on the internet. If you
  installed on a remote box, open a tunnel from your laptop and then use the
  same URLs there:

    ssh -N -L 3004:127.0.0.1:3004 -L 8011:127.0.0.1:8011 <user>@<host>

  Next steps:
    • Configure branding + persona in the Settings page.
    • To enable channels: edit .env (WHATSAPP_/RESEND_/CALCOM_ keys), set the
      matching *_SIMULATED=false, then:  $DC up -d
    • To expose a public demo URL, see docs/setup-demo.md.
    • Useful: $DC logs -f backend   |   $DC ps   |   $DC down

EOF

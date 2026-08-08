# Installing Eko AI Realtors for a single office

Eko AI Realtors runs as one self-contained Docker Compose stack per real-estate
office (one deploy = one inmobiliaria). This guide covers a fresh install on the
office's own machine or VPS.

## Requirements

- **Docker** + the **Docker Compose** plugin (`docker compose version` works).
- ~2 GB RAM free, ~5 GB disk.
- Outbound HTTPS to the LLM providers (`api.kimi.com`, `api.minimax.io`) and, when
  enabled, to Meta / Resend / Cal.com.
- No GPU required — the LLM runs in the cloud (Kimi 2.6 primary, MiniMax M2.7
  fallback). On-prem LLM (Ollama) is optional and out of scope for the default install.

## Quick start (interactive)

```bash
git clone https://github.com/enderjnets/Eko-AI-RealEstate.git
cd Eko-AI-RealEstate
./scripts/install.sh
```

The installer:

1. Verifies Docker + Compose are present and the daemon is running.
2. Prompts for the **agency name**, **environment**, and (optionally) the **Kimi /
   MiniMax API keys**.
3. Generates a `.env` with **strong random secrets** (`POSTGRES_PASSWORD`,
   `WHATSAPP_VERIFY_TOKEN`). Secrets are written to `.env` (mode `600`, gitignored)
   and **never printed to the terminal**.
4. Leaves all channels (WhatsApp / email / calendar) in **SIMULATED** mode unless
   you explicitly opt in — so the stack boots and is fully clickable before any
   external account exists.
5. Builds the images, starts the stack, waits for the backend health check, and
   applies the database migrations (`alembic upgrade head`).
6. Sets the agency branding via the Settings API.

When it finishes you get:

| What | URL |
|---|---|
| Dashboard | http://localhost:3004/leads |
| Settings (branding / persona / languages / hours) | http://localhost:3004/settings |
| API docs (Swagger) | http://localhost:8011/docs |
| Health | http://localhost:8011/api/v1/health |

## Non-interactive install

For provisioning scripts:

```bash
AGENCY_NAME="Sunset Realty Group" \
APP_ENV=production \
KIMI_API_KEY=sk-kimi-… \
MINIMAX_API_KEY=sk-cp-… \
./scripts/install.sh --no-prompt
```

Any value not supplied via env var falls back to a safe default, and channels
stay SIMULATED.

## Turning on the real channels

Channels are off (SIMULATED) by default. To go live, fill the relevant keys in
`.env`, set the matching `*_SIMULATED=false`, then `docker compose up -d`:

| Channel | Keys in `.env` | Setup guide |
|---|---|---|
| WhatsApp | `WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | [`setup-whatsapp.md`](setup-whatsapp.md) |
| Email (Resend) | `RESEND_API_KEY`, `RESEND_FROM`, `RESEND_WEBHOOK_SECRET` | — |
| Calendar (Cal.com) | `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID` | [`setup-calcom.md`](setup-calcom.md) |

> ⚠️ Never ship `WHATSAPP_SIMULATED=true` with `APP_ENV=production` to a paying
> customer. The backend logs a warning at startup if it sees that combination —
> outbound messages would only be logged, not actually sent.

## Dashboard login (auth)

The installer asks for a **dashboard password**. If you set one, it enables auth
(`AUTH_ENABLED=true`) and the dashboard + data API require login at `/login`
(one shared password for the office; session is an httpOnly cookie). Leave it
blank for an open dashboard (dev / public demo only). To change it later, edit
`DASHBOARD_PASSWORD` in `.env` and `docker compose up -d`. The backend logs a
warning at startup if `APP_ENV=production` with auth off.

## Branding

Open **`/settings`** in the dashboard to configure:

- Agency name + phone (how the agent introduces itself)
- Agent persona (the system prompt — tone & behavior)
- Greeting template (`{agency_name}` is substituted)
- Languages the agent answers in (it auto-detects and matches the lead's language)
- Business hours (informational)

Changes apply immediately to new replies — no restart needed.

## Day-to-day operations

```bash
docker compose ps                 # status
docker compose logs -f backend    # follow backend logs
docker compose down               # stop (data persists in the postgres volume)
docker compose up -d              # start again
```

## Upgrading

Stop the backend before migrating. Starting the new image against the old
schema leaves every org-scoped query failing until the migration lands, and with
`restart: unless-stopped` a startup check that legitimately refuses becomes a
restart loop rather than a message you can read.

```bash
git pull
docker compose build

# Back up first: several migrations transform data (022 archives duplicate
# active conversations, 018 removes duplicate identity rows) and their
# downgrades do not put it back.
docker compose exec -T db pg_dump -U eko eko_realestate > backup-$(date +%F).sql

docker compose stop backend
docker compose run --rm backend alembic upgrade head
docker compose up -d
docker compose logs -f backend   # read the startup checks; they refuse loudly
```

### Before upgrading to 0.39.x

Three settings became load-bearing. The stack refuses to start without the
first, so check all three before you begin:

| Setting | Why |
|---|---|
| `AUTH_SECRET` | Required once `AUTH_ENABLED=true`, minimum 32 characters. It used to fall back to a value derived from `DASHBOARD_PASSWORD` — which the office shares — and that key signs both the organization and the platform-operator claim. `openssl rand -hex 32` |
| `PLATFORM_ADMIN_EMAILS` | The only source of platform access. Without it nobody can create an agency or reach Settings → Registrations, and the shared password deliberately cannot grant it. |
| `APP_DB_PASSWORD` | Must match the password inside `DATABASE_URL_APP`. The migration creates the RLS role inside the backend container and reads it there; left at the default, the role that guards every tenant boundary keeps the password published in this repository. |

Also note: users who were signing in purely on `GOOGLE_ALLOWED_DOMAIN` with no
`allowed_users` row are now refused rather than placed in the default
organization. Create their rows first, or they lose access at the cutover.

The Postgres data volume persists across upgrades; migrations are forward-only
and safe to re-run (`alembic upgrade head` is a no-op when already current).

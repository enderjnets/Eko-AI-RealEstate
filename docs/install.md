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

```bash
git pull
docker compose build
docker compose up -d
docker compose exec backend alembic upgrade head
```

The Postgres data volume persists across upgrades; migrations are forward-only
and safe to re-run (`alembic upgrade head` is a no-op when already current).

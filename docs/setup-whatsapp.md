# Setup — Meta WhatsApp Business Cloud API

> This is the **production** path. For dev / demo, leave `WHATSAPP_SIMULATED=true`
> and skip this doc entirely — the orchestrator works end-to-end with simulated
> outbound (logged instead of sent).

## Prerequisites

- A Meta / Facebook business account
- A phone number not currently registered in WhatsApp (or one you're willing to
  migrate out of the consumer app)
- A domain with HTTPS for the webhook callback (Cloudflare tunnel or a public
  IP with a real cert — Meta rejects self-signed)

## Step 1 — Create the Meta App

1. Go to https://developers.facebook.com/apps and click **Create App**.
2. Type: **Business**. App name: e.g. `Eko AI Realtors — Inmobiliaria Pérez`.
3. After creation, in the left sidebar, click **Add Product** → **WhatsApp** →
   **Set up**.
4. Meta gives you a test phone number + a temporary access token (good for 24h).
   For production, you'll add a real number and a permanent token later.

## Step 2 — Get the four secrets

In the WhatsApp panel of the Meta App, copy these into your `.env`:

```bash
# App Dashboard → Settings → Basic → App Secret (click "Show")
WHATSAPP_APP_SECRET=<32-char hex>

# A token YOU invent (used only by Meta to confirm you control the webhook).
# Any random ≥20-char string. Must match what you give Meta in step 4.
WHATSAPP_VERIFY_TOKEN=<your invented random string>

# WhatsApp → API Setup → Temporary access token (test phase)
# OR a permanent token from a System User (production)
WHATSAPP_ACCESS_TOKEN=EAAJ...

# WhatsApp → API Setup → "From" Phone number ID (NOT the phone number itself)
WHATSAPP_PHONE_NUMBER_ID=10987654321
```

## Step 3 — Flip simulated off

```bash
WHATSAPP_SIMULATED=false
```

Restart the backend container:

```bash
docker compose restart backend
```

The startup log should say `LLM primary=kimi fallback=minimax` and NOT show the
"WHATSAPP_SIMULATED=true AND APP_ENV=production" warning.

## Step 4 — Register the webhook

In the Meta App dashboard: **WhatsApp → Configuration → Webhook**:

- **Callback URL**: `https://<your-public-host>/api/v1/webhooks/whatsapp`
  (Cloudflare tunnel example: `https://inmo-demo.ekoaiautomation.com/api/v1/webhooks/whatsapp`)
- **Verify token**: the same string you put in `WHATSAPP_VERIFY_TOKEN`.
- Click **Verify and save**. Meta will GET your endpoint with `hub.mode=subscribe`,
  `hub.verify_token=<your token>`, and `hub.challenge=<random>`. Our handler
  echoes back the challenge if the token matches → green check.

Then click **Manage webhook fields** → subscribe to **messages**. (Other fields
like `message_template_status_update` are optional for Phase 1.)

## Step 5 — Smoke test

Send a WhatsApp from any phone to the test number Meta gave you. Watch the
backend logs:

```bash
docker compose logs -f backend
```

Expected sequence:

1. `INFO [app.api.v1.webhooks.whatsapp] WhatsApp webhook verified` (only on
   handshake — happens once at registration).
2. On each inbound message:
   `INFO [app.services.conversation] Created lead id=N phone=...`
   `INFO [app.services.llm] LLM ok provider=kimi model=kimi-for-coding in_tok=... out_tok=...`
   `INFO [app.services.conversation] Turn done: lead=N ... status=sent`

Verify the lead persisted:

```bash
curl http://localhost:8011/api/v1/leads
```

## Production checklist

- [ ] `WHATSAPP_SIMULATED=false` in `.env`
- [ ] `WHATSAPP_APP_SECRET` populated (signature verification activates when
      SIMULATED=false; without the secret, every inbound returns 403)
- [ ] Permanent access token from a System User (NOT the 24-h temp token)
- [ ] Public HTTPS URL with valid cert (not self-signed)
- [ ] `APP_ENV=production` in `.env`
- [ ] On startup the backend does NOT log the "SIMULATED+production" warning
- [ ] Send a real WhatsApp from your phone → check it lands in `/api/v1/leads`

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Webhook setup fails Meta validation | `WHATSAPP_VERIFY_TOKEN` mismatch | Compare `.env` value to what you typed in Meta dashboard (no trailing spaces) |
| All inbound POSTs return 403 | Wrong / missing `WHATSAPP_APP_SECRET` | Copy from Meta App → Settings → Basic → App Secret |
| Outbound sends fail with 401 | Access token expired (24h temp) | Generate a permanent token via System User |
| Customer gets no reply | Backend logs show LLM error | Check `KIMI_API_KEY` + `MINIMAX_API_KEY` are set; run `python scripts/llm_ab_test.py` to confirm |
| Customer sees the reply twice | Meta retried our webhook | Should NOT happen — we have UNIQUE constraint on `wa_message_id`. If it does, check logs for the second POST and inspect the orchestrator's idempotent-skip log line |

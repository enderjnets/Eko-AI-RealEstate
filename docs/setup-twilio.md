# Connecting real SMS (Twilio)

Eko AI Realtors speaks SMS through **Twilio Programmable Messaging**. In dev the
SMS channel runs SIMULATED (outbound is logged, the webhook accepts unsigned
requests), so it works end to end with no account. This guide wires a real
Twilio number for a pilot.

## 1. Get the credentials

From the [Twilio Console](https://console.twilio.com):

- **Account SID** — starts with `AC…` (Console home).
- **Auth Token** — Console home (keep it secret).
- **A phone number with SMS** — Phone Numbers → Manage → Buy a number (pick one
  with the **SMS** capability). E.164 format, e.g. `+13055551234`.

> Trial accounts work, but can only SMS **verified** numbers and prepend a trial
> banner. Upgrade for open testing.

## 2. Configure `.env`

On the host running the stack, set (never commit these — `.env` is gitignored):

```bash
SMS_SIMULATED=false
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+13055551234
# The exact public URL Twilio will call (must match what you set in step 3),
# used to validate X-Twilio-Signature behind a proxy/tunnel:
TWILIO_WEBHOOK_URL=https://your-domain.example.com/api/v1/webhooks/sms
```

Then `docker compose up -d` to pick them up.

## 3. Point the number's webhook at the backend

In the Console: **Phone Numbers → Manage → Active numbers → (your number) →
Messaging → "A message comes in"**:

- Webhook: `https://your-domain.example.com/api/v1/webhooks/sms`
- Method: **HTTP POST**

The webhook must be publicly reachable. For a quick test you can reuse the demo
Cloudflare tunnel hostname; for a customer install, use their own domain. The
URL here MUST match `TWILIO_WEBHOOK_URL` exactly (Twilio signs the URL it calls).

## 4. Test the round trip

Text the Twilio number from your phone. Expected:

1. Twilio POSTs the inbound to `/api/v1/webhooks/sms`.
2. The backend validates the signature, creates/updates the lead
   (`channel="sms"`), classifies intent, and scores it.
3. The AI reply is sent back via the Twilio REST API — you get an SMS reply.
4. The conversation shows up in the dashboard `/leads`.

Watch it happen:

```bash
docker compose logs -f backend | grep -iE "sms|twilio|turn done"
```

## How it works (for reference)

- **Inbound**: `app/api/v1/webhooks/sms.py` validates `X-Twilio-Signature`
  (HMAC-SHA1 over the request URL + sorted POST params, keyed by the auth token),
  then hands a `ParsedMessage(channel="sms")` to the orchestrator — the same path
  as WhatsApp and email.
- **Outbound**: `app/services/sms.py::send_sms` POSTs to
  `https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json`. The webhook
  returns empty TwiML; the reply is sent asynchronously after the LLM responds.
- **Idempotency**: Twilio retries on timeout; the UNIQUE constraint on
  `messages.external_id` (the `MessageSid`) dedupes.

## Cost & safety notes

- Each inbound + outbound SMS segment is billed by Twilio (fractions of a cent).
- A public SMS webhook + real number means anyone who texts the number triggers
  the agent (and an LLM call + an outbound SMS). For a public demo, prefer the
  SIMULATED mode; enable real Twilio on the customer's own deployment.
- Keep `SMS_SIMULATED=false` only where a real number is configured — the backend
  raises a clear error if `send_sms` runs without the `TWILIO_*` values.

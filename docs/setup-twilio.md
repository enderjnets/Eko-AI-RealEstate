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
TWILIO_AUTH_TOKEN=your-auth-token            # account's PRIMARY auth token (signs webhooks)
TWILIO_PHONE_NUMBER=+13055551234
# The exact public URL Twilio will call (must match what you set in step 3),
# used to validate X-Twilio-Signature behind a proxy/tunnel:
TWILIO_WEBHOOK_URL=https://your-domain.example.com/api/v1/webhooks/sms
# A2P 10DLC: once registered under a Messaging Service, set its SID so outbound
# goes through the registered campaign (recommended for US delivery):
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Track delivery status (delivered/undelivered + carrier error in the dashboard):
TWILIO_STATUS_CALLBACK_URL=https://your-domain.example.com/api/v1/webhooks/sms/status
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

## US A2P 10DLC registration (required for US delivery)

US carriers **filter/block** SMS from unregistered 10-digit long codes — messages
show `sent` on Twilio's side but never arrive (`undelivered`, error **30034**).
To deliver to US phones you must register **A2P 10DLC**:

1. Console → **Messaging → Regulatory Compliance → Onboarding**.
2. **Sole Proprietor** package (no EIN needed): cheapest/fastest for a single
   agent (~$4.50 brand + $15 campaign vetting + $2/mo, ~3,000 segments/day,
   1 msg/sec). Standard Brand needs an EIN but allows higher throughput.
3. Register the **Brand** (name, address, email, mobile for OTP) → **Campaign**
   (use case, sample messages, opt-in description) → attach your number to the
   resulting **Messaging Service**.

### ⚠️ Messaging Service webhook override

Once the number belongs to a **Messaging Service**, Twilio **ignores the
per-number webhook** and uses the Messaging Service's instead. Set the inbound
URL there: **Messaging → Services → (your service) → Integration → "Send a
webhook"** → `https://your-domain.example.com/api/v1/webhooks/sms` (POST). Also
set `TWILIO_MESSAGING_SERVICE_SID` in `.env` so outbound uses the campaign.

## Opt-out (STOP / HELP)

Twilio handles **STOP/UNSUBSCRIBE** (opt-out) and **HELP** keywords automatically
at the account / Messaging Service level (Advanced Opt-Out). When a lead texts
STOP, Twilio blocks further messages to them; our `send_sms` will then get an
error from Twilio (surfaced as a `failed` Message) rather than delivering. Keep
default opt-out enabled for compliance.

**"No extra code needed" applies to Twilio's own blocking, and only to SMS.** The
app enforces opt-out again at the dispatch boundary
(`app/services/delivery.py`), and that gate is what covers the two things Twilio
cannot see: a message already queued in our own scheduler *before* the lead
replied STOP, and the lead's other channels (WhatsApp, email). Do not read this
section as "the app needs no opt-out logic" — it has some, on purpose.

## Cost & safety notes

- Each inbound + outbound SMS segment is billed by Twilio (fractions of a cent).
- A public SMS webhook + real number means anyone who texts the number triggers
  the agent (and an LLM call + an outbound SMS). For a public demo, prefer the
  SIMULATED mode; enable real Twilio on the customer's own deployment.
- Keep `SMS_SIMULATED=false` only where a real number is configured — the backend
  raises a clear error if `send_sms` runs without the `TWILIO_*` values.

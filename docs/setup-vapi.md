# Voice agent setup — VAPI (Phase 13)

The voice channel uses [VAPI](https://vapi.ai) for the live call (Deepgram STT +
11labs TTS + a realtime LLM). VAPI runs the conversation and POSTs **server
messages** to our backend:

- `tool-calls` → answered **synchronously** so the assistant can act + speak the
  result mid-call (e.g. book a visit).
- `end-of-call-report` → the finished transcript is ingested into the lead
  timeline (`channel="voice"`).

There is **no outbound "send"** on this channel — the conversation happens live in
the call, so we only ingest the finished call. (Outbound calling — the agent
*calling* a lead — is deferred to a future phase.)

> When `VOICE_SIMULATED=true` (the default), the webhook accepts unsigned
> requests so dev + the public demo work without a VAPI account.

## 1. The assistant

One VAPI assistant backs the product: **"Eko AI Realtors"**. Its config (voice,
transcriber, model, system prompt, server webhook, tools) is applied via the VAPI
REST API — see `scripts/setup_vapi.sh` for the exact PATCH payload used. Key
choices:

| Field | Value | Why |
|---|---|---|
| `voice` | 11labs `EXAVITQu4vr4xnSDxMaL` (female, English) | Warm, natural English voice. |
| `transcriber` | Deepgram `nova-2`, `en` | Proven, low-latency. |
| `model` | `anthropic` `claude-sonnet-4-5` | Best instruction-following for qualification. Billed via the VAPI account — **NOT** our Claude Max OAuth (so it does not violate the product's no-Anthropic-OAuth rule). |
| `server.url` | `https://<host>/api/v1/webhooks/voice` | Where VAPI posts tool-calls + end-of-call. |
| `server.secret` | random string | Sent as `x-vapi-secret`; must equal `VAPI_WEBHOOK_SECRET`. |
| `serverMessages` | `["end-of-call-report","tool-calls","status-update"]` | What we listen for. |

### Tools (function calling, executed by our backend)

- `check_availability(days?)` → returns the next free visit slots (reuses
  `/calendar/slots` / Cal.com).
- `book_visit(datetime, property_address?, name?, phone?)` → books a `Visit` for
  the caller (resolved/created by their phone number) and confirms verbally.

The assistant prompt instructs the model to pass `datetime` as **ISO-8601 UTC**.

## 2. Phone number (inbound)

Assign a VAPI phone number to the assistant (in the VAPI dashboard or via the API:
`PATCH /phone-number/{id}` with `assistantId`). Callers to that number reach the
agent. For a web-call-only setup, no number is needed.

## 3. Backend env (`.env`, never committed)

```bash
VOICE_SIMULATED=false
VAPI_API_KEY=<vapi bearer>            # REST API (management / future outbound)
VAPI_WEBHOOK_SECRET=<same as server.secret on the assistant>
VAPI_ASSISTANT_ID=<assistant id>
VAPI_PHONE_NUMBER_ID=<phone number id>
```

Then recreate the backend (env is read at runtime; no rebuild needed):
`docker compose up -d backend`. No DB migration — `Conversation`/`Message`/`Visit`
already exist.

> `book_visit` needs `CALENDAR_SIMULATED=true` (default) **or** real Cal.com
> credentials (`CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID`). Without either, the
> tool returns a graceful "a team member will follow up" message.

## 4. Verify

1. `POST /api/v1/webhooks/voice` **without** `x-vapi-secret` → **403** in live
   mode (confirms the secret check is active).
2. Call the number, qualify, ask to book a visit → the agent confirms a time
   (tool-call) and, on hang-up, the lead appears in `/leads/{id}` with the voice
   transcript (🗣️), intent/score, and the visit in the Visits section.
3. Logs: `docker compose logs -f backend | grep -iE "voice|vapi|tool|end-of-call"`.

## Security note

A public inbound number means anyone who calls it triggers the agent (VAPI minutes
+ LLM cost). Monitor usage in the VAPI dashboard for the first days; to disable,
unassign the number from the assistant (or set `VOICE_SIMULATED=true`).

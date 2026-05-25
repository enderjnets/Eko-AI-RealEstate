# Setup — Cal.com calendar booking

> This is the **production** path. For dev / demo, leave `CALENDAR_SIMULATED=true`
> and skip this doc — the dashboard's BookingDialog generates fake weekday slots
> in-memory and persists `calcom-sim-<uuid>` bookings without any external call.

## Why Cal.com

- Free tier covers a single realtor (1 calendar + unlimited bookings).
- v2 API exposes `/slots/available` (list slots) and `/bookings` (create / cancel),
  which is everything Phase 5 needs.
- The realtor's existing Google / Outlook / iCloud calendar plugs into Cal.com
  as a destination, so confirmed bookings show up where they already work.

## Step 1 — Create the Cal.com account + Event Type

1. Sign up at https://cal.com.
2. **Settings → Calendars** — connect the realtor's Google / Outlook calendar
   so bookings end up there.
3. **Event Types → New** — create one called e.g. *"Visita propiedad"*. Set the
   duration to **30 minutes** (matches our default). Note the **Event Type ID**
   in the URL (`https://app.cal.com/event-types/<ID>`).

## Step 2 — Get the API key

1. **Settings → Developer → API keys → Add**.
2. Scope: at minimum `bookings:read` + `bookings:write` + `slots:read`. The
   simpler "all scopes" key works too.
3. Copy the key — you only see it once.

## Step 3 — Configure the backend

Put these in `.env`:

```bash
CALENDAR_SIMULATED=false
CALCOM_BASE_URL=https://api.cal.com
CALCOM_API_KEY=<your key here>
CALCOM_EVENT_TYPE_ID=<event type id from step 1>
```

Restart the backend:

```bash
docker compose restart backend
```

## Step 4 — Smoke test

```bash
# List slots for any lead (the slots are global per event type — they don't depend on the lead).
curl http://localhost:8011/api/v1/leads/15/calendar/slots?days=7&timezone=Europe/Madrid

# Book the first slot.
curl -X POST -H "Content-Type: application/json" \
     -d '{"start_time":"2026-05-26T10:00:00+02:00","timezone":"Europe/Madrid"}' \
     http://localhost:8011/api/v1/leads/15/calendar/book
```

The booking should appear in the realtor's Cal.com dashboard within a second,
and on the connected Google/Outlook calendar within a minute.

## Step 5 — Cancellation behavior

`POST /api/v1/visits/{id}/cancel` calls Cal.com's
`POST /v2/bookings/{id}/cancel` and then sets `Visit.status = cancelled`.
The realtor's Google/Outlook event disappears automatically.

**Special case**: any `external_booking_id` that starts with `calcom-sim-`
(left over from SIMULATED mode bookings during dev) is cancelled locally
without an API call, so you can clean up dev data even in production mode.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/slots` returns 503 "Cal.com unavailable" | Missing API key or event type id | Re-check `.env` and `docker compose restart backend` |
| `/book` returns 503 with `attendee_email is required` | Lead has no email — Cal.com requires one for real bookings | For phone-only leads, store a placeholder email like `<phone>@whatsapp.invalid` on the Lead, OR stay in SIMULATED mode for that lead |
| Bookings work but don't appear in the realtor's Google Calendar | Cal.com isn't connected to the realtor's calendar | Re-do Step 1.2 in Cal.com — Settings → Calendars |
| `/v2/...` requests return 401 | API key revoked or wrong scope | Generate a new key |
| `cal-api-version` header mismatch | Cal.com sometimes bumps the required header version | Update the value in `app/services/calendar_cal.py` (currently `2024-08-13`) |

## What's out of scope (Phase 5)

- **Google Calendar direct integration** — Phase 5 picks Cal.com only; Google
  OAuth comes later if a customer asks.
- **Auto-booking from the AI agent** — Phase 5 V1 keeps booking in the
  dashboard (the realtor clicks the slot). A future phase can give the agent
  function calling so it books automatically when the lead asks for a visit.
- **Recurring availability windows beyond Cal.com's event-type config** — use
  Cal.com's own UI for that.
- **Multi-realtor / round-robin** — Cal.com supports it natively (teams); the
  backend will work as-is, you just point `CALCOM_EVENT_TYPE_ID` at a team
  event type.

# Onboarding a client agency

Five steps. Each one alone leaves something unusable — an organization nobody
can log into, a login with no way to receive leads, or an agency whose replies
go out from your number — so do them in order.

## Becoming a platform operator first

All of these are platform-operator routes, and they need the `su` claim. Exactly
one thing issues it: **an email listed in `PLATFORM_ADMIN_EMAILS` signing in
with Google or Apple.** Set that variable to your own address, restart, and sign
in with it. There is no other way in, deliberately.

The shared `DASHBOARD_PASSWORD` is **not** one of them, and never becomes one.
It is the agency's password — `install.sh` describes it as protecting `/leads`
and the office shares it with whoever answers the phone — so letting it mint
platform access, even as a fallback for a fresh install, put every tenant one
front-door login away from a receptionist.

These routes also stay closed when `AUTH_ENABLED=false`, unlike every other
gate in the app — in that mode tokens are signed with a constant published
in this repository, so a claim proves nothing. They also re-read
`PLATFORM_ADMIN_EMAILS` on every request rather than trusting the claim, so
removing someone from that list retires their access immediately instead of
whenever their week-long session happens to expire.

Being an admin of the default organization is *not* enough, and used not to be
distinguishable: org 1 is a real client agency (`client-zero`), so its admins
inherited platform rights, and so did any session predating multi-tenancy.
An agency's own admin gets 403 here.

## 1. Create the organization

```bash
curl -X POST "$API/api/v1/platform/organizations" \
  -b cookies.txt -H 'content-type: application/json' \
  -d '{"name": "Cherry Creek Realty", "slug": "cherry-creek"}'
```

Returns the `id`. `status` starts `active`; `plan` defaults to `pilot`.

## 2. Route their inbound destinations

**This is the step that cannot be skipped.** An inbound message is attributed
to an agency by *where it arrived* — nothing else can tell tenants apart. An
unmapped destination is refused with 503 rather than filed under another agency.

```bash
# One call per channel the agency uses.
curl -X POST "$API/api/v1/platform/routes" -b cookies.txt \
  -H 'content-type: application/json' \
  -d '{"org_id": 3, "channel": "sms", "destination": "+13035551234"}'
```

| Channel | What `destination` is |
|---|---|
| `sms` | The Twilio number clients text |
| `whatsapp` | The WhatsApp Business `phone_number_id` (preferred over the display number — it survives reformatting and porting) |
| `email` | The mailbox that receives inbound mail |
| `voice` | The VAPI number that gets called |

Destinations are normalised, so `+1 (303) 555-1234` and `13035551234` are the
same route. A destination already claimed by another agency returns 409 — one
number, one agency, deliberately.

## 3. Invite their first admin

```bash
curl -X POST "$API/api/v1/platform/organizations/3/members" \
  -b cookies.txt -H 'content-type: application/json' \
  -d '{"email": "owner@cherrycreek.com", "role": "admin"}'
```

That person can then sign in with Google or Apple and manage their own team
from Settings → Team. A 409 means the email already belongs to another
organization: identity is global, one person to one agency.

## 4. Point the route at their own provider account

Skip this and the agency still *receives* correctly, but every reply goes out
from **your** number and address. Their lead answers you, `To` matches your
route, and the rest of their conversation is written into your tenant. Startup
logs a warning naming any agency still in this state.

Put their credentials in `.env` under names of your choosing, restart, then
record the names — never the values, which stay in `.env`:

```bash
# .env
TWILIO_SID_CHERRY_CREEK=AC...
TWILIO_TOKEN_CHERRY_CREEK=...
```

```bash
curl -X PATCH "$API/api/v1/platform/routes/7/identity" -b cookies.txt \
  -H 'content-type: application/json' \
  -d '{"provider_account_ref": "TWILIO_SID_CHERRY_CREEK",
       "credential_ref": "TWILIO_TOKEN_CHERRY_CREEK",
       "inbound_secret_ref": "TWILIO_TOKEN_CHERRY_CREEK",
       "webhook_url": "https://api.example.com/api/v1/webhooks/sms"}'
```

`inbound_secret_ref` is what lets their inbound messages pass signature
verification — for Twilio it is the same auth token. `webhook_url` must match
the URL configured in their console exactly, or every signature fails.

A 400 listing `environment_variables_not_set` means you recorded a name you
have not set (or have not restarted since setting). That check exists because
the alternative is a route that fails at a lead's first message instead of
here.

An agency that uses *your* provider account with its own number needs none of
this: leave the refs null and only the destination is theirs.

## 5. Check it landed

```bash
curl "$API/api/v1/platform/organizations" -b cookies.txt   # the new org is listed
curl "$API/api/v1/platform/routes" -b cookies.txt          # destinations and credential names
```

Then send a real message to the routed number and confirm two things: the lead
appears in that agency's dashboard and nobody else's, **and the reply arrives
from their number**. The second half is the one that used to be wrong.

## Suspending an agency

```bash
curl -X PATCH "$API/api/v1/platform/organizations/3" -b cookies.txt \
  -H 'content-type: application/json' -d '{"status": "suspended"}'
```

Takes effect within about 15 seconds (the resolver caches the org list). A
suspended agency loses API access immediately, its background follow-ups stop,
and its inbound destinations stop resolving.

## Entering an agency for support

```bash
curl -X POST "$API/api/v1/platform/impersonate/3" -b cookies.txt -c cookies.txt
```

Swaps your session for one acting inside that organization. **Recorded in
`user_activity` before the cookie is issued** — deliberately, so there is always
an answer to "who looked at our data?". Log out and back in to return to your
own.

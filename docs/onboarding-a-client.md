# Onboarding a client agency

Four steps. Each one alone leaves something unusable — an organization nobody
can log into, or a login with no way to receive leads — so do them in order.

All of these are platform-operator routes. They require an `admin` session
**whose organization is the default one**; an agency's own admin gets 403.
That distinction exists because `require_admin` authorises the admin of *some*
organization, and every client has one.

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

## 4. Check it landed

```bash
curl "$API/api/v1/platform/organizations" -b cookies.txt   # the new org is listed
curl "$API/api/v1/platform/routes" -b cookies.txt          # its destinations are mapped
```

Then send a real message to the routed number and confirm the lead appears in
that agency's dashboard — not in anyone else's.

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

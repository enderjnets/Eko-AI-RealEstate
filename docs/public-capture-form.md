# The public capture form

`POST /api/v1/public/leads` + the `/contact` page. The only route in this
product a stranger is meant to reach, and the only way someone who saw a video
becomes a lead: every other channel needs them to already have the agency's
phone number or email address.

## What it is for

Two things, and the second is the one people forget:

1. **Turn a viewer into a lead.** The link goes in the bio on TikTok,
   Instagram and YouTube. A submission lands in the Inbox exactly like a
   WhatsApp message does — same lead record, same conversation view, same
   Reply button.
2. **Record which video sent them.** The UTM parameters on the link are stored
   on the lead. Without this you can only ever look at view counts, and view
   counts do not pay. With it you can ask which of forty videos produced an
   appointment, and publish more of those.

## Which agency a submission belongs to

A form post carries no session, so nothing in the request proves who is
asking. Since the multi-tenant work, an unauthenticated request resolves to no
organization at all and — under default-deny RLS — writes nothing.

The answer reuses the mechanism that already decides which agency an inbound
SMS belongs to: `channel_routes`. A row with `channel='web'` maps a **form
key** (the opaque slug embedded in the landing page) to an organization.

```sql
-- via POST /api/v1/platform/organizations/{id}/routes, not by hand
channel = 'web'
destination = 'natalia-denver'   -- the form key
```

That inherits, already tested, the guarantees this needs:

- **Globally unique** — two agencies cannot claim the same key.
- **The demo organization is refused.** `POST /auth/register` drops any
  anonymous visitor into it as a viewer, so a lead filed there is a lead
  published.
- **Suspended organizations are refused.**
- **Single-tenant fallback.** An install with exactly one agency needs no
  route and no form key at all — which is why Natalia's install works with
  nothing configured.

Set the key in the frontend build with `NEXT_PUBLIC_CAPTURE_FORM_KEY`. Leave
it empty on a single-agency install. **Once a second agency exists, a
submission with no key is refused with 404** — a public endpoint that quietly
defaults to the first tenant is how one agency's leads end up in another's
dashboard.

## Request

```json
POST /api/v1/public/leads
{
  "form": "natalia-denver",
  "name": "Jane Watcher",
  "email": "jane@example.com",
  "phone": "(303) 555-1234",
  "message": "Saw your Wash Park video, looking under 1M",
  "consent": true,
  "consent_text": "<the exact wording rendered on the page>",
  "utm": { "utm_source": "tiktok", "utm_content": "denver-washpark-01" },
  "turnstile_token": "…",
  "website": ""
}
→ 202 {"ok": true}
```

| Code | Meaning |
|---|---|
| 202 | Accepted. Says nothing about whether the lead was new, merged or a duplicate — that would be a membership oracle for testing whether an address is in an agency's book. Also returned for a honeypot hit. |
| 400 | Turnstile rejected or unreachable. |
| 404 | Unknown form key, a key pointing at the demo org, or no key on a multi-agency install. Deliberately not distinguishable — otherwise this endpoint enumerates an operator's tenants. |
| 422 | `contact_required` (neither email nor phone), `consent_text_required` (box ticked with no wording), or a body pydantic rejected. |
| 413 | Body over 256 KB, refused at the ASGI layer before pydantic materialises it. |
| 429 | Rate limited (per-IP, or the platform-wide ceiling). |

### Fields

- **Identifier.** Phone if given, else email. The phone is normalised to E.164
  — `(303) 555-1234`, `303-555-1234` and `+1 303 555 1234` all become
  `+13035551234`, so the form does not manufacture a duplicate of every lead
  who later replies by SMS. `CAPTURE`'s `DEFAULT_CALLING_CODE` is `1`; change
  it for a non-US install.
- **Repeat submissions merge.** `leads` is unique on `(org_id, phone)`. A
  second submission updates the same lead; it does not 500.
- **Attribution.** Whitelisted keys only (`utm_source`, `utm_medium`,
  `utm_campaign`, `utm_content`, `utm_term`, `gclid`, `fbclid`,
  `landing_variant`, `tier`, `referrer`), 200 characters each. **First touch
  wins** — a later submission is appended under `attribution_later`, never
  written over the first. The question is which video found them, and
  overwriting credits whatever they saw last.

## Consent (TCPA)

Four columns on `leads`, not a key in `meta`: `consent_at`, `consent_text`,
`consent_ip`, `consent_user_agent`. The obligation is to show **what the person
was reading** when they agreed, so a bare timestamp defends nothing. `consent:
true` without `consent_text` is refused rather than stored.

`may_send_automated(lead, channel, db)` gates the nurture worker. An automated
SMS or WhatsApp goes out only if the lead consented **or** has sent us an
inbound message on that same channel (consumer-initiated contact). Email is not
gated — CAN-SPAM asks for a working unsubscribe, not prior consent.

The case this catches is quiet: a web lead who did not tick the box, then one
manual SMS from the agent — which creates an SMS thread — and from then on the
worker has a sendable channel and no permission to use it.

## Abuse defences

| Defence | Detail |
|---|---|
| Body cap | 256 KB, enforced in ASGI middleware that buffers-and-replays: `Content-Length` is a claim rather than a measurement, and a chunked request carries none. **Per path** — `/api/v1/discovery/upload` keeps its documented `FILE_IMPORT_MAX_MB`; a single global cap tight enough for this form silently refused a realtor's 750 KB contact export. Registered inside CORS so the 413 is readable by a browser on another origin. |
| Per-IP limit | 5 per 10 minutes, charged **before** the honeypot. The honeypot used to return first, which made `{"website": "bot"}` a completely unmetered endpoint. |
| Honeypot | A `website` field, positioned off-screen. Filled in → 202 and nothing written, indistinguishable from success so a bot gets no tuning feedback. |
| **Global ceiling** | **60 per 10 minutes**, charged after the captcha and **before the tenant lookup**. Charged first, it was a kill switch anyone could hold down — sixty tokenless posts from sixty forged addresses each got a 400 and each still spent a slot. Charged last, resolving a form key is a database round trip that a caller rotating the IP header could drive without limit, because the per-IP budget resets with every forged address. |
| Turnstile | Off while `TURNSTILE_SECRET` is empty — check `/api/v1/health` → `captcha`, because an unset secret accepts everything and looks identical to a working captcha from outside. Configured, it is mandatory **and fail-closed** — if Cloudflare cannot be reached the submission is refused, because a captcha that passes everyone during an outage is not a captcha. |

The order — body cap, per-IP, honeypot, shape, captcha, global budget, tenant —
is itself a defence, and each step moved there because of a specific way the
previous order was exploitable.

The rate counters live in the process. That is correct only because the app is
pinned to one uvicorn worker — the same constraint `main.py` documents for the
background loops. Under `--workers N` they become N independent budgets.

The ceiling cuts both ways: a flood of 60 submissions per 10 minutes locks out
real visitors for the rest of the window. The ceiling is the backstop;
Turnstile is the actual answer, which is a reason not to leave it off for long.

## Opting out (STOP)

The disclosure the visitor reads — and which is stored verbatim as the consent
record — promises "reply STOP to opt out". That is a term of the agreement the
record documents, so it is implemented, by keyword and not by the model:

- **Recognised**: the CTIA set (`STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`,
  `END`, `QUIT`, `OPTOUT`, `REVOKE`) plus the Spanish a bilingual Denver
  audience actually types (`BAJA`, `PARAR`, `CANCELAR`, `DETENER`). Whole
  message only, punctuation ignored — "can I stop by the open house?" is a live
  buyer, not a revocation.
- **Channels**: sms, whatsapp, voice. An email unsubscribe is a link and a
  `List-Unsubscribe` header, not a one-word reply.
- **Effect**: `leads.opted_out_at/_channel/_keyword` are set, exactly one
  confirmation is sent, **the model is never called**, and
  `may_send_automated` returns False from then on — outranking written consent,
  because an instruction to stop is the more recent statement of what the
  person wants.
- **Scope: every channel, including email.** Broader than the law requires —
  CAN-SPAM would permit still emailing someone who only texted STOP, and the
  letter of TCPA is per channel. The cost of reading it narrowly is a person
  who asked us to stop and kept hearing from us; the cost of reading it broadly
  is bounded, because this gate covers **automated** messages only and a
  realtor can still write to them personally.
- **Coming back**: `START`, `ALTA`, `RESUME`, `UNSTOP`, `OPT IN` clear it.
  **Not** `yes` / `si` / `sí` — they were, and they are the most common single
  word a person sends, so a lead who had opted out and answered "Sí" to
  anything at all resubscribed themselves. CTIA requires START and UNSTOP; it
  does not require agreement words, and reading agreement as re-consent is
  backwards.
- **It lasts.** Every later message from that lead is stored and shown in the
  Inbox but gets **no** automated reply — the revocation is not spent by the
  turn that carried it. And the retry sweep drops anything that was already
  queued when it arrived, because the gate belongs at the dispatch boundary and
  not only at the producer.
- **`cancelar` is deliberately NOT a stop word.** `CANCEL` is in the CTIA set
  and stays; its Spanish cognates are required by nobody and are what a
  bilingual client types about a *viewing*. Silencing a live buyer is the worse
  error and the one they cannot undo without knowing about START.
- Phone keyboards substitute curly quotes, ellipsis characters and em dashes.
  `stop…` and `“STOP”` are matched — a revocation that fails because the
  keyboard was helpful is a revocation that did not happen.
- The dashboard **shows it**: an amber banner on the lead, and the AI badge
  reads "Opted out" instead of "AI agent active", which would otherwise be a
  control stating something false about what the system will do.

Why keyword and not the LLM: a revocation has to be recognised when the model
is down or slow, has to behave identically every time, and has to agree with
the carriers — who intercept STOP at the aggregator regardless of what the
application decides.

**The order in `may_send_automated` is load-bearing.** The opt-out check runs
first. Placed after the consumer-initiated branch it would be satisfied by
STOP itself, since STOP arrives as an inbound message on the channel — the gate
inverted by exactly the input it exists to obey. That was a real defect, found
by audit, and `tests/test_optout.py` pins it.

## Turning the captcha on

Turnstile is the only defence here a determined script cannot outspend, and it
is **off** until both halves are set. Both halves, in this order — the ordering
is not symmetric and getting it backwards costs every lead until it is fixed.

1. **Cloudflare** → Turnstile → add a widget, scoped to the hostname the form
   is served from (`inmo-demo.ekoaiautomation.com`). A widget bound to a
   different hostname fails when the visitor solves it. You get a **site key**
   (public) and a **secret key**.
2. Put both in the root `.env`:
   ```
   NEXT_PUBLIC_TURNSTILE_SITE_KEY=0x4AAA…
   TURNSTILE_SECRET=0x4AAA…
   ```
3. **Rebuild the frontend.** `NEXT_PUBLIC_*` is inlined at compile time, so
   `docker compose up -d` alone will not pick up the site key:
   ```
   docker compose build frontend
   docker compose up -d
   ```
   The backend needs the **recreate** that `up -d` does, not `restart` — a
   container's environment is fixed when it is created.

**Why the order matters.** Site key first is fail-OPEN: the widget renders,
submissions are accepted unverified, leads still arrive. Secret first is
fail-CLOSED: the server demands a token the page cannot produce, every visitor
is told *"we couldn't verify that you're human"*, reloading never helps, and
**100% of leads are lost** with nothing logged server-side. If both go together
in one build + recreate, neither window opens.

**Verify it is actually on** — the failure is silent acceptance, so the form
looking fine proves nothing:

```
curl -s https://<host>/api/v1/health | jq .captcha    # "on"
```

Then submit a real lead in a browser. A `curl` returning 202 proves nothing:
with the secret unset, `curl` gets 202 too.

## If the form moves to its own domain

Today `/contact` is served by the same Next.js app that proxies `/api`, so the
POST is same-origin and CORS never comes into it. The content plan puts the
landing page on its own domain later. On that day the new origin must be added
to `CORS_ORIGINS` in the backend `.env`, or every submission fails in the
browser with no server-side trace at all.

## Known limits

- **No LLM classification.** Webhook turns run a classifier that fills
  `intent`, `zone` and `budget`. This endpoint does not: a paid model call
  behind an unauthenticated POST is a bill anyone can run up, and the rate
  ceiling still permits 8,640 calls a day. Web leads arrive with those fields
  empty, which also means property matching does not fire for them until a
  human or a later inbound sets them.
- **No auto-reply.** `web` is not in `SENDABLE_CHANNELS` — nothing can be
  delivered to a form. The lead sits in the Inbox as pending and a person
  answers, which is what §9 of the content plan asks for in the first weeks.
- **Consent is only as good as the form.** A forged POST can tick the box with
  somebody else's phone number. Inherent to all web consent; the industry
  answer is the IP and user-agent record this stores, plus Turnstile, plus an
  opt-out in the first automated message.

## Verifying a deployment

Do this in a browser, not with curl — a 202 is not verification:

1. Open `/contact?utm_source=tiktok&utm_content=<a real video id>`
2. Fill it in as a visitor would; tick the box.
3. The lead is in the Inbox, badged **Web form**, with a non-zero score.
4. In Postgres, that lead carries the `utm_content` and a `consent_at` with
   the wording, IP and user agent.

---

# The landing beacon — `POST /api/v1/public/landing`

The form tells you who wrote. This tells you who *read* — and without it "the
video brought a hundred people and two wrote" and "the video brought two people
and both wrote" are the same picture, while calling for opposite decisions.

## What it stores

One `landing_sessions` row per visit, rolled up as the visit goes: where they
came from (`source`, derived from the UTM or the referrer host), the device,
browser and OS **families**, the in-app browser if it is one, the country and —
when Cloudflare's "Add visitor location headers" transform is on for the zone —
the region and city, how far they scrolled, which sections they reached, taps
on *call* and on the consult form, whether the form was started and submitted,
and the lead it became if it became one.

Behind it, `landing_events` holds the raw stream, deleted after
`LANDING_EVENTS_RETENTION_DAYS` (90). **Reports read the session, never the
events** — the session carries the same facts already merged, so the numbers do
not change when the purge runs.

## What it does not store, and why that is the whole design

- **No cookie and no persistent identifier.** The session key lives in
  `sessionStorage`; it dies with the tab and cannot follow anybody anywhere.
- **No IP address.** It is read for the rate limit and dropped.
- **No raw user agent.** Reduced to families (`phone` / `Chrome` / `iOS`)
  before it is written; the full string is close enough to a fingerprint that
  keeping it would undo not setting a cookie.

Because of those three, this is not tracking in the sense a cookie banner
exists for. A privacy notice is still the right thing to publish, and the
Global Privacy Control signal is honoured by the page: with it set, the tracker
sends nothing at all.

## Contract

`text/plain` body — `navigator.sendBeacon` cannot reliably send JSON — parsed
by hand. At most **16 KB** and **25 events** per batch; a closed set of event
names (`page_view`, `section_view`, `scroll`, `cta_click`, `tel_click`,
`form_start`, `form_submit`, `form_error`); metadata of at most five short
keys. Its own rate budget (60 per address per 10 minutes, 3,000 platform-wide),
**separate from the form's** — one attentive visitor sends four beacons, and
sharing the form's budget of five would mean reading the page carefully costs
you the ability to submit it.

**`LANDING_SESSIONS_PER_DAY` (20,000) is the control that actually bounds the
table**, and it is worth being clear about why the rate limit is not. Sixty
posts per address per ten minutes is 8,640 permanent session rows a day from a
single address, and sessions are never deleted by age — deleting them would
rewrite the denominator of every historical funnel. So the cap is on **creating**
a session, per agency, per local day. A visit already being recorded keeps
merging its beacons after the cap is reached, so a real visitor is never
truncated mid-page; only somebody inventing session keys is stopped. It is
logged once per agency per day when it trips.

Every counter is written as a SQL expression (`cta_clicks + :n`,
`GREATEST(max_scroll_pct, :pct)`, `COALESCE(form_started_at, :now)`), never as a
number computed in Python from a row that was read a moment earlier. Two
beacons for the same visit are normal — `sendBeacon` fires on both
`visibilitychange` and `pagehide` — and folding them in the process loses
clicks and lets the scroll depth go *down*.

**Always 204**, including when it declines: an endpoint that answers
differently for a valid and an invalid form key is an oracle for enumerating an
operator's tenants, and a beacon has nothing useful to do with the difference.

## Joining a visit to its lead

The form sends `session_id` alongside the rest. It is a **separate field, not
an attribution key**: the whitelist in `services/capture.py` means "which
campaign produced this lead" and is pinned by a test, an assert and this
document — a per-visit identifier is not that and must never reach `lead.meta`.
The join is applied after the lead is committed and notified, wrapped, because
a failure there must cost a row in a report and never a resubmission. For the
same reason the field carries **no shape pattern**: a `pattern` would reject the
whole submission with 422, so a bug in the tracker's key generator would stop
costing an analytics row and start costing the lead. The shape is checked where
it is used, and a value that does not match is simply not looked up.

**`form_submitted_at IS NOT NULL AND lead_id IS NULL`** is the funnel step that
would otherwise be invisible: the visitor pressed send and no lead ever arrived
— a captcha refusal, a dropped connection. The page's own `form_submit` beacon
writes the timestamp, so this survives even when the submission never reached
the server.

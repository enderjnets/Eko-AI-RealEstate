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
| Body cap | 256 KB, enforced in ASGI middleware on both `Content-Length` and the stream, because the header is a claim rather than a measurement. There is no reverse proxy — the tunnel points straight at uvicorn — and a 43 MB body was previously parsed and answered 202. |
| Per-IP limit | 5 per 10 minutes, charged **before** the honeypot. The honeypot used to return first, which made `{"website": "bot"}` a completely unmetered endpoint. |
| Honeypot | A `website` field, positioned off-screen. Filled in → 202 and nothing written, indistinguishable from success so a bot gets no tuning feedback. |
| **Global ceiling** | **60 per 10 minutes**, charged **last** — after the captcha. Charged first, it was a kill switch anyone could hold down: sixty tokenless posts from sixty forged addresses each got a 400 and each still spent a slot. |
| Turnstile | Off while `TURNSTILE_SECRET` is empty. Configured, it is mandatory **and fail-closed** — if Cloudflare cannot be reached the submission is refused, because a captcha that passes everyone during an outage is not a captcha. |

The order — body cap, per-IP, honeypot, shape, captcha, tenant, global budget —
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
- **Coming back**: `START`, `ALTA`, `RESUME`, `UNSTOP` clear it.

Why keyword and not the LLM: a revocation has to be recognised when the model
is down or slow, has to behave identically every time, and has to agree with
the carriers — who intercept STOP at the aggregator regardless of what the
application decides.

**The order in `may_send_automated` is load-bearing.** The opt-out check runs
first. Placed after the consumer-initiated branch it would be satisfied by
STOP itself, since STOP arrives as an inbound message on the channel — the gate
inverted by exactly the input it exists to obey. That was a real defect, found
by audit, and `tests/test_optout.py` pins it.

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

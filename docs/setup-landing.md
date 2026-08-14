# Setup — the public landing (`/`)

Since v0.44.0 the root of the install is the agency's public marketing page,
not the dashboard. Staff sign in at `/login`, which still lands on `/leads`;
there is a discreet link at the foot of the landing.

The page is a port of the approved Claude Design mockup, kept in the repo at
[`docs/design/natalia-robbie-landing-v2.html`](design/natalia-robbie-landing-v2.html)
as the visual reference.

## The rule that shapes the whole page

**Nothing factual is hardcoded, and nothing unconfigured is invented.**

Every name, number, address and quote comes from a `NEXT_PUBLIC_LANDING_*`
variable. A variable you leave empty makes the thing that needs it disappear —
the stat strip, the "Reach us" section, the testimonials, the hero portrait.

That is deliberate, not an oversight. This page advertises a licensed
real-estate brokerage. A placeholder phone number, an invented tenure figure or
a made-up client testimonial on it is a false statement to a consumer, which
Colorado's advertising rules and the FTC both reach. An empty section is
merely incomplete; a fabricated one is a liability that lands on the broker's
licence.

## Build time, not run time

Like every `NEXT_PUBLIC_*`, these are **inlined when the frontend image is
built**. Editing `.env` and restarting changes nothing — you must rebuild:

```bash
docker compose build eko-realestate-frontend && docker compose up -d eko-realestate-frontend
```

Each variable has to appear in four places to survive the trip: `.env.example`
(documentation), `docker-compose.yml` (build arg), and the frontend
`Dockerfile` as both `ARG` and `ENV`. Miss one and Next inlines an empty string
while your `.env` looks perfectly filled in. `frontend/lib/__tests__/landingConfigWiring.test.ts`
fails the build if any of the four is missing — that is the guard, and it is
there because this install has already lost eighteen settings that way.

## The variables

| Variable | What it drives | Empty means |
|---|---|---|
| `NEXT_PUBLIC_LANDING_ADVISORS` | name in the header, footer and page title | no name shown |
| `NEXT_PUBLIC_LANDING_BROKERAGE` | brokerage line under the name | no brokerage shown |
| `NEXT_PUBLIC_LANDING_ADDRESS` | office address in the footer | omitted from the footer line |
| `NEXT_PUBLIC_LANDING_PHONE` | "Or just call us" + the Call tile | both hidden |
| `NEXT_PUBLIC_LANDING_SMS` | the Text tile | tile hidden |
| `NEXT_PUBLIC_LANDING_EMAIL` | the Email tile | tile hidden |
| `NEXT_PUBLIC_LANDING_YEARS` | first stat | **whole strip hidden** |
| `NEXT_PUBLIC_LANDING_MARKETS` | second stat | **whole strip hidden** |
| `NEXT_PUBLIC_LANDING_PORTRAIT` | hero image | hero collapses to one column |
| `NEXT_PUBLIC_LANDING_BOOKING_URL` | "Book a consult" destination | button scrolls to the form |
| `NEXT_PUBLIC_LANDING_TESTIMONIALS` | the quotes section | **section hidden** |

The stat strip is all-or-nothing on purpose: one lonely number reads as an
omission. With no phone, SMS or mailbox at all, "Reach us" disappears entirely.

Phone numbers may be written the way humans read them — `(303) 555-0192`. The
`tel:` and `sms:` links are normalised for you.

Testimonials are a JSON array, and malformed JSON costs the section rather than
the page:

```env
NEXT_PUBLIC_LANDING_TESTIMONIALS=[{"quote":"They told us the price was wrong.","attribution":"Seller · Cherry Creek North"}]
```

## Where the leads go

The consult form posts through the **same public capture path as `/contact`** —
`POST /api/v1/public/leads` — with the same honeypot, the same Turnstile check
and the same one-source consent wording. Leads land in the inbox exactly as
they do today; nothing new had to be built on the backend.

Two details worth knowing:

- **`NEXT_PUBLIC_CAPTURE_FORM_KEY` is the tenant key**, not a label for the
  page. The landing sends the same key `/contact` sends, because both forms
  belong to the same agency. A key that is supplied but not registered in
  `channel_routes` is refused with a 404 — see
  [`public-capture-form.md`](public-capture-form.md) and
  [`onboarding-a-client.md`](onboarding-a-client.md) before setting it. On a
  single-agency install, leave it empty.
- Leads from this page carry `landing_variant=landing` in their attribution, so
  you can tell them apart from `/contact` submissions. A `landing_variant` in
  the URL wins over that default, which is how you A/B a video's landing.

## Before it goes live

- [ ] Confirm the exact office address with the managing broker — Colorado
      advertising rules want the brokerage identifiable, and a wrong address is
      worse than none.
- [ ] Real phone numbers and mailbox, or leave the section off.
- [ ] Real, cleared client testimonials, or leave the section off.
- [ ] Brand approval from the brokerage for the wording and the logo lockup.
- [ ] Turnstile keys, or the form has no bot protection (`/api/v1/health`
      reports `captcha: "off"` until the secret is set).

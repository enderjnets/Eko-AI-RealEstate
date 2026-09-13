# Social Entry Hub Design

## Purpose

Social profiles currently send people to a broad homepage. The new `/start`
route gives a visitor arriving from Instagram, TikTok, or YouTube one quick
decision: calculate what rent could buy, ask about selling or valuing a home,
or call the advisors. Every choice must keep the visit's first-touch
attribution so the dashboard can connect the social post to later action.

## Options considered

1. Send every profile directly to `/calculator`. This is the shortest path for
   buyers, but it discards seller and immediate-contact intent.
2. Build a full campaign landing page with a second form. This can be highly
   tailored, but duplicates capture, consent, validation, and analytics logic.
3. Build a compact decision hub and reuse the existing calculator, tracked
   consult form, and telephone action. This is the selected option because it
   reduces friction without creating a second lead-capture system.

## Public route and content

`/start` is public on the marketing hostname and renders in English or Spanish
through the existing language provider. It uses the current `LANDING` values
for names, phone number, brokerage, and legal identity. It must not hard-code
those deployment values.

The page contains exactly three primary actions:

- **Buy:** opens `/calculator`.
- **Sell or value a home:** opens `/#consult`, where the existing tracked form
  already records start, submit, error, and lead creation.
- **Talk now:** opens `tel:${LANDING.phone}` when a phone is configured; the
  fallback opens `/#consult`.

All action labels, supporting copy, metadata-facing page copy, and accessibility
labels have matching English and Spanish translations. The page includes the
existing language switcher.

The route is a profile link hub, not an organic-search article. Its robots
metadata is `noindex, follow`, with a canonical URL ending in `/start`.

## Attribution

`withAttribution(href, attribution)` is a pure frontend helper. It copies only
the keys in `UTM_KEYS`, trims values, drops empty values, limits each value to
200 characters, preserves an existing query and fragment, and never copies the
referrer. Internal targets receive the first-touch attribution captured on
`/start`. If no `landing_variant` arrived, links receive
`landing_variant=start`.

Telephone links are returned unchanged because query parameters cannot be
attached to `tel:` URLs. Their click is still attributed to the current landing
session before navigation.

The short aliases `/ig`, `/instagram`, `/tt`, `/tiktok`, `/yt`, and `/youtube`
redirect to `/start` and retain their current source, `bio` medium, and profile
campaign tags.

## Tracking semantics

The page mounts:

```tsx
<LandingTracker variant="start" sections={[]} trackScroll={false} />
```

A short page can fit in one viewport. The generic tracker would record 100%
scroll immediately and turn every bounce into an engaged visit, so scroll
tracking is disabled only for this route.

Every anchor carrying `data-track` records `cta_click`; a `tel:` anchor records
`tel_click`. Untagged navigation records nothing. The three locations are
`start-calculator`, `start-sell-value`, and `start-call` (or
`start-contact` when the telephone fallback is used).

## Visual and interaction constraints

The page is mobile first, loads without a remote image dependency, and keeps
all three choices visible with clear touch targets. It follows the existing
warm Denver Home Story palette and type system. It must render without
JavaScript, while analytics and language switching enhance it after hydration.

## Acceptance criteria

- `/start` and its subpaths are public; `/starter` is not accidentally matched.
- Each bio alias redirects to `/start` with correct UTM values.
- The page renders three distinct actions in both languages.
- Existing UTMs and click IDs survive the next internal navigation.
- The route records a page view but no synthetic scroll event.
- Each tagged non-telephone action records one CTA event; the phone records one
  telephone event.
- The existing homepage, calculator, guide, and form behavior remain intact.

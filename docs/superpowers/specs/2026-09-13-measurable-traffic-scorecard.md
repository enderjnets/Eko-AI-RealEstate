# Measurable Traffic and Content Scorecard Design

## Purpose

Analytics must answer which social piece produced a site visit, a meaningful
next step, a lead, and an appointment. It must also keep deliberate QA and
unambiguous automation out of performance totals without rewriting uncertain
history.

## Traffic classification options

1. Infer bots from country, event count, scroll, or burst timing. This is
   rejected because six real sessions previously recorded exactly 37 form
   starts due to a product bug; behavior rules would erase real people.
2. Delete suspicious rows after a test. This is rejected because it destroys
   the audit trail and makes past dashboards impossible to reproduce.
3. Persist a conservative classification and exclude only explicit QA or
   unequivocal automation. This is selected because every exclusion remains
   visible and reversible.

## Persistent traffic classification

`landing_sessions` gains three fields:

- `traffic_class`: non-null text constrained to `unknown`, `automated`, or
  `test`, with `unknown` as the server default.
- `traffic_class_reason`: nullable short text containing a stable reason code.
- `traffic_classified_at`: nullable timezone-aware timestamp.

Historical rows remain `unknown`, including the six sessions affected by the
old form-start bug. Unknown sessions are counted. Only `automated` and `test`
are excluded from dashboard metrics.

New sessions are classified before the raw user agent is discarded:

- `automated` when the tracker sends `webdriver: true`, or the user agent
  contains a specific automated signature: HeadlessChrome, Googlebot, bingbot,
  facebookexternalhit, Lighthouse, curl, wget, python-requests, or Bytespider.
- `test` when first-touch attribution contains both `utm_source=eko_qa` and
  `utm_medium=test`.
- `unknown` otherwise, including normal Chrome, Safari, Instagram, and TikTok
  in-app browsers.

The frontend transmits `webdriver` only when it is true. A false value is not
evidence that a visitor is human.

Analytics returns `excluded_sessions` with totals for `automated` and `test`.
The rows stay in the database. The measured-session filter is centralized and
applied to traffic totals, daily counts, source/device/location/language
breakdowns, sections, funnel steps, and content attribution.

For `/start`, a session is engaged after a CTA click, telephone click, or form
start, in addition to the existing section and scroll rules. This prevents an
untouched short page from being marked engaged while recognizing a real choice.

## Exact content scorecard

The existing 48-hour post-publication block remains and is labeled temporal
association. It is not presented as attribution.

Exact site attribution uses:

- `LandingSession.utm_content == "piece-<id>"` and matching UTM source for a
  publication's platform.
- The lead's first-touch `Lead.meta.attribution.utm_content` and source. A
  returning session never moves a lead from one piece to another.
- `Visit.lead_id` for appointments. `appointments_set` counts all visit rows;
  `appointments_held` counts rows whose status is `completed`.

Each publication row returns:

```json
{
  "latest_metrics": {
    "views": 0,
    "likes": 0,
    "comments": 0,
    "captured_on": "2026-09-13",
    "source": "manual"
  },
  "attribution": {
    "sessions": 0,
    "engaged": 0,
    "cta_clickers": 0,
    "contact_intents": 0,
    "form_starts": 0,
    "form_submits": 0,
    "leads": 0,
    "appointments_set": 0,
    "appointments_held": 0
  }
}
```

`latest_metrics` is null when no snapshot exists. Individual social counters
remain nullable: null means the platform did not supply a reading, while zero
means a measured zero. The existing `views` response field remains during this
release for compatibility.

The dashboard groups rows by content piece, shows the exact funnel for each
platform, and lets staff enter views, likes, and comments for Instagram and
TikTok. YouTube remains populated by its current API collector. English and
Spanish labels describe exact attribution separately from the 48-hour
association.

## Tenant boundary

Existing RLS remains forced on both tables and every new analytics query runs
inside the existing organization scope. `content_metrics` has a pre-existing
simple foreign key on `publication_id` rather than a composite organization
foreign key. This phase does not change the content schema, so correcting that
separate integrity gap is recorded for later instead of expanding a traffic
measurement release with an unrelated production constraint migration.

## Acceptance criteria

- The migration upgrades and downgrades cleanly with existing data.
- Historical sessions remain counted as `unknown`.
- Known automation and explicit QA rows are stored but omitted everywhere in
  Analytics, with exclusion counts returned.
- Event count, geography, repeated forms, and scroll never classify a session.
- Two `piece-<id>` tags remain separate by platform.
- Leads use first-touch metadata and appointments follow their attributed lead.
- Null and zero social counters remain distinct in API and UI.
- The current generic analytics, capture, content-metrics, and video-metrics
  behavior remains covered by the full test suites.

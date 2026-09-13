# Measurable Traffic and Content Scorecard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude only explicit QA and unequivocal automation from Analytics, then show the exact site-to-appointment result of each social publication.

**Architecture:** Classification is persisted on landing sessions at ingestion, before the raw user agent is reduced and discarded. A single measured-session predicate feeds every analytics query. Content analytics batch sessions, first-touch lead attribution, visits, and latest social counters into platform-specific rows consumed by the existing grouped content table.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16 with Alembic and RLS, Next.js/React/TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-measurable-traffic-scorecard.md`

## Global Constraints

- Historical sessions stay `unknown` and remain counted.
- Only `automated` and `test` are excluded; no behavior, country, device, scroll, or event-count heuristic is allowed.
- Explicit QA requires both `utm_source=eko_qa` and `utm_medium=test`.
- New schema is added only through Alembic after revision `059_partner_briefs`.
- Exact leads use first-touch `Lead.meta.attribution`; later sessions cannot reassign them.
- Null social counters and measured zeroes remain distinct.
- All dashboard copy must exist in English and Spanish.
- Run each new test once in red before writing production code.

---

### Task 1: Persist conservative traffic classification

**Files:**
- Modify: `backend/app/models/landing.py`
- Modify: `backend/app/services/landing_analytics.py`
- Modify: `backend/app/api/v1/public.py`
- Create: `backend/migrations/versions/20260913_1900_landing_traffic_class.py`
- Test: `backend/tests/test_public_landing_events.py`
- Test: `backend/tests/test_landing_is_tenant_isolated.py`
- Modify: `frontend/lib/track.ts`
- Test: `frontend/lib/__tests__/track.test.ts`

**Interfaces:**
- Produces: `classify_traffic(user_agent: str | None, webdriver: bool, attribution: dict[str, str]) -> tuple[str, str | None]`.
- Produces: optional request field `webdriver: Literal[True] | None` and persisted fields `traffic_class`, `traffic_class_reason`, `traffic_classified_at`.

- [ ] **Step 1: Write failing backend classifier and ingestion tests**

Assert `webdriver=True` and each explicit automated signature return
`automated`; the exact QA pair returns `test`; ordinary Chrome, Safari,
Instagram, and TikTok return `unknown`; and changes in country, scroll,
event count, or repeated forms do not enter the classifier. Drive the public
endpoint and assert the class is stored while no raw UA is stored.

- [ ] **Step 2: Run focused backend tests and confirm red**

Run: `cd backend && python -m pytest tests/test_public_landing_events.py -k "traffic_class or webdriver or automated or explicit_test" -q`

Expected: FAIL because the fields and classifier do not exist.

- [ ] **Step 3: Write the migration and model**

Create revision `060_landing_traffic_class` with down revision
`059_partner_briefs`. Add non-null `traffic_class` with server default
`unknown`, the reason and timestamp columns, and a named check constraint for
the three allowed values. Downgrade drops the constraint and columns in reverse
order. Mirror them on `LandingSession`.

- [ ] **Step 4: Implement classifier and public request handling**

Add a closed tuple of case-insensitive signatures and return stable reason
codes such as `webdriver`, `ua_headless_chrome`, and `explicit_qa`. Add
`webdriver: Literal[True] | None = None` to `LandingBatchIn`. During the first
session insert, classify from the raw header and cleaned attribution, write all
three fields, then continue storing only the existing reduced browser/device
facts.

- [ ] **Step 5: Add the frontend true-only marker in red then green**

Extend the serialized tracker payload with `webdriver: true` only when
`navigator.webdriver === true`; assert the key is absent for false or missing
values. Run `cd frontend && npm test -- lib/__tests__/track.test.ts` before and
after implementation.

- [ ] **Step 6: Verify migration and focused tests**

Run Alembic upgrade, downgrade one revision, and upgrade again against the
isolated PostgreSQL database. Then run:

```bash
cd backend
python -m pytest tests/test_public_landing_events.py tests/test_landing_is_tenant_isolated.py -q
```

Expected: migrations and tests pass; RLS isolation remains intact.

- [ ] **Step 7: Commit classification**

```bash
git add backend/app/models/landing.py backend/app/services/landing_analytics.py backend/app/api/v1/public.py backend/migrations/versions/20260913_1900_landing_traffic_class.py backend/tests/test_public_landing_events.py backend/tests/test_landing_is_tenant_isolated.py frontend/lib/track.ts frontend/lib/__tests__/track.test.ts
git commit -m "feat(analytics): separate QA and automated traffic" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2: Apply one measurable-session rule everywhere

**Files:**
- Modify: `backend/app/services/analytics.py`
- Test: `backend/tests/test_analytics.py`

**Interfaces:**
- Consumes: `LandingSession.traffic_class`.
- Produces: traffic response `excluded_sessions: { total: int, automated: int, test: int }`.

- [ ] **Step 1: Write failing analytics exclusion tests**

Seed one unknown, one automated, and one test session with deliberately
different days, sources, devices, locations, sections, and funnel events.
Assert only the unknown row contributes to every traffic aggregate and funnel
stage, while exclusion counts are `total=2`, `automated=1`, and `test=1`.
Also assert an untouched `/start` session is not engaged and one with a CTA
click is engaged; existing 50% scroll engagement remains true.

- [ ] **Step 2: Run focused tests and confirm red**

Run: `cd backend && python -m pytest tests/test_analytics.py -k "excluded or start_engaged" -q`

Expected: FAIL because exclusions and interaction-based engagement are absent.

- [ ] **Step 3: Implement the centralized scope**

Create a private predicate:

```python
def _measured_session() -> ColumnElement[bool]:
    return LandingSession.traffic_class == "unknown"
```

Apply it alongside the date window to every `LandingSession` query in
`traffic()` and to the traffic-derived funnel counts. Compute excluded counts
with the same date window but without `_measured_session`. Extend the engaged
condition with CTA clicks, telephone clicks, or non-null form start.

- [ ] **Step 4: Run the complete analytics tests**

Run: `cd backend && python -m pytest tests/test_analytics.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the measured scope**

```bash
git add backend/app/services/analytics.py backend/tests/test_analytics.py
git commit -m "fix(analytics): report only measured visitor sessions" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3: Batch exact piece-to-appointment attribution

**Files:**
- Modify: `backend/app/services/analytics.py`
- Test: `backend/tests/test_analytics.py`

**Interfaces:**
- Consumes: measured landing sessions, `utm_content=piece-<id>`, publication platform, first-touch lead metadata, `Visit.lead_id`, and latest `ContentMetric`.
- Produces: each content row's `latest_metrics` and `attribution` objects while preserving the existing `association`, `leads_tagged`, and `views` fields.

- [ ] **Step 1: Write failing exact-attribution tests**

Seed two pieces on different platforms, tagged and untagged sessions, one
excluded QA session, leads whose first touches name each piece, and scheduled,
completed, and cancelled visits. Assert platform separation and the exact nine
fields from the spec. Assert a later session tagged to piece B does not move a
lead first attributed to piece A. Seed a metrics snapshot with zero likes and
null comments and assert both values retain their meaning.

- [ ] **Step 2: Run focused tests and confirm red**

Run: `cd backend && python -m pytest tests/test_analytics.py -k "exact_attribution or latest_metrics or first_touch" -q`

Expected: FAIL because the response has neither object.

- [ ] **Step 3: Implement batched aggregation**

Collect all publication and piece IDs first. Fetch measured sessions for the
window once, group only tags matching `piece-<integer>`, and require normalized
source to equal the publication platform. Fetch candidate leads once, inspect
`meta["attribution"]` defensively in Python, and build `lead_id -> (piece_id,
source)`. Fetch visits for those lead IDs once and aggregate set/held counts.
Fetch latest metrics for all publication IDs in one ordered query and keep the
first row per publication. Never execute a query inside the publication loop.

- [ ] **Step 4: Run analytics and query-count regression tests**

Run: `cd backend && python -m pytest tests/test_analytics.py -q`

Expected: PASS and query count remains constant when a second piece is added.

- [ ] **Step 5: Commit exact attribution**

```bash
git add backend/app/services/analytics.py backend/tests/test_analytics.py
git commit -m "feat(analytics): connect social pieces to appointments" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4: Render the bilingual scorecard and manual counters

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/analytics/ContentTable.tsx`
- Modify: `frontend/components/analytics/AnalyticsView.tsx`
- Modify: `frontend/lib/i18n.tsx`
- Test: `frontend/lib/__tests__/analyticsPage.test.ts`
- Test: `frontend/lib/__tests__/i18nParity.test.ts`

**Interfaces:**
- Consumes: `latest_metrics`, per-publication `attribution`, and `traffic.excluded_sessions`.
- Produces: bilingual, platform-specific view/like/comment counters and site-to-appointment scorecard.

- [ ] **Step 1: Write failing API and rendering contract tests**

Assert TypeScript types expose all fields in the spec. Require UI labels for
visits, engaged, next-step clicks, contact intent, forms, leads, appointments
set/held, views, likes, comments, exact attribution, 48-hour association, and
excluded QA/automation. Assert rendering uses null checks (`=== null`) so zero
does not become “no reading.”

- [ ] **Step 2: Run focused frontend tests and confirm red**

Run: `cd frontend && npm test -- lib/__tests__/analyticsPage.test.ts lib/__tests__/i18nParity.test.ts`

Expected: FAIL because the new contract and labels are absent.

- [ ] **Step 3: Extend types and content rows**

Add exact interfaces in `api.ts`. Replace the one-field manual editor with a
small views/likes/comments editor for Instagram and TikTok that submits the
existing metrics endpoint. Render each platform's social counters and exact
attribution as a compact sequence; keep the 48-hour values under their current
association label. Show excluded session counts near the traffic summary only
when total is greater than zero.

- [ ] **Step 4: Add translations and pass focused tests**

Add every new `analytics.*` key to both dictionaries, then run the two focused
tests until they pass.

- [ ] **Step 5: Run frontend verification**

Run: `cd frontend && npm test && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0.

- [ ] **Step 6: Commit the scorecard UI**

```bash
git add frontend/lib/api.ts frontend/components/analytics/ContentTable.tsx frontend/components/analytics/AnalyticsView.tsx frontend/lib/i18n.tsx frontend/lib/__tests__/analyticsPage.test.ts frontend/lib/__tests__/i18nParity.test.ts
git commit -m "feat(analytics): show social content conversion scorecard" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```


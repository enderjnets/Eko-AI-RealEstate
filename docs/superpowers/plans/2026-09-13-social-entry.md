# Social Entry Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fast bilingual `/start` page that routes social visitors to the calculator, the existing seller form, or a telephone call while preserving attribution.

**Architecture:** A server page owns metadata and renders one focused client component. Pure helpers build attributed internal links and classify anchor clicks; `LandingTracker` remains the browser adapter and gains an explicit switch to suppress false scroll engagement on a one-screen page.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript, Tailwind CSS, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-13-social-entry.md`

## Global Constraints

- All visible copy must exist in both English and Spanish in `frontend/lib/i18n.tsx`.
- Advisor, brokerage, phone, and legal identity must come from `LANDING`; do not hard-code deployment values.
- `/start` uses `noindex, follow` metadata and canonical `/start`.
- The page reuses `/calculator`, `/#consult`, and `tel:`; it does not create a second form.
- Attribution copies only `UTM_KEYS`, limits values to 200 characters, and never propagates `referrer`.
- Run each new test once in red before writing production code.

---

### Task 1: Attributed internal links

**Files:**
- Modify: `frontend/lib/capture.ts`
- Test: `frontend/lib/__tests__/capture.test.ts`

**Interfaces:**
- Consumes: `UTM_KEYS` and `Record<string, string>` first-touch attribution.
- Produces: `withAttribution(href: string, attribution: Record<string, string>): string`.

- [ ] **Step 1: Write failing helper tests**

Add tests equivalent to:

```ts
expect(withAttribution("/calculator", {
  utm_source: " instagram ",
  utm_content: "piece-42",
  referrer: "https://instagram.com/",
})).toBe("/calculator?utm_source=instagram&utm_content=piece-42");

expect(withAttribution("/?mode=sell#consult", {
  utm_source: "youtube",
  landing_variant: "start",
})).toBe("/?mode=sell&utm_source=youtube&landing_variant=start#consult");

expect(withAttribution("tel:+13035550101", { utm_source: "tiktok" }))
  .toBe("tel:+13035550101");
expect(withAttribution("/calculator", {})).toBe("/calculator");
```

Also assert percent encoding, a 200-character cap, unknown-key removal, empty
value removal, and replacement of an existing allowed query key without
duplicating it.

- [ ] **Step 2: Run the focused test and confirm red**

Run: `cd frontend && npm test -- lib/__tests__/capture.test.ts`

Expected: FAIL because `withAttribution` is not exported.

- [ ] **Step 3: Implement the pure helper**

Implement the exported function without reading browser globals:

```ts
export function withAttribution(
  href: string,
  attribution: Record<string, string>,
): string {
  if (/^(?:tel|mailto):/i.test(href)) return href;
  const hashAt = href.indexOf("#");
  const hash = hashAt >= 0 ? href.slice(hashAt) : "";
  const beforeHash = hashAt >= 0 ? href.slice(0, hashAt) : href;
  const queryAt = beforeHash.indexOf("?");
  const path = queryAt >= 0 ? beforeHash.slice(0, queryAt) : beforeHash;
  const params = new URLSearchParams(queryAt >= 0 ? beforeHash.slice(queryAt + 1) : "");
  for (const key of UTM_KEYS) {
    const value = (attribution[key] ?? "").trim().slice(0, 200);
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return `${path}${query ? `?${query}` : ""}${hash}`;
}
```

- [ ] **Step 4: Run the focused test and confirm green**

Run: `cd frontend && npm test -- lib/__tests__/capture.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit the helper**

```bash
git add frontend/lib/capture.ts frontend/lib/__tests__/capture.test.ts
git commit -m "feat(landing): preserve attribution across social choices" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2: Honest click and scroll tracking

**Files:**
- Modify: `frontend/lib/track.ts`
- Modify: `frontend/components/landing/LandingTracker.tsx`
- Test: `frontend/lib/__tests__/track.test.ts`

**Interfaces:**
- Consumes: anchor `href` and optional `data-track` value.
- Produces: `trackedAnchorEvent(href: string, where?: string): { name: "cta_click" | "tel_click"; meta: { where: string } } | null` and `LandingTracker` prop `trackScroll?: boolean`.

- [ ] **Step 1: Write failing event-classification tests**

```ts
expect(trackedAnchorEvent("/calculator", "start-calculator")).toEqual({
  name: "cta_click", meta: { where: "start-calculator" },
});
expect(trackedAnchorEvent("tel:+13035550101", "start-call")).toEqual({
  name: "tel_click", meta: { where: "start-call" },
});
expect(trackedAnchorEvent("/calculator")).toBeNull();
```

Add source-contract assertions that `LandingTracker` accepts `trackScroll`,
does not attach or call the scroll handler when it is false, and still removes
listeners it actually attached.

- [ ] **Step 2: Run the focused test and confirm red**

Run: `cd frontend && npm test -- lib/__tests__/track.test.ts`

Expected: FAIL because the helper and prop do not exist.

- [ ] **Step 3: Implement classification and the scroll switch**

Add the pure helper to `track.ts`. In the delegated click listener call it and
record its returned event. Add `trackScroll = true` to `LandingTracker`; wrap
both `addEventListener("scroll", ...)` and the initial `onScroll()` call with
that flag, and only remove that listener when enabled.

- [ ] **Step 4: Run tracking tests and confirm green**

Run: `cd frontend && npm test -- lib/__tests__/track.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit tracking behavior**

```bash
git add frontend/lib/track.ts frontend/components/landing/LandingTracker.tsx frontend/lib/__tests__/track.test.ts
git commit -m "fix(analytics): track social choices without false scrolls" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3: Public bilingual `/start` route

**Files:**
- Create: `frontend/app/start/page.tsx`
- Create: `frontend/components/landing/Start.tsx`
- Modify: `frontend/lib/hosts.ts`
- Modify: `frontend/next.config.js`
- Modify: `frontend/lib/i18n.tsx`
- Test: `frontend/lib/__tests__/hostRouting.test.ts`
- Test: `frontend/lib/__tests__/bioLinks.test.ts`
- Test: `frontend/lib/__tests__/publicMetadata.test.ts`
- Create: `frontend/lib/__tests__/startPage.test.ts`

**Interfaces:**
- Consumes: `withAttribution`, `LandingTracker`, `LANDING`, `LanguageSwitcher`, and the active i18n language.
- Produces: public route `/start` and bio redirects whose destinations begin with `/start?`.

- [ ] **Step 1: Write route, redirect, metadata, and source-contract tests**

Require `/start` in `PUBLIC_PATHS` with boundary-safe matching; require all six
bio aliases to route to `/start` with the expected UTM source, medium `bio`,
and campaign `profile`; require `robots.index === false`,
`robots.follow === true`, and canonical `/start`.

In `startPage.test.ts`, read the component source and assert one occurrence of
each `data-track` identifier, a language switcher, `LANDING.phone`,
`withAttribution`, and:

```tsx
<LandingTracker variant="start" sections={[]} trackScroll={false} />
```

- [ ] **Step 2: Run the focused tests and confirm red**

Run:

```bash
cd frontend
npm test -- lib/__tests__/hostRouting.test.ts lib/__tests__/bioLinks.test.ts lib/__tests__/publicMetadata.test.ts lib/__tests__/startPage.test.ts
```

Expected: FAIL because `/start` and its contracts do not exist.

- [ ] **Step 3: Implement the page and routing**

Create a metadata-only server page that renders `<Start />`. In the client
component, collect current query attribution, add `landing_variant=start` only
when absent, build the two internal hrefs with `withAttribution`, and render the
phone or consult fallback from `LANDING.phone`. Use three clear cards with the
existing `ln-*` color and typography tokens. Add all `start.*` keys to both
language dictionaries. Add `/start` to `PUBLIC_PATHS`, and change every bio
redirect destination from `/?...` to `/start?...`.

- [ ] **Step 4: Run focused and parity tests**

Run:

```bash
cd frontend
npm test -- lib/__tests__/hostRouting.test.ts lib/__tests__/bioLinks.test.ts lib/__tests__/publicMetadata.test.ts lib/__tests__/startPage.test.ts lib/__tests__/i18nParity.test.ts
```

Expected: PASS.

- [ ] **Step 5: Verify the frontend build**

Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0 and the build lists `/start` as a route.

- [ ] **Step 6: Commit the route**

```bash
git add frontend/app/start/page.tsx frontend/components/landing/Start.tsx frontend/lib/hosts.ts frontend/next.config.js frontend/lib/i18n.tsx frontend/lib/__tests__
git commit -m "feat(landing): add social entry hub" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```


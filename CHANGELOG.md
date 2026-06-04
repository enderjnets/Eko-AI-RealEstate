# CHANGELOG

All notable changes to **Eko AI Realtors**.

## [0.34.0] — 2026-06-04

### Admin: change demo access to Member + per-user engagement stats

- **Change access level**: admins can switch a demo registration from view-only to
  **Member** (read+write) via a per-row dropdown in Settings. `PATCH /api/v1/team/accounts/{id}`
  updates `Account.role`; `login/account` then mints a member session.
- **Per-user stats** (Google/Apple **and** demo accounts): each Settings row has a 📊 toggle
  showing logins, total actions, active days, last seen, most-used sections (mini-bars),
  device/browser, and IP — to understand users and improve the system.
- **Lightweight tracking**: a middleware upserts one `UserActivity` row per session-email on
  each authenticated request to a tracked section; login endpoints bump login_count. The
  shared office password (no email) isn't tracked. Stats are admin-only.
- Backend: `user_activity` table (Alembic `013`), `services/activity.py`, the middleware,
  `GET /api/v1/team/activity`. IP + device only (no geolocation).

## [0.33.0] — 2026-06-04

### Admin: registered-users view (Google/Apple + view-only demo signups)

- **Settings** now shows a **"Demo registrations (view-only)"** panel listing everyone who
  self-registered via the public form — name, email, phone, company, location, registration
  date — for sales follow-up. Admins can delete a registration (e.g. test accounts).
- Google/Apple access is still managed in the **"Team & access (Google/Apple)"** panel (the
  allow-list). Both sit together in Settings, admin-only.
- Backend: `GET /api/v1/team/accounts` + `DELETE /api/v1/team/accounts/{id}` (admin-gated,
  on the existing `require_admin` team router). Reuses the `accounts` table — no migration.

## [0.32.1] — 2026-06-04

### Fix: the "Create account" (register) link did nothing

- The `AuthGuard` only exempted `/login`, so navigating to `/register` while
  unauthenticated (on the AUTH_ENABLED demo) bounced straight back to `/login` —
  the link appeared to do nothing. `/register` is now a public route in the guard,
  so the registration page opens. `components/ui/AuthGuard.tsx`.

## [0.32.0] — 2026-06-04

### Self-registration → read-only ("viewer") demo accounts

- **New `/register` page**: anyone can sign up with name, email, phone, company,
  address, state, country + password. Registration auto-signs them in.
- These are **read-only "viewer" accounts** — they can browse the whole dashboard
  but cannot mutate anything. Intended to showcase the system to prospective clients.
- **Read-only enforced server-side**: `require_auth` rejects any non-GET request
  from a viewer with 403 (single choke-point for the whole data API). Passwords are
  hashed with stdlib PBKDF2 (no new dep). New `accounts` table (Alembic `012`).
- **UI**: a "view-only" banner + the create/edit controls hide for viewers
  (Add lead, Composer reply, book/cancel visit, calendar Add event, lead quick
  actions). `/login` gains an email+password sign-in for these accounts alongside
  the office password and Google/Apple.
- Endpoints: `POST /api/v1/auth/register`, `POST /api/v1/auth/login/account`. New
  role `viewer` in the session token.

## [0.31.1] — 2026-06-03

### Calendar: clicking an appointment opens the lead

- Calendar items (in both the Agenda list and the Month grid) are now clickable —
  a visit or follow-up navigates straight to the lead's page (`/leads/{id}`).
  Lead-less manual events are not clickable. `components/calendar/CalendarView.tsx`.

## [0.31.0] — 2026-06-02

### New Calendar tab: agenda + month grid + manual events

- New **Calendar** nav tab aggregating, in the office timezone: all lead **visits**,
  **manual events**, and **pending system follow-ups** — one place to see everything
  the system schedules.
- Two views (toggle): **Agenda** (list grouped by day — Today/Tomorrow/date) and
  **Month** (month grid with each day's items).
- **Add event** creates a manual calendar entry (title, date/time, duration, notes)
  that doesn't need a lead. The naive wall-clock is localized to the office timezone.
- Backend: `Visit.lead_id` is now **nullable** + `Visit.title` (Alembic `011`).
  New `GET /api/v1/visits` (all, optional from/to), `POST /api/v1/visits` (manual
  event, `provider=manual`, no Cal.com round-trip), `GET /api/v1/visits/agenda`
  (visits + PENDING follow-ups unified). `VisitOut` gains `lead_id?`/`title`.

## [0.30.0] — 2026-06-02

### Office timezone: visits booked in local time (not UTC) + a Settings preference

- **Bug**: the voice agent treated a spoken "2 PM" as 2 PM **UTC**, so the visit
  landed at 8 AM Denver. Booking now interprets the spoken wall-clock time in the
  **office timezone** and stores it correctly (2 PM Denver → 20:00 UTC). `_parse_dt`
  localizes the wall-clock to the office tz; `book_visit` + manual `book_slot` load
  the office tz from settings; the assistant prompt now passes a tz-less local time.
- **New Settings preference — Timezone**: auto-detected from the browser on first
  load (one-time persist), changeable anytime. Drives how the agent interprets
  spoken times and how all visits are displayed.
- Visits now render in the office timezone **with the tz abbreviation** (e.g.
  "2:00 PM MDT"), consistent regardless of the viewer's location.
- `AgentSettings.timezone` (Alembic `010`, default UTC); `tzdata` added to
  requirements (python-slim has no system zoneinfo). `GET/PUT /settings` validate
  the IANA name.

## [0.29.1] — 2026-06-02

### Friendly "lead not found" state (no more raw red API error)

- Opening a lead that no longer exists (e.g. an old link to a lead that was merged
  or removed) showed a raw red `API 404: Lead not found` box. It now renders a clean
  "Lead not found" empty state — with a hint that it may have been merged/removed and
  a **Back to leads** link. Real (non-404) errors still show the error box.
- `components/leads/LeadDetail.tsx` distinguishes 404 from other errors; i18n
  `lead.notFoundHint` (EN+ES).

## [0.29.0] — 2026-06-02

### Inbox: "new + pending" badge count + quick-access dropdown menu

- The nav **Inbox badge** now counts **`needs_attention`** = awaiting our reply **OR**
  a fresh (<24h) untriaged conversation (e.g. a just-finished voice call where the
  agent spoke last). So a new call shows up immediately, without old leads inflating
  the number.
- Clicking the Inbox badge opens a **dropdown**: a **"Go to inbox"** header (general
  section) and below it direct links to each new/pending communication (channel icon
  🗣️/✉️/💬 + name + preview) that jump straight to `/leads/{id}`.
- **Opening a lead** marks it reviewed → clears it from the badge, *unless* it's still
  awaiting our reply (that clears on reply or explicit "handled").
- Backend: `services/inbox.py` computes `needs_attention` (`NEW_ACTIVITY_WINDOW_HOURS=24`);
  `GET /inbox` gains a `filter=attention` + `attention_count`; `GET /inbox/count` gains
  `attention`. `pending` is unchanged for back-compat.

## [0.28.1] — 2026-06-02

### Fix voice: a call lands on ONE lead (transcript + visit + extracted fields)

- **Split-lead bug**: a single call produced two leads — the **visit** went to the
  number the caller *dictated* (`book_visit` arg) while the **transcript** went to the
  real **caller id** (end-of-call report). Fix: `book_visit` now keys the lead on the
  **caller id** (same identifier the end-of-call ingest uses) and keeps the dictated
  number as a callback note → visit + transcript land on the same lead.
- **Structured-data bug**: VAPI returned `structuredData` in a **nested** auto-shape
  (`customer_info` / `property_inquiry`) that wasn't mapped → the lead had no
  intent/zone/budget. Fix: `_flatten_voice_structured` normalizes both the flat and
  nested shapes; `scripts/setup_vapi.sh` now sets an **explicit** `structuredDataPlan.schema`
  so future calls return a deterministic flat shape.

## [0.28.0] — 2026-06-02

### Phase 13 · Voice agent (VAPI) — calls that qualify leads and book visits

- **New VOICE channel.** The agent answers calls via VAPI (female English 11labs
  voice + Claude Sonnet 4.5 as the realtime brain). It qualifies the caller
  (buy/rent/valuation, zone, budget, timeline) and can **book a visit during the
  call** through a tool-call into the Cal.com booking service (Phase 5).
- **End-of-call ingest.** When the call ends, VAPI POSTs an `end-of-call-report`
  to `POST /api/v1/webhooks/voice`; we ingest the full transcript into the lead's
  timeline as `channel="voice"` (turns as Messages), apply the extracted fields,
  and rescore — same lead pipeline as SMS/email. No LLM call on ingest (the
  conversation already happened live). Idempotent per `call_id`.
- `services/voice.py`: `verify_vapi_secret` (shared `x-vapi-secret`),
  `parse_end_of_call_report`, and `handle_tool_call` (`check_availability` /
  `book_visit`). `conversation.py::ingest_voice_call` upserts the lead and stores
  the transcript. Voice stays OUT of `SENDABLE_CHANNELS` (no outbound text).
- `VOICE_SIMULATED=true` by default (dev + the public demo need no VAPI account;
  the webhook accepts unsigned requests). Outbound calling (the agent calling
  leads) is deferred to a future phase. Setup: `docs/setup-vapi.md`.
- Tests: `test_voice_service.py` (secret/parse/tool-calls) +
  `test_voice_webhook_e2e.py` (end-of-call → lead+conversation+messages+score,
  idempotency, tool-call book_visit → Visit).

## [0.27.1] — 2026-06-01

### More robust email threading: full References chain

- The agent's reply now sets the `References` header to the **full chain** (thread
  root … the lead's message), not just `In-Reply-To` to the parent — so Gmail/
  Outlook reliably nest the reply inside the conversation instead of starting a new
  thread.
- `services/email.py::send_email` takes a `references` arg; `conversation.py` builds
  the chain from `thread_id` (root) + `external_id` (inbound message) and passes it.

## [0.27.0] — 2026-06-01

### Inbound email: fetch real body + Message-ID (Received Emails API) → correct threading

- **Root cause of "replies as a new email instead of threading"**: Resend's
  `email.received` webhook is **metadata-only** (no body/headers), so inbound
  messages were stored with empty content and without the real RFC822 Message-ID
  — so the agent's reply couldn't be threaded.
- **Fix**: the webhook handler now calls `GET /emails/inbound/{id}` (Received
  Emails API) to fetch the **full** email — `text`, RFC822 `message_id`, and
  `references`/`in_reply_to` — and passes that to the orchestrator. The agent now
  reads the real message and its reply carries correct `In-Reply-To`/`References`
  → Gmail threads it into the conversation.
- `services/email.py`: new `fetch_inbound_email(id)` + `_strip_quoted_reply()`
  (drops quoted "On … wrote:" / ">" history so the agent sees only the new
  message). The SIMULATED path (tests) skips the fetch (body already present).
- Note: external delivery (Gmail→Resend) was working all along — the emails were
  in the Received Emails API; we just weren't pulling their content into the backend.

## [0.26.1] — 2026-06-01

### Email self-loop guard: the agent never replies to itself

- **Security fix**: an inbound email whose sender is **our own sending address**
  (`noreply@<domain>`) is now ignored. Without it, a reply/bounce addressed back
  to `noreply@` re-entered via the inbound webhook and the agent answered itself
  in an infinite loop (burning LLM calls + sending emails). Found during inbound
  testing.
- `services/conversation.py`: guard at the top of `handle_inbound_message` — if
  `channel=email` and the sender equals the `RESEND_FROM` address, it returns
  `ignored_self_loop` without creating a lead or replying. +1 test.

## [0.26.0] — 2026-06-01

### Agent language: English by default, mirroring the lead's language (or the one they ask for)

- Outbound agent communications now default to **English**. If the lead writes in
  another supported language (es/en) the agent mirrors it; if the lead explicitly
  asks for another language, the agent switches to it.
- `services/i18n.py`: `DEFAULT_LANGUAGE` changed `es → en` (used when the language
  can't be detected / the text is ambiguous). The steering line now allows an
  explicit override ("UNLESS the client asks for another language").
- `services/conversation.py`: the default supported-language order is now
  `["en", "es"]` (reply + suggestions), so an unsupported detected language falls
  back to English. Previously the default was Spanish.
- i18n tests +3 (English default, English-first mirroring, explicit-request override).

## [0.25.0] — 2026-06-01

### Local Gemma (Google) LLM fallback via Ollama — the agent replies even when paid quotas are exhausted

- **Root cause**: the agent stopped replying to leads because **both** paid LLM
  providers ran out of quota (Kimi: "usage limit for this billing cycle";
  MiniMax: "usage limit exceeded"). Not an email or code bug.
- **Fix**: added a third LLM provider — **Gemma** (Google's open model) running
  **locally on Ollama** on the ROG — as a free final fallback. Order is
  Kimi → MiniMax → local Gemma. Paid providers still go first (quality); when
  both fail, local Gemma guarantees the lead gets an answer at no cost.
- `services/llm.py`: new `ollama` provider speaking Ollama's native `/api/chat`
  (with `format=json` for the classifier), separate from the Anthropic protocol
  used by Kimi/MiniMax. Gated by `OLLAMA_ENABLED`. +1 test.
- Config: `OLLAMA_ENABLED` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL` /
  `OLLAMA_TIMEOUT_SECONDS` in config.py + docker-compose. The ROG demo uses
  `gemma3:4b` (fits the RTX 3070 8GB).

## [0.24.1] — 2026-05-31

### Fix: Add Lead budget accepts "600k"/"1.2M" + readable validation errors

- **Bug**: typing the budget as `600k` / `800k` in Add Lead sent the raw string to
  the backend → `422 Input should be a valid decimal`, and the error was dumped
  as raw JSON in the modal.
- **Fix**: the budget is now normalized client-side — accepts `600k`, `1.2M`,
  `600,000`, `$850000` and converts to a number before sending (k=×1,000,
  M=×1,000,000). If a field is non-numeric, a clear inline message is shown
  instead of sending garbage.
- **Fix**: `errorDetail` (lib/api.ts) now formats FastAPI validation errors
  (when `detail` is an array) as readable `field: message` text instead of
  dumping raw JSON (which could also crash React if rendered as an object).

## [0.24.0] — 2026-05-31

### Power layer on Properties (search + type chips + sort) and Analytics (weekly trend)

Continues the Claude Design desktop pass — the same "intuitive yet powerful"
layer, now on Properties and Analytics. Frontend-only; no backend changes.

- **Properties → CRM-style explorer**: live search (zone / address / title /
  type) with a `/` shortcut; filter chips by property type (derived from the
  loaded listings); a max-price filter; a toggleable Newest ↔ Price sort; an
  "N of M active" counter; and an empty state with clear-filters. The Sync MLS
  button stays.
- **Analytics → real weekly trend**: ▲/▼ deltas computed from the existing
  `leads_per_day` series — a new "New this week" stat card (sum of the last 7
  days) with a % delta vs. the previous 7 days, and the per-day chart now
  highlights the current week (bright bars) vs. the prior week (dimmed). No
  invented metrics — a trend only shows where there is real time-series data.
- Full EN + ES i18n. Everything stays responsive; mobile and the rest of the
  dashboard are untouched.

## [0.23.0] — 2026-05-29

### More powerful desktop: CRM-style Leads + Lead detail with quick actions & "Why this score"

Implements the desktop design handed off from Claude Design — make the realtor
feel the system is intuitive yet powerful. (Mobile shipped in v0.22.0; this is
the desktop layer.) Everything stays responsive; the mobile experience is intact.

- **Leads is now a CRM-style explorer** (`LeadsExplorer`, replacing
  `FilterBar` + `LeadsTable`): live search (name / zone / contact / intent /
  type) with a `/` keyboard shortcut; smart filter chips (All · 🔥 Hot ·
  Pending reply · New · Qualified · Visiting · Won); a toggleable Priority ↔
  Recent sort (server-side) with a live "N of M" counter; richer rows (red→amber
  accent bar on hot leads, amber "waiting for reply" dot, hover chevron); and an
  empty state with a clear-filters action.
- **Backend**: `GET /leads` now returns `needs_response` per lead (last message
  inbound = waiting on us), via a grouped query scoped to the page (no N+1, same
  pattern as the inbox). Powers the "Pending reply" chip and the row dot. +1 test.
- **Lead detail quick-action bar**: Reply (focuses the composer) · Call (`tel:`
  for phone leads) · Book visit (scrolls to the visits section) · Mark won
  (`PATCH status=won`). Plus a **"Why this score"** card that visualizes the real
  `score_breakdown` (Intent / Budget / Engagement / Urgency / Zone / Type /
  Recency / Visit) with gradient bars.
- **Global polish**: accessible `:focus-visible` ring + a dark scrollbar that
  matches the noir console.
- Full EN + ES i18n for the new strings.

## [0.22.1] — 2026-05-29

### Fix: "Sign in with Google" works on mobile (popup → redirect)

On a phone, tapping "Sign in with Google" opened a new tab to
`accounts.google.com/gsi/transform` that stayed **blank**. Mobile browsers open
the GIS popup as a separate tab, so the credential never returns to the original
tab. (Desktop worked; the Google Console config was correct; v0.22.0 did not
cause it — it surfaced on first mobile use.)

- The button now uses `ux_mode="redirect"` + `login_uri` → Google does a
  full-page navigation (no popup) and POSTs the ID token to the backend. Works
  identically on mobile and desktop.
- New `POST /api/v1/auth/login/google/callback`: verifies Google's
  double-submit CSRF token (`g_csrf_token` body == cookie), validates the ID
  token + allow-list (reusing the existing helpers), sets the session cookie,
  and 303-redirects into `/leads`. Failures bounce to
  `/login?error=google_failed|google_denied` (the login page shows the notice).
  +4 backend tests.
- **Requires one Google Cloud Console change**: add
  `https://inmo-demo.ekoaiautomation.com/api/v1/auth/login/google/callback` to
  the OAuth client's **Authorized redirect URIs** (see
  `docs/setup-google-signin.md`). Password login is unchanged. The legacy JSON
  popup endpoint `POST /api/v1/auth/login/google` is kept for back-compat.

## [0.22.0] — 2026-05-29

### Native-app mobile dashboard (bottom tab bar + slim top bar + notch support)

Mobile visitors to `inmo-demo.ekoaiautomation.com` now get a genuinely usable,
native-app-feeling dashboard. Desktop is unchanged.

- **Fixed bottom tab bar** (phones only, hidden ≥ `md`): Discovery · Leads ·
  Inbox · Properties · Stats. The active tab is highlighted in violet based on
  the current route; Inbox shows an amber dot when there are pending
  conversations. This is the primary navigation on mobile.
- **Slim top bar on mobile**: brand + language + sign-out (plus a Settings gear
  for admins, since Settings isn't in the tab bar). The full desktop link row is
  hidden below `md`.
- **Notch / safe-area support**: `viewport-fit=cover` + dark `theme-color` +
  apple-web-app metadata. The tab bar honors `env(safe-area-inset-bottom)`, and
  page content reserves bottom clearance via `body:has(.eko-tabbar)` so login /
  about (which have no tab bar) keep their full-height layout.
- **Touch-friendly composer on mobile**: the channel selector (SMS / Email /
  Voice) spans full width with larger tap targets; the "Suggest replies" and
  "Send" buttons are roomier for the thumb. Desktop layout is untouched.
- Single-column stacking was already handled per-page by Tailwind responsive
  classes; this release adds the native mobile chrome that was missing.

Implements the mobile design handed off from Claude Design (claude.ai/design).

## [0.21.2] — 2026-05-28

### Inbox handled-state moved to a real column (removes the Lead.meta race)

- The inbox "handled" state moved from `Lead.meta["inbox"]["handled_at"]` (JSON
  blob) to a dedicated `leads.inbox_handled_at` column (Alembic `009`, backfilled
  from the existing JSON). Previously, marking handled reassigned the whole `meta`
  dict, so it could clobber (or be clobbered by) a concurrent writer to `meta`
  (e.g. discovery enrichment writing `meta.enrichment`). They're now separate
  columns and can't interfere.
- `set_handled()` is now a plain column assignment (no ISO parse, no dict
  reassign); removed the silent parse-swallow that could leave a lead "pending"
  forever on a corrupt value.
- **Regression test +1**: two overlapping sessions on the same lead (one writes
  `meta.enrichment`, the other marks handled) both survive (the old approach lost
  one on the last commit).

## [0.21.1] — 2026-05-28

### Code-review fixes for the inbox

- **Past visits no longer shown as booked**: `_next_visit_per_lead` now filters
  `scheduled_at >= now`, so a visit still in scheduled/confirmed status only
  because it was never advanced to completed isn't counted as booked, and
  `next_visit_at` is the next *future* visit (was: earliest-ever, possibly past).
- **Channel/identifier guard**: the channel picker allowed choosing Email for a
  phone-only lead (or SMS for an email lead), which dispatched to an invalid
  recipient and persisted the message as FAILED. `send_human_message` now rejects
  with `channel_identifier_mismatch` before creating an undeliverable
  conversation; the composer surfaces a clear message.
- **Channel-scoped counts**: with `?channel=X` the pending/booked counts were
  computed before the channel filter, so the chip badges didn't match the rows.
  Counts are now computed over the channel-filtered set.
- **Tests +4**: past visit not booked (+ next_visit_at is the future one),
  mismatched channel rejected without creating a conversation, create-when-missing
  uses a compatible channel (whatsapp→sms), counts scoped by channel.

## [0.21.0] — 2026-05-28

### Communications inbox — leads buzón with badges, filters, priority

New **Inbox** tab in the Nav (with a pending counter): a mailbox-style view of
leads with open conversations. Each lead shows its priority (🔥/🟡/⚪), a
**pending-channel badge** (✉️ Email / 💬 SMS / 🗣️ Voice) when it's waiting for our
reply, and a 📅 **Visit** badge with date if a visit is booked; leads with nothing
pending show **✅ Up to date**.

- **Filters**: Pending (default) / With visit / All. **Auto-sorted by priority**
  (score desc; within a score, the longest-waiting first). "Pending" = the lead's
  last message is inbound and we haven't replied/handled it since.
- **Mark handled** removes a lead from pending (stored in `Lead.meta` — no
  migration); it re-arms only when a new inbound arrives. Replying from the
  conversation also clears it (last message becomes outbound). "Reply" opens the
  lead's unified conversation.
- **Backend**: `services/inbox.py` (derived state via grouped queries — no N+1:
  last message per lead, channels per lead, next active visit) + `api/v1/inbox.py`
  (`GET /api/v1/inbox?filter=pending|booked|all`, `GET /inbox/count` for the nav
  badge, `POST`/`DELETE /inbox/{id}/handled`). Behind the same `require_auth` gate
  as the rest of the data API.
- **Tests +5**: pending reflects last inbound by channel; handled suppresses then a
  new inbound re-arms; `filter=booked` only with-visit ordered by date; priority
  sort + coherent count; mark-handled idempotent + isolated + 404.

## [0.20.0] — 2026-05-28

### Unified multichannel lead thread + channel picker + real email (plumbing)

A lead's conversation is now a **single timeline merging all channels** (SMS +
email + WhatsApp), time-ordered, each bubble showing its channel icon; the header
lists the active channels. Previously only the most-recently-active channel showed.

- **New endpoint** `GET /api/v1/conversations/{lead_id}/timeline` — merges messages
  across all of the lead's conversations (each tagged with its channel); returns
  `channels[]`, `primary_channel`, and per-channel summaries; 200 with empty arrays
  when the lead has no conversation yet. `MessageOut` now includes `channel`.
- **Channel picker** in the composer (SMS / Email active; Voice disabled "coming
  soon", Phase 13). Sending on a channel the lead hasn't used creates that
  conversation. `send_human_message(channel=…)` (auto-picks when omitted —
  backward compatible) rejects voice; `HumanMessageIn.channel` is
  `Literal["sms","email","whatsapp"] | None` (voice → 422).
- **Fix**: sent messages now appear instantly (client-side timeline refetch via an
  `onSent` callback) instead of relying on `router.refresh()`, which didn't re-run
  the client component effect — the outbound didn't show until a full reload.
- **Real email (plumbing)**: `docker-compose.yml` now passes
  `EMAIL_SIMULATED` / `RESEND_API_KEY` / `RESEND_FROM` / `RESEND_WEBHOOK_SECRET`
  to the backend (was missing); `RESEND_FROM` default moved to a **dedicated
  subdomain** (`realtors.ekoaiautomation.com`) — never mixed with Eko AI Main's
  `biz.ekoaiautomation.com`. New `docs/setup-email.md` (subdomain + Cloudflare DNS,
  isolated from the sales platform).
- **Tests +8**: timeline (2-channel merge ordering, id tiebreak, empty 200) +
  channel selection (reuse existing conversation, create when missing, voice 422 +
  service-level `unsupported_channel`, auto-pick when channel omitted).

## [0.19.0] — 2026-05-27

### Sign in with Apple

Adds a **"Sign in with Apple"** button on `/login`, below Google under the same
"or" divider. Coexists with the password and Google flows — none replaces the
others. It reuses the **same office allow-list as Google** (the list is keyed on
the email, not the provider), so an already-allowed email signs in via Apple with
the same role.

- **Web popup flow** (Sign in with Apple JS, `usePopup: true`): Apple authenticates
  in a popup and returns the `id_token` in-page; the frontend POSTs it to
  `POST /api/v1/auth/login/apple`.
- **Backend verification**: `verify_apple_id_token` validates the identity token's
  **RS256** signature against Apple's public keys (`appleid.apple.com/auth/keys`),
  plus `iss == https://appleid.apple.com`, `aud == APPLE_CLIENT_ID` (the Services
  ID), expiry and `email_verified`. Role resolved via the shared
  `resolve_email_access`. No client secret / `.p8` key needed — only the public
  Services ID. Apple Private Relay emails (`@privaterelay.appleid.com`) log in only
  if explicitly allow-listed.
- **Config**: `APPLE_CLIENT_ID` (backend) + `NEXT_PUBLIC_APPLE_CLIENT_ID` +
  `NEXT_PUBLIC_APPLE_REDIRECT_URI` (frontend, inlined at build), wired through
  `docker-compose.yml` + `frontend/Dockerfile` like Google. `GET /api/v1/auth/me`
  now reports `apple_signin_enabled`. New dependency `pyjwt[crypto]`.
- New component `frontend/components/ui/AppleSignInButton.tsx`; `docs/setup-apple-signin.md`.
- **Tests +4**: `verify_apple_id_token` (happy path with mocked JWKS + decode;
  rejects not-configured + unverified email), `/me` reports the flag, and the Apple
  login flows (pinned admin + DB member + denied) reusing the Google allow-list.

## [0.18.0] — 2026-05-27

### Version button + changelog viewer in the dashboard

Adds a version pill (`v0.18.0`) in the top-right of the Nav (next to the language
switcher). Clicking it opens a modal listing the full version history (version,
date, title, bullet changes) read from `lib/version.ts` — mirroring Eko AI Main.

- Modal closes on ESC, click-outside or the Close button; locks body scroll while
  open; rendered via a portal. Dashboard violet/noir palette, EN/ES i18n.
- New component `frontend/components/ui/VersionButton.tsx`, mounted in
  `components/ui/Nav.tsx`.

## [0.17.0] — 2026-05-27

### Add Lead — manual lead creation (demo + operational) with AI kickoff

Adds an **Add Lead** button + modal on `/leads` to create a lead by hand. One
flow, two uses: (1) the realtor poses as a client to experience the agent
live, and (2) the realtor enters a real referral/contact into their CRM. Either
way the lead enters the **same pipeline** as auto-captured ones — scoring, intent
classification, property matching and follow-ups.

- **First-message kickoff**: an optional "first message from the client" is
  injected as an INBOUND message and triggers the full AI turn (classify → reply
  → send through the chosen channel) via the same path a real webhook takes. On
  save the dashboard lands directly on the lead's conversation with the AI reply
  already generated.
- **Channels**: SMS (default) and Email work today; Voice shows as disabled
  ("coming soon", Phase 13) and WhatsApp is omitted for now. The backend only
  accepts `sms`/`email` for the kickoff so it can't create an undeliverable
  conversation.
- **Backend**: `POST /api/v1/leads` (`LeadCreate`, `extra="forbid"`) with dedupe
  by identifier (409 on conflict), marks `meta.source="manual"` (NOT a demo flag
  → first-class lead, not wiped by `seed_demo --reset`) and rescores on create.
  Reuses `handle_inbound_message` for the first turn; sits behind the same
  `require_auth` as the rest of the data API.
- **Frontend**: `AddLeadButton` modal (dashboard violet/noir palette),
  `leadsApi.create` + `LeadCreate` interface, EN/ES i18n.
- **Tests +5**: create without message (source=manual + score + no conversation),
  create with first message (mocked LLM → conversation + inbound/outbound),
  duplicate 409, missing phone 422, unknown field 422.

## [0.16.2] — 2026-05-27

### Fix — Google login 401'd (missing `requests` transport dependency)

The Google button rendered but selecting an account failed with "Google sign-in
failed". `google-auth`'s `verify_oauth2_token` uses `google.auth.transport.requests`
to fetch Google's public keys, and `requests` is an **optional** dependency of
`google-auth` — it wasn't in `requirements.txt`, so verification raised
`requests library is not installed` → 401. (Password login was never affected.)

- Added `requests==2.32.3` to `backend/requirements.txt`.
- Regression test: `verify_google_id_token` on a malformed token must fail with
  `invalid_id_token`, not `google_auth_library_missing` — so an absent transport
  dep is caught in CI (the existing tests mocked verification and missed it).

## [0.16.1] — 2026-05-27

### Fix — wire the Google Sign In env vars into the containers

v0.16.0 shipped the Google Sign In code but `docker-compose.yml` didn't pass the
`GOOGLE_*` vars to the backend, so `GOOGLE_ADMIN_EMAILS` never reached the
container and the bootstrap admin wasn't seeded into `allowed_users`.

- Backend `environment:` now passes `GOOGLE_CLIENT_ID`, `GOOGLE_ADMIN_EMAILS`,
  `GOOGLE_ALLOWED_EMAILS`, `GOOGLE_ALLOWED_DOMAIN`.
- Frontend gets `NEXT_PUBLIC_GOOGLE_CLIENT_ID` as a **build arg** (Next.js inlines
  `NEXT_PUBLIC_*` at build time — declared in the Dockerfile, not runtime env).

## [0.16.0] — 2026-05-27

### Google Sign In (GIS) + admin-managed team access

Adds "Sign in with Google" on `/login` (coexists with the password) **and**
admin-managed access control. The allow-list moves out of env vars into the
database so an admin edits it live from a restored, admin-only **Settings** tab.

#### Auth model

- The session token now carries **identity + role** (`admin` | `member`), still
  an HMAC-signed `eko_auth` cookie (no new dependency, no JWT lib).
- **Password login → admin** (master key; lockout-proof fallback). **Google login**
  takes its role from the access list.
- **`POST /api/v1/auth/login/google`** verifies the Google ID token (signature +
  `aud == GOOGLE_CLIENT_ID` + `email_verified`) via `google-auth`, resolves the
  email against the access list, and mints the role-bearing cookie. Not on the
  list → `401 email_not_in_allow_list` (safe default deny).
- **`GET /api/v1/auth/me`** now returns `role` + `google_signin_enabled`.

#### Team / access (admin-only)

- New `allowed_users` table (email, role, added_by) — Alembic `008`.
- **`/api/v1/team`** CRUD (`require_admin`): list / add / change-role / remove.
  Guards: cannot demote or remove an env-pinned admin; cannot remove the **last**
  admin.
- **`GOOGLE_ADMIN_EMAILS`** (env) pins bootstrap admin(s) — always admin, seeded
  into the table on startup, immutable from the UI.
- The **entire Settings page is admin-only** now (`/api/v1/settings` +
  `/api/v1/team` under `require_admin`; hidden + 403 for members).

#### Frontend

- **`/login`** shows the GIS "Sign in with Google" button (via `@react-oauth/google`)
  when configured; coexists with the password.
- **Settings** restored to the nav (gear), shown only to admins. New **Team /
  Access** panel: add Gmail addresses, set role, promote/remove; env-pinned admins
  shown as immutable "owner".
- `lib/api.ts` `teamApi` + `MeResult.role`; i18n `settings.team.*` (EN + ES).

#### Config & docs

- `.env.example`: `GOOGLE_CLIENT_ID`, `GOOGLE_ADMIN_EMAILS`, `GOOGLE_ALLOWED_EMAILS`,
  `GOOGLE_ALLOWED_DOMAIN`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
- `docs/setup-google-signin.md` updated for the DB-managed team + bootstrap admin.

## [0.15.2] — 2026-05-27

### Nav reorder — Discovery · Leads · Properties · Analytics · API · EN

- Reordered the top nav to **Discovery, Leads, Properties, Analytics, API, EN**
  (language switcher) — Discovery leads (the prospecting flow starts there).
- **Settings** was removed from the top bar to match the requested menu; the page
  is still reachable at `/settings`.

## [0.15.1] — 2026-05-27

### Discovery — SIMULATED fallback per category with no real provider

- In real mode (`DISCOVERY_SIMULATED=false`, how the ROG demo runs) only
  `investor_llc` returned data (Colorado SOS, free); the seller categories +
  `renter` came back **empty** because they have no free real source (ATTOM is
  paid, FSBO needs a licensed feed) — so most of Discovery looked broken.
- **Fix**: when a category has no configured real provider (or it returns
  nothing), Discovery falls back to that category's curated SIMULATED leads, so
  all 7 categories stay demoable. Real data (Colorado SOS now, ATTOM once keyed)
  takes precedence when present.
- Test: in real mode, `fsbo` with no provider still returns leads.

## [0.15.0] — 2026-05-27

### Discovery v2 — search reoriented to real-estate leads (not businesses)

Discovery now finds **people likely to buy / rent / sell** real estate, not
generic businesses — the whole point of a realtor product. Backed by research
(see [`docs/discovery-realestate-research.md`](docs/discovery-realestate-research.md)).

#### Lead categories (how agents actually prospect)
- **Sellers**: `fsbo` (For Sale By Owner), `expired` (expired listings),
  `absentee` (out-of-state owners), `preforeclosure` (distressed),
  `high_equity` (long-tenure / likely-to-sell).
- **Buyers**: `investor_llc` (real-estate investor LLCs), `renter`
  (renters / relocators).

#### What changed
- Each discovered lead carries **motivation** ("listing expired 2 weeks ago",
  "notice of default recorded"), **timeline** (immediate / 3-6mo / exploring),
  **property type** and **estimated value**. Enrichment uses these to classify
  `intent` (seller → `valuation`, buyer → `buy`/`rent`) and to weight the score
  by motivation + urgency.
- **SIMULATED-first**: ~17 curated realistic Denver-metro leads across the
  categories — $0, no keys. Real per category: `investor_llc` via **Colorado SOS
  (free)**; `absentee`/`preforeclosure`/`high_equity` via **ATTOM**
  (`ATTOM_API_KEY`, key-gated); `fsbo`/`expired`/`renter` need a licensed feed
  (stay SIMULATED).
- API: `POST /discovery/search` now takes **`category`** (+ optional `query`
  refine) instead of `sources`. `BusinessOut` / `Lead.meta` carry
  motivation/timeline/property_type/est_value.
- Frontend: **lead-category preset chips** (Sellers / Buyers) replace the source
  toggles; results show motivation + timeline + type + value; a **DNC/TCPA
  compliance note** is shown (leads are prospects, not consented contacts). i18n
  EN/ES.
- Tests updated to category-based search.

## [0.14.4] — 2026-05-27

### Fix — surface the real API error (no more "body stream already read")

- The API client (`lib/api.ts`) read an error response body twice (`res.json()`
  then `res.text()` in the `catch`), which threw *"Failed to execute 'text' on
  'Response': body stream already read"* and **masked the real error** — a backend
  500 showed up as that confusing message instead.
- Fix: an `errorDetail()` helper reads the body **once** as text, then tries
  `JSON.parse` to pull out `detail`. Applied to `api()` and `discoveryApi.upload()`.
- Context: this surfaced when the backend returned 500 because the ROG disk was
  100% full and Postgres was stuck in recovery (crash-loop on "No space left on
  device"). Freed ~93 GB of Docker build cache and the DB recovered; this fix
  ensures the *real* error shows next time.

## [0.14.3] — 2026-05-27

### Discovery — server-side enrichment (no longer depends on the browser)

Leads passed through the flow but stayed unenriched. **Root cause**: enrichment
only fired from the **frontend** loop over **newly created** leads — so leads
imported before classification (v0.14.2), skipped by dedupe on re-import, or left
when the user closed the tab, never got enriched (`score 0`, no intent).

- **Fix**: a server-side enrichment worker. `enrich_pending_leads()` finds
  discovery leads still unclassified (`score == 0`) and enriches them; it runs as
  an in-process loop (`ENRICHMENT_ENABLED`, every 120s, mirroring the follow-ups
  worker) plus a manual `POST /api/v1/discovery/enrich-pending`. Enrichment no
  longer depends on the browser — every discovery lead ends up classified.
- **Retry cap**: `enrich_lead` tracks `meta.enrichment.attempts`; the sweep gives
  up on a lead after 3 failures so it won't retry forever.
- **Backfill**: on deploy, the worker (or the manual endpoint) classifies the
  older leads that were sitting at `score 0` / no intent.
- The frontend per-lead loop stays for immediate progress feedback; the worker is
  the safety net. Tests +1 (sweep only touches unclassified discovery leads,
  respects the cap, leaves conversation leads alone).

## [0.14.2] — 2026-05-26

### Discovery — imported leads are now classified (intent + 🔥 score) like the rest

Imported discovery leads showed up bare in `/leads` (status `new`, no intent,
score `0` ⚪) next to worked leads with 🔥 / qualified / buy badges. Enrichment now
**also classifies and scores** the lead so it carries the same `IntentBadge` +
`ScoreBadge`.

- The enrichment LLM now also returns **`intent`** (`buy` / `rent` / `valuation` /
  `other` — best-fit if the contact could be a client, else `other`) and
  **`relevance`** (0-10). `enrich_lead` sets `lead.intent` and computes
  `lead.score` + `score_breakdown` via a prospect-lead scoring (no conversation
  to score): `partner_type` (referral_partner 35 / prospect 32 / vendor 18 /
  competitor 6 / other 12) + `relevance×2` + real contact (+25) + website (+10),
  mapped to `hot ≥67 / warm ≥34 / cold` with the same thresholds as `scoring.py`.
- A referral-partner mortgage broker with contact + high relevance → 🔥 hot; a
  competitor with no contact → ⚪ cold. The leads list ranks them by score
  alongside conversation leads.
- Status stays `new` (honest — freshly sourced, unworked). If enrichment fails the
  lead is still saved, just unclassified.
- Tests +3: `_coerce` of intent/relevance, `discovery_score` tiers, and the happy
  path now asserts `lead.intent`, `lead.score > 0`, and
  `score_breakdown.source == "discovery_enrichment"`.

## [0.14.1] — 2026-05-26

### Hotfix — widen `leads.phone` 32 → 254 (discovery import was 500-ing)

- Importing a discovery lead with a long identifier (a LinkedIn URL, or the
  synthetic `discovery:<source>:<slug>:<city>` key) raised HTTP 500
  `StringDataRightTruncationError`. **Root cause**: `leads.phone` was still
  `VARCHAR(32)` in the database even though the model has declared `String(254)`
  since Phase 3 — that migration renamed columns but never actually altered
  `leads.phone` (emails under 32 chars worked by luck).
- **Migration `007_phase12_widen_phone`**: `ALTER leads.phone TYPE VARCHAR(254)`
  to align the DB with the model. Safe widening (no data loss, keeps the unique
  index).
- Without this, the v0.14.0 fix (importing contact-less leads) failed in
  production for most Colorado SOS / LinkedIn results.

## [0.14.0] — 2026-05-26

### Discovery fix — imported leads now save + LLM enrichment with a progress bar

Follow-up to Phase 12 after testing surfaced that "Import selected" appeared to do
nothing.

#### Critical fix: imports were silently dropped

- **Root cause**: `import_business_leads` used `phone | email` as the unique
  identifier, but most sources (Colorado SOS, LinkedIn) carry **neither** → every
  such lead was skipped and never reached `/leads`. The `phone` column is
  `NOT NULL UNIQUE`, so a contact-less lead couldn't even be created.
- **Fix**: identifier now falls back **phone → email → website → synthetic**
  (`discovery:<source>:<slug>:<city>`). Every named business imports, and
  re-imports **dedupe** on that stable key instead of duplicating. Import also
  returns the created `lead_ids`.

#### New: lead enrichment + visible progress

- **`services/enrichment.py`** + **`POST /api/v1/discovery/enrich/{lead_id}`**:
  per lead, the LLM (`json_mode`) infers a normalized **business_type**, a
  **partner_type** (`referral_partner` / `vendor` / `prospect` / `competitor` /
  `other`), a one-line **summary**, an **outreach_angle**, and **tags** — stored
  in `meta.enrichment`. Flags `contact_missing` when there's no real phone/email.
  Graceful (mirrors `classifier.py`): LLM down or bad JSON → `status="failed"`,
  never raises, never loses the lead.
- **Progress bar**: after import, the frontend enriches lead-by-lead with a real
  **X/N progress bar**, then shows a summary + a **"View in Leads"** link.
- `/leads` table renders contact-less discovery leads cleanly (synthetic id → `—`
  with a search glyph; `linkedin.com/in/…` URLs with a globe glyph).

#### Tests

- **+9**: `lead_identifier` fallback + deterministic synthetic key; import with no
  contact **now creates + dedupes + returns `lead_ids`**; `_coerce`
  (invalid `partner_type` → `other`, tag string → list capped at 4); `enrich_lead`
  happy path (persists `meta`, `contact_missing`) + graceful on LLM failure + bad JSON.

## [0.13.0] — 2026-05-26

### Phase 12 — Discovery: lead search (4 sources) + import from any file

Adds proactive lead sourcing — until now leads were inbound-only (WhatsApp /
email / SMS). A realtor can now go find new business leads, or bulk-import an
existing contact database in any file format.

#### Search (4 sources, preview-and-select)

- New **Discovery** tab (mirrors the Eko AI sales platform): search **Google
  Maps, Yelp, LinkedIn, Colorado SOS** for businesses, see a checklist preview,
  pick which to import.
- **`services/discovery.py`** — ported + adapted from the sales platform's
  discovery agent (Paperclip dropped). SIMULATED-first like `listings.py`:
  `DISCOVERY_SIMULATED=true` (default) serves a curated set of plausible CO
  businesses with **zero keys**. Real adapters per source, each degrading to
  `[]` without its key: **Colorado SOS** (public Socrata API — **free, no key**),
  **Yelp** (Fusion), **Google Maps** (Outscraper), **LinkedIn** (SerpApi).

#### File import (any format)

- **`services/file_import.py`** — `extract_text` routes by extension: **PDF**
  (`pypdf`), **XLSX** (`openpyxl`), **images JPG/PNG** via OCR (`pytesseract` +
  `tesseract-ocr` in the Dockerfile), CSV/TXT/HTML (stdlib + tag strip). Then
  `extract_leads` runs the text through the LLM (`json_mode`) to pull contacts
  as a JSON array, with the classifier's graceful-degradation style (bad output
  → `[]`, never crashes).

#### Import → leads

- Search/upload return **transient** results (not persisted). `POST
  /api/v1/discovery/import` creates the selected ones as `Lead` rows
  (`status=new`, `meta.source`), **deduped** by identifier (phone, else email)
  against existing leads. No new table / migration.

#### API + frontend + config

- API under **`/api/v1/discovery`** (`/search`, `/upload` with a
  `FILE_IMPORT_MAX_MB=25` cap, `/import`) — protected by `require_auth`.
- Frontend **`/discovery`**: `DiscoveryPanel` (4 toggleable source chips + a
  reusable `ResultsList` checklist) + `FileImport` (drag-drop). Discovery link
  in the nav (Search icon). i18n EN/ES.
- `config` + `.env.example` + compose: `DISCOVERY_SIMULATED`,
  `YELP_API_KEY` / `OUTSCRAPER_API_KEY` / `SERPAPI_API_KEY` (reuse the sales
  platform keys), `FILE_IMPORT_MAX_MB`. `requirements`: `pypdf` / `openpyxl` /
  `pillow` / `pytesseract`. New **`docs/setup-discovery.md`**.

#### Tests

- **+13 (total 145)**: `test_discovery.py` (6 — simulated search returns
  businesses, source filtering, `max_results` cap, `sanitize_email`, import
  creates + dedupes, import without identifier skips) + `test_file_import.py`
  (7 — `extract_text` plaintext/csv/html-strip/empty, `extract_leads` parses a
  JSON array, tolerates prose, bad output → `[]`, empty text skips the LLM).

Voice (VAPI / Retell) renumbered to Phase 13.

## [0.12.0] — 2026-05-26

### Phase 11 — Pilot hardening: dashboard auth + analytics

Makes the product safe and measurable to hand to a paying office.

#### Dashboard auth (one office = one shared password)

- **`/login`** page + **`AuthGuard`** (redirects to login when the session is
  missing). HMAC-signed session token in an httpOnly cookie (no new dependency).
  **Sign-out** in the nav.
- **`require_auth`** gate on the data API (leads / conversations / visits /
  settings / properties / analytics); webhooks + health stay open. Gated by
  **`AUTH_ENABLED`** — default **off** (dev + the public demo stay open); the
  installer turns it on with a password. Startup **WARN** if `APP_ENV=production`
  and `AUTH_ENABLED=false`.
- `config` + `.env.example` + compose: `AUTH_ENABLED` / `DASHBOARD_PASSWORD` /
  `AUTH_SECRET` / `AUTH_TTL_HOURS`. `scripts/install.sh` now prompts for a
  dashboard password and enables auth.

#### Analytics

- **`GET /api/v1/analytics`** + **`/analytics`** page: funnel by status,
  conversion rate, leads by channel, by score tier (🔥/🟡/⚪), average first-
  response time, and new leads per day (14d). No chart library (div bars).

#### Tests

- **+6 (132 total)**: auth service (password / token / tamper / expiry) + the
  gate (open when disabled; 401 → login → cookie when enabled) + analytics envelope.

#### Roadmap

- Voice (VAPI/Retell) renumbered to **Phase 12**.

## [0.11.0] — 2026-05-26

### Phase 10 — Autonomous nurture + in-conversation listing offers

The agent now works leads **while you sleep**, and offers real inventory in chat.

#### Autonomous follow-ups

- **`FollowUp` model** + Alembic `006` (lead / visit / kind / status /
  `scheduled_for`, UNIQUE(visit, kind) → idempotent enqueue).
- **`services/followups.py`** — `enqueue_for_visit` schedules a 24h-before
  **reminder** + a post-visit sequence (**24h** "how was it?", **72h** nudge,
  **7d** "new similar listings"). `process_due_followups` sends the due ones,
  **skipping** human takeover, cancelled visits, and the 72h nudge if the lead
  already replied. Bilingual templates, sent as the AI agent via the lead's channel.
- **In-process worker** (`main.py` asyncio loop, `FOLLOWUPS_ENABLED` +
  `FOLLOWUPS_INTERVAL_SECONDS`) + **`scripts/run_followups.py`** for cron. Booking
  a visit enqueues the sequence.

#### Agent offers listings in-conversation

- When a lead is buy/rent with a known zone, the orchestrator injects the **real
  matched listings** into the system prompt (only those, never invented) so the
  agent offers them naturally — closing the Phase 7 loop (matching was
  dashboard-only before).
- **Fix**: the matcher crashed on `float * Decimal` when the budget came fresh
  from the classifier (swallowed → empty matches). Normalized with `Decimal(str())`.

#### Tests

- **+6 (126 total)**: follow-up scheduling / due-processing / skip rules +
  agent-gets-real-listings-in-prompt.

#### Roadmap

- Voice (VAPI/Retell) renumbered to **Phase 11** (still deferred).

## [0.10.0] — 2026-05-26

### Multilingual dashboard (English default + Spanish) with a language switcher

The realtor dashboard is now multilingual: **English by default, Spanish second**,
with a **language switcher** (globe + EN/ES) in the nav on **every page**.

- **`lib/i18n.tsx`** — client `LanguageProvider` + `useI18n` hook + full EN/ES
  dictionaries. The choice persists to `localStorage` and syncs `<html lang>`.
  `t(key)` falls back to English, then the key.
- **Every UI string** goes through `t()`: nav, pages, badges (status / intent /
  score / visit), leads table + detail, composer, suggestions, property matches,
  visits, booking dialog, properties grid, settings, takeover toggle, messages.
- **Locale-aware formatters** — `relativeTime` / `exactTime` / `formatBudget`
  (USD, en/es) + visit & booking dates follow the active language.
- Pages use a client `PageHeader`; the lead-detail page is now a client component.
  `/about` landing copy refreshed (MLS matching).

This pairs with the agent already replying in the lead's language (Phase 3) — now
the realtor's interface is bilingual too.

## [0.9.1] — 2026-05-26

### SMS hardening — A2P `MessagingServiceSid` + delivery status callbacks

Two production improvements to the SMS channel, surfaced by reading Twilio's API docs:

- **`send_sms` via `MessagingServiceSid`** — when `TWILIO_MESSAGING_SERVICE_SID`
  is set, outbound goes through the A2P 10DLC-registered Messaging Service (the
  Twilio-recommended path for US delivery) instead of the bare `From` number.
  Falls back to `TWILIO_PHONE_NUMBER`.
- **Delivery status callbacks** — new `POST /api/v1/webhooks/sms/status`. With
  `TWILIO_STATUS_CALLBACK_URL` set, `send_sms` asks Twilio to POST status updates
  (`sent` → `delivered`/`undelivered`/`failed` + `ErrorCode`); the backend
  reflects the final state on the outbound `Message` so the dashboard shows real
  delivery (and logs carrier errors like **30034** = A2P 10DLC unregistered).
- `config.py` + `.env.example` + compose: `TWILIO_MESSAGING_SERVICE_SID` +
  `TWILIO_STATUS_CALLBACK_URL`.
- **`docs/setup-twilio.md`** expanded: A2P 10DLC registration (Sole Proprietor vs
  Standard), the Messaging Service webhook override gotcha, and STOP/HELP opt-out
  (handled by Twilio's default Advanced Opt-Out).
- Tests **+4 (120 total)**: status mapper + status-callback e2e.

## [0.9.0] — 2026-05-26

### Phase 9 — SMS channel (Twilio)

A third channel: SMS via Twilio, on the same multichannel architecture as
WhatsApp and email. SIMULATED-first, so it works without an account.

#### Backend

- **`services/sms.py`** — `send_sms` (SIMULATED logs / real Twilio REST API),
  `verify_twilio_signature` (HMAC-SHA1 over the request URL + sorted POST params,
  keyed by the auth token), `parse_inbound_sms` → `ParsedMessage(channel="sms")`.
- **`POST /api/v1/webhooks/sms`** — parses Twilio's form, validates the signature
  (unless SIMULATED), hands off to the orchestrator, returns empty TwiML (the
  reply is sent asynchronously via REST). Signature URL comes from
  `TWILIO_WEBHOOK_URL` or is rebuilt from forwarded headers.
- Dispatcher gains an `sms` branch; idempotency via UNIQUE `messages.external_id`
  (the `MessageSid`).
- `config.py` + `.env.example` + compose: `SMS_SIMULATED` (default true) +
  `TWILIO_ACCOUNT_SID` / `AUTH_TOKEN` / `PHONE_NUMBER` / `WEBHOOK_URL`.
- `scripts/simulate_inbound_sms.py` for smoke testing.

#### Docs

- **`docs/setup-twilio.md`** — account + number + webhook + signature + cost/safety
  notes.

#### Tests

- **+9 (116 total)**: `test_sms_service.py` (7) + `test_sms_webhook_e2e.py` (2).

#### Roadmap

- Voice (VAPI/Retell) remains **Phase 10**, deferred until a provider account exists.

## [0.8.0] — 2026-05-26

### Phase 8 — Lead intelligence (scoring + prioritization + digest)

Leads are now scored and ranked so the realtor knows who to call first — no
external accounts needed (it scores signals the pipeline already produced).

#### Backend

- **`leads.score`** (0-100, indexed) + **`score_breakdown`** (JSON) — Alembic `005`.
- **`services/scoring.py`** — `compute_lead_score` is deterministic and cheap:
  intent (20) · budget (15) · engagement (15) · urgency (12) · zone (10) ·
  recency (10) · visit (10) · property_type (8), then a **status gate**
  (WON/LOST → 0, PAUSED → ½). Returns an explainable breakdown + tier. No
  per-lead LLM call. `rescore_lead` / `rescore_all` (grouped queries).
- The orchestrator **recomputes the score after every inbound turn**.
- **API**: `score`/`score_breakdown` in `LeadOut`; `sort=score|recent` (default
  `score`); `GET /leads/digest` (top hot/active leads); `POST /leads/rescore-all`.
- **`scripts/daily_digest.py`** — cron-friendly hot-leads digest.

#### Frontend

- **`ScoreBadge`** — 🔥 hot (≥67) / 🟡 warm (≥34) / ⚪ cold, in the leads table
  (now score-sorted) and the lead detail header.
- **`HotLeadsPanel`** — "Leads calientes — a quién llamar primero" on `/leads`,
  fed by `/leads/digest`.

#### Tests

- **+11 (107 total)**: `test_scoring.py` (8 pure) + `test_lead_digest.py` (3 API).

#### Roadmap

- SMS (Twilio) → **Phase 9**, Voice (VAPI/Retell) → **Phase 10** — both still
  deferred until the external accounts exist.

## [0.7.0] — 2026-05-25

### Phase 7 — MLS / IDX listings (RESO) + per-lead property matching

The agent now works against real-estate inventory: listings are ingested from a
RESO Web API feed (SIMULATED in dev), browsable at `/properties`, and matched to
each lead's intent / zone / budget on the lead detail.

#### Backend

- **`Property` model reworked for the USA**: `source` (`reso`/`idx`/`mls`/`manual`),
  `status` (`active`/`pending`/`sold`/`off_market`), `bedrooms`, `bathrooms`
  (half-baths, `2.5`), `sqft`, `property_type`, `address`/`city`/`state`/`zip_code`,
  `zone` (neighborhood), `latitude`/`longitude`, `photos`, `description`,
  `listed_at`. Alembic `004` drops + recreates the (empty) EU placeholder table.
- **`services/listings.py`**:
  - `fetch_listings` — SIMULATED returns a curated 9-listing Miami set; real mode
    queries a **RESO Web API** (OData) feed and maps the RESO Data Dictionary
    fields. Configured via `RESO_BASE_URL` + `RESO_ACCESS_TOKEN`.
  - `sync_listings` — idempotent upsert by `(source, external_id)`.
  - `match_properties_for_lead` — intent gate (rent vs sale) + zone + budget
    (±10%) + property type, ranked by price.
- **Endpoints**: `GET /properties` (filters), `POST /properties/sync`,
  `GET /properties/{id}`, `GET /leads/{id}/matches`.
- **`scripts/sync_listings.py`** ingest CLI (cron-friendly). Config + `.env.example`
  + compose env (`LISTINGS_SIMULATED` default true, `RESO_*` for prod).

#### Frontend

- **`/properties`** — grid of listing cards with zone / max-price filters and a
  **Sincronizar MLS** button.
- **`MatchesSection`** on the lead detail — "Propiedades sugeridas" matched to the
  lead, each with **Enviar al lead** (sends a formatted blurb via the composer).
- **Propiedades** nav link.

#### Docs

- **`docs/setup-mls.md`** — connecting a real RESO Web API / IDX feed + the
  matching rules + an IDX-compliance note (why the public demo stays SIMULATED).

#### Tests

- **+12 (96 total)**: `test_listings_service.py` (5) + `test_properties_api.py`
  (7 — idempotent sync, filters, 404s, buy-lead matches sale-only, rent-lead
  matches rentals-only).

## [0.6.0] — 2026-05-25

### Phase 6 — Single-customer installer + branding panel + public demo

The product is now installable by a single office in one command, brandable
from the dashboard, and demoable from a live public URL — and CI is green for
the first time since Phase 1.

#### Branding panel (Settings API + `/settings` page)

- **`GET/PUT /api/v1/settings`** over the `AgentSettings` singleton (auto-created
  with defaults). `PUT` is a partial update; `languages` is normalized to
  lowercase + de-duped. Empty body → 400, unknown field → 422.
- **`/settings`** dashboard page: agency name + phone, agent persona (system
  prompt), greeting template, languages (es/en/pt/fr chips), and business hours
  (per-day open/close or closed). A **Configuración** link is in the nav.
  Changes apply immediately to new auto-replies.

#### Single-customer installer

- **`scripts/install.sh`** — interactive installer: checks prerequisites
  (Docker/Compose/daemon), generates a `.env` with **strong random secrets**
  (`POSTGRES_PASSWORD`, `WHATSAPP_VERIFY_TOKEN`, mode `600`, never printed),
  builds + starts the stack, waits for the health check, runs
  `alembic upgrade head`, and sets the agency branding via the API. Channels stay
  **SIMULATED** unless explicitly opted in. `--no-prompt` for provisioning scripts.
- **`docs/install.md`** — full single-office install + channel-enable + upgrade
  guide (no GPU — the LLM is cloud-hosted Kimi + MiniMax).

#### Public demo

- **`backend/scripts/seed_demo.py`** — idempotent demo dataset (*Sunset Realty
  Group*, Miami): 6 bilingual EN/ES leads + realistic conversations + 2 visits
  (scheduled / completed). Every row is tagged `meta.demo=true`; `--reset` wipes
  only the demo rows, `--keep-settings` preserves branding.
- **`deploy/cloudflared/config.example.yml`** + **`docs/setup-demo.md`** — a
  **dedicated** Cloudflare Tunnel for `inmo-demo.ekoaiautomation.com`, isolated
  from the sales-platform tunnel. Safety model: all channels SIMULATED (a visitor
  can never trigger a real send), seed data only, optional Cloudflare Access.

#### CI (green for the first time since Phase 1)

- **Backend**: added a real Postgres service + `alembic upgrade head` so the
  DB-backed tests actually run instead of erroring on a missing server. Ruff now
  ignores the 3 rules that conflict with intentional idioms (`B008` FastAPI
  `Depends`/`Query` defaults, `UP042` `str`+`Enum` for pg_enum, `UP037`
  SQLAlchemy quoted forward-refs) and auto-fixes the rest.
- **Frontend**: dropped `cache: npm` (there's no `package-lock.json`, so the
  cache step was aborting the whole job before tsc/lint).

#### Tests

- **+7 (84 total)**: `test_settings_api.py` (GET auto-create, PUT update +
  persistence, partial update, languages normalize/dedupe, empty-body 400,
  unknown-field 422, empty-languages 422). The singleton model test no longer
  couples to a specific `agency_name`.

## [0.5.0] — 2026-05-25

### Phase 5 — Calendar booking (Cal.com) + dashboard VisitsSection

The realtor can now book property visits from the dashboard. `/leads/[id]`
shows a **Visitas** section under the conversation with upcoming + past
visits, an **Agendar visita** button that opens a slot picker (next 7 weekdays,
groups by day, click slot + optional address/notes → Confirm), and a per-card
cancel.

#### Backend

- **`Visit` model** + Alembic migration `003_phase5_visits` (5 columns +
  `external_booking_id` UNIQUE for idempotency + status enum).
- **`services/calendar_cal.py`** — Cal.com v2 API wrapper:
  - `list_available_slots(start, end, timezone, busy_starts)` —
    SIMULATED returns weekday slots at 10/11/14/15/16 in-memory; production
    calls Cal.com `/v2/slots/available` with `cal-api-version: 2024-08-13`.
  - `create_booking(start_time, attendee_name, email, phone, notes, tz, duration)`
    — SIMULATED returns `calcom-sim-<uuid>` ids no-network; real Cal.com
    `POST /v2/bookings` otherwise.
  - `cancel_booking(external_id)` — IDs starting with `calcom-sim-` always
    cancel locally even in production mode (lets you clean up dev data).
- **Endpoints**:
  - `GET /api/v1/leads/{id}/calendar/slots?days=7&timezone=UTC`
  - `POST /api/v1/leads/{id}/calendar/book` → `Visit`
  - `GET /api/v1/leads/{id}/visits`
  - `POST /api/v1/visits/{id}/cancel` `{reason?}`
- Slots **excludes already-booked starts** for the same lead (`busy_starts`
  set built from active visits) so no double-booking.
- Attendee email/phone auto-picked from `lead.phone` (email if it contains `@`,
  phone otherwise). Real Cal.com requires email; SIMULATED accepts phone-only.

#### Frontend

- **`VisitsSection`** — lists upcoming + past visits with status badges,
  formatted ES dates, address, notes, per-card cancel button.
- **`BookingDialog`** — modal slot picker grouped by day, optional address +
  notes, real-time validation, `router.refresh()` style update via
  `onBooked()` callback.
- **`VisitStatusBadge`** — color-coded badge for the 5 visit statuses.
- `lib/api.ts` — `calendarApi.slots/book` + `visitsApi.list/cancel` + types.

#### Config

- + `CALENDAR_SIMULATED=true` (dev default — no Cal.com account required)
- + `CALCOM_BASE_URL=https://api.cal.com`
- `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID` from Phase 0 now actually used.

#### Tests (+13, total 77)

- `test_calendar_service.py` (7): simulated slots weekday-only, hours match
  the constant, busy_starts filter, list_available_slots simulated branch,
  create_booking returns `calcom-sim-` id, cancel_booking returns True,
  `calcom-sim-` id cancels locally even when SIMULATED=false.
- `test_visits_api.py` (6): /slots returns weekday slots, /slots 404 on
  missing lead, /book persists Visit with `calcom-sim-` id, /visits lists
  inserted, cancel flips status + rejects re-cancel, /slots excludes
  already-booked starts (no double-booking).

#### Docs

- `docs/setup-calcom.md` — Cal.com account + event type + API key + smoke
  test + troubleshooting matrix.

## [0.4.0] — 2026-05-25

### Phase 4 — Composer manual + AI reply suggestions

Completes the human-takeover loop. Phase 2 added the toggle that pauses the AI
agent; Phase 4 adds the UI to actually reply from the dashboard, plus an AI
helper that drafts 3 options the realtor can pick / edit / send.

#### Frontend

- **`Composer`** component below the chat in `/leads/[id]`: textarea +
  character counter (0/4000) + Send button. Sends via the lead's last-active
  channel — no channel picker needed for the common case.
- **"Sugerir respuestas"** button generates 3 alternative replies from the
  LLM. Each suggestion is a clickable card that fills the textarea — the
  realtor can edit before sending. Powered by the same Kimi + MiniMax fallback
  used by the agent itself.
- `router.refresh()` after a successful send → the new outbound bubble appears
  immediately, no page reload.
- Errors render inline below the composer (no toast/modal), keeping the
  realtor's attention on the conversation.

#### Backend

- **`POST /api/v1/leads/{id}/messages`** — accepts `{ "text": ..., "subject"?: ... }`.
  Auto-picks the channel from the most recently-active Conversation. For email,
  derives `Re: <subject>` from the last inbound + threads via `In-Reply-To`
  header. Persists as `Message(sender=HUMAN, direction=OUTBOUND)` and routes
  through the existing `_dispatch_send()` dispatcher.
- **`POST /api/v1/leads/{id}/suggestions`** — accepts `{ "count": int }`
  (clamped to `[1, 5]`). Builds a system prompt asking for a JSON array of N
  diverse short replies + the language-steering line from Phase 3. Parses the
  array tolerantly (matches first `[...]` block, drops empties, coerces to
  strings).
- **Degrades gracefully**: any LLM failure / invalid JSON / missing lead /
  empty conversation returns `{"suggestions": [], "error": "..."}` with HTTP
  200 so the UI shows an empty state instead of crashing.

#### Orchestrator

- Two new functions in `app/services/conversation.py`:
  - `send_human_message(lead_id, text, db, subject?)` — dispatches via the
    existing channel dispatcher and persists with `sender=HUMAN`.
  - `generate_reply_suggestions(lead_id, db, count=3)` — re-uses the same
    history-build + language-detection pipeline as the auto-reply, but with a
    "give me 3 options as a JSON array" prompt.

#### Tests

- **63 passing** on live ROG Postgres (+8 new):
  - human-send happy path (WhatsApp SIMULATED → outbound persists SENT
    with synthetic wamid).
  - human-send lead not found → `{status: error, error: lead_not_found}`.
  - human-send empty text → HTTP 400.
  - human-send lead without any Conversation → `error: no_active_conversation`.
  - suggestions happy path (3 quoted in valid JSON).
  - suggestions with prose around the JSON (parser extracts the array).
  - suggestions LLM returns non-JSON → empty list + error field.
  - suggestions count=99 clamps to 5.

## [0.3.0] — 2026-05-25

### Phase 3 — Multichannel + Email (Resend) + Bilingual (USA pivot)

**Strategic pivot**: target customers shift from EU real-estate offices
(WhatsApp-first) to USA realtors where SMS, Email and phone calls dominate.
WhatsApp remains an optional channel for international clients. Roadmap
reordered: Phase 4=SMS (Twilio), Phase 5=Voice (VAPI/Retell), Phase 6=Calendar
booking (moved from Phase 3), Phase 7=MLS/IDX, Phase 8=installer.

#### Multichannel refactor

- Schema rename to channel-agnostic names:
  - `messages.wa_message_id` → `external_id` (120 → 255 chars)
  - `messages.wa_status` → `delivery_status`
  - `conversations.wa_thread_id` → `external_thread_id` (80 → 255)
  - `leads.phone` widened 32 → 254 chars (RFC 5321 max email length — same
    column doubles as identifier for whatsapp/sms/voice and email)
- New `messages.subject` column (nullable, email-only).
- New `conversations.channel` index (queries filter on it constantly).
- `ParsedMessage` moved to `app/services/_common.py` with `channel`,
  `external_id`, `from_identifier`, `content`, `subject`, `thread_id` —
  single shared type emitted by every channel parser.
- Orchestrator routes outbound through `_dispatch_send(channel, ...)` →
  `whatsapp_send` / `email_send` (lazy imports). One conversation per
  `(lead, channel)`: a lead writing via both WhatsApp AND email gets two
  active conversations.

#### Email channel (Resend)

- `services/email.py`:
  - `send_email(to, subject, body_text, in_reply_to)` POSTs to
    `api.resend.com/emails` with threading headers.
  - `parse_inbound_email(payload)` returns `ParsedMessage(channel="email")`
    with subject + `thread_id` from In-Reply-To/References/Message-ID.
  - `verify_resend_signature(...)` Svix-style HMAC-SHA256 with multi-sig
    header support (key rotation).
  - `EMAIL_SIMULATED=true` (dev default) logs outbound instead of POSTing —
    no Resend account or domain DNS required.
- `POST /api/v1/webhooks/email` — same idempotency contract as the WhatsApp
  webhook (200 + UNIQUE `external_id` catches retries).
- New env vars: `EMAIL_SIMULATED`, `RESEND_API_KEY`, `RESEND_FROM`,
  `RESEND_WEBHOOK_SECRET`.

#### Bilingual agent

- `services/i18n.py` — `detect_language()` (langdetect, deterministic seed) +
  `pick_supported_language()` (clamps to AgentSettings.languages whitelist) +
  `language_instruction()` (steering line for the system prompt).
- Orchestrator detects on the **latest inbound only** (no bias from historical
  AI replies), picks `target_lang`, appends an "IDIOMA: el cliente escribe
  en X. Responde EXCLUSIVAMENTE en X" line to the system prompt.
- Classifier accepts optional `language_hint` so it disambiguates words like
  "rent" (EN) vs "renta" (ES, can mean income). JSON output values still
  English (rent/buy/valuation/other) regardless of input language.

#### Dashboard

- `MessageBubble` renders a channel icon next to the sender label (envelope
  email / message-circle WhatsApp / message-square SMS / phone voice) +
  shows the email subject above the bubble when channel="email".
- `LeadsTable` shows a heuristic glyph (email vs phone) next to the
  identifier so the realtor knows at a glance which channel the lead used.
- API client (`lib/api.ts`) interfaces updated to new field names.

#### Tests

- **55 passing** on live ROG Postgres (+10 new):
  - `test_email_service.py` (8) — signature accept/reject/missing/wrong-secret/
    multi-sig-one-matches + parser minimal/threading/html-fallback/non-received
    skipped/missing-from-skipped + send_email SIMULATED.
  - `test_i18n.py` (9) — detect ES/EN, short-text fallback, pick_supported,
    language_instruction both personas, unknown lang fallback.
  - `test_email_webhook_e2e.py` (1) — end-to-end POST → Lead (email
    identifier), Conversation(channel="email"), 2 Messages with subject +
    threading.
- Existing tests updated to use `external_id` / `delivery_status`.

## [0.2.0] — 2026-05-25

### Phase 2 — Realtor dashboard (UI for the Phase 1 backend)

What was protocol-only after v0.1.0 now has a face. The realtor can open
`http://<host>:3004/leads` and see the leads the AI captured, drill into
any conversation, and click one button to take over from the agent.

#### Frontend (Next.js 14 App Router)

- **`/leads`** — paginated list with status + intent filters (querystring-based,
  Suspense-wrapped so SSR works). Each row shows name, phone, status badge,
  intent badge, zone, budget range, relative time of last message, and a "Humano"
  pill when human_takeover is on.
- **`/leads/[id]`** — detail page with:
  - Lead header (avatar, name, phone, status + intent badges, last activity).
  - Metadata grid (zona, presupuesto, tipo, urgencia, created/updated timestamps).
  - **Takeover toggle** (top-right of header) — one-click PATCH to flip
    `human_takeover`. While ON, the orchestrator skips AI auto-reply (Phase 1
    already enforces this).
  - Conversation thread (chat-style bubbles, inbound left/outbound right,
    per-message LLM provider badge + Meta delivery status + timestamps).
- **`/about`** — public-facing landing kept (the Phase 0 placeholder) for
  sharing the product link. `/` redirects to `/leads`.
- **API client** — typed in `frontend/lib/api.ts` (Lead, Conversation, Message
  interfaces + `leadsApi.list/get/patch` + `conversationsApi.get`). All requests
  go through same-origin `/api/...`, which `next.config.js` rewrites to the
  backend container — works identically from LAN, Tailscale, or future
  Cloudflare tunnel without per-env URLs.
- **Components**: `Nav`, `StatusBadge`, `IntentBadge`, `FilterBar`, `LeadsTable`,
  `MessageBubble`, `LeadDetail`, `TakeoverToggle`. All Tailwind, Eko-violet
  palette, lucide-react icons.

#### Backend

- **`PATCH /api/v1/leads/{id}`** — partial update endpoint. Accepts any subset
  of `name | status | intent | zone | budget_min | budget_max | property_type |
  urgency | human_takeover`. Empty body → 400. Unknown field → 422 (Pydantic
  `extra='forbid'`). Missing lead → 404.

#### docker-compose

- Frontend now reads `INTERNAL_API_URL` at runtime for the rewrite (defaults
  to `http://backend:8000`). Build arg `NEXT_PUBLIC_API_URL` defaulted to `/api`
  since client JS no longer touches an absolute backend URL.

#### Tests

- `test_leads_api.py` (+8): list envelope, get 404, PATCH takeover roundtrip,
  PATCH partial update preserves untouched fields, PATCH empty 400, PATCH
  unknown field 422, PATCH invalid enum 422, PATCH 404. Total **33 passing**.

#### Brand

- Final rename Inmobiliario → **Eko AI Realtors** in `<title>`, landing copy,
  README, CLAUDE.md.

## [0.1.0] — 2026-05-25

### Phase 1 CORE — WhatsApp 24/7 + Kimi/MiniMax fallback + Lead capture

The product is now functional end-to-end at the protocol layer: an inbound
WhatsApp message → upsert Lead → save inbound message → classify intent →
generate AI reply → save outbound message → send. Frontend dashboard is still
Phase 2 (next).

#### Identity & infrastructure

- `CLAUDE.md` at repo root: anti-patterns ("never touch sales platform repos
  or containers"), port map across all 4 stacks on the ROG, brand name
  "Eko AI Realtors" vs repo name `Eko-AI-RealEstate`, LLM decisions
  (Kimi+MiniMax, NOT Anthropic OAuth for customer traffic), phase status.
- `docker-compose.yml` port remap to `5434/6381/8011/3004` (no collisions with
  sales prod, sales main dev, or pricing-v2 preview).
- Container rename `eko-realestate-*` for unambiguous identity.
- `.github/workflows/ci.yml`: ruff + pytest (backend) + tsc + lint (frontend)
  on every PR to main.
- GitHub repo: 10 topics, milestones for Phases 1–5, brand-aligned description.
- Memory file `project_eko_ai_realestate.md` + MEMORY.md pointer for
  cross-session continuity.

#### Database (SQLAlchemy 2 async + Alembic)

- `backend/app/db/base.py` — async engine + sessionmaker + get_db() FastAPI dep
  + `pg_enum()` helper (uses `.value` lowercase for Postgres enum members, not
  Python NAME).
- 5 models in `backend/app/models/`:
  - `Lead` — phone (UNIQUE), name, status enum (7 states), intent enum
    (rent/buy/valuation/other), budget_min/max, zone, property_type, urgency,
    last_message_at, human_takeover, meta (JSON), timestamps.
  - `Conversation` — lead_id FK CASCADE, channel, wa_thread_id, status, summary,
    started_at/last_at.
  - `Message` — conversation_id FK CASCADE, direction (inbound/outbound), sender
    (lead/agent/human), content, **UNIQUE wa_message_id** (webhook idempotency),
    wa_status, llm_provider, llm_model, created_at.
  - `Property` — placeholder for Phase 4 (Idealista/Fotocasa scrapers).
  - `AgentSettings` — singleton (id=1) with Spanish defaults for agent_persona,
    greeting_template, languages, business_hours.
- Baseline migration `20260525_1200_phase1_baseline.py` creates the 5 tables
  + indices + FK cascades + enum types.

#### LLM client (Kimi primary + MiniMax fallback)

- `backend/app/services/llm.py` — single entry `generate_reply()`. Inline
  fallback per request: if Kimi times out / 429 / 5xx, retries against MiniMax
  in the same request before raising `LLMUnavailable`.
- Both providers use the `anthropic` Python SDK with custom `base_url`
  (Anthropic-messages protocol).
- `json_mode=True` appends a "return JSON only" steer for the classifier.
- A/B test script (`backend/scripts/llm_ab_test.py`) ran 5 representative
  Spanish realtor prompts through both providers; results:
  - Kimi: avg 3,371 ms / 5/5 OK / more concise
  - MiniMax: avg 5,626 ms / 5/5 OK / more conversational
  - Decision: keep Kimi primary, MiniMax fallback (both produce natural ES).

#### Intent classifier

- `backend/app/services/classifier.py` — `classify_intent(messages)` returns
  `IntentResult` Pydantic schema (intent + confidence 0-1 + entities).
- Entities extracted: zone, budget_min, budget_max, property_type, urgency.
- Coerces `"1.500€"` strings to `1500.0` floats.
- Three failure modes degrade gracefully to `intent=OTHER + raw_response`:
  LLMUnavailable, JSON not parseable, JSON valid but schema mismatch.

#### WhatsApp webhook + orchestrator

- `backend/app/services/whatsapp.py`:
  - `verify_signature()` — HMAC-SHA256 with `WHATSAPP_APP_SECRET`,
    constant-time compare.
  - `parse_inbound_message()` — flattens Meta's nested
    entry/changes/value/messages tree; non-text types persisted as
    `[imagen]/[audio]/[video]/...` placeholders.
  - `send_text_message()` — POSTs to Meta Graph API; LOGS instead when
    `WHATSAPP_SIMULATED=true` (dev default).
- `backend/app/services/conversation.py` — `handle_inbound_message()`
  orchestrates the full 10-step turn: lead upsert → conv get-or-create →
  idempotency check → save inbound → human_takeover bypass → build history →
  classify intent (apply if confidence ≥ 0.55, never overwrite existing values)
  → load AgentSettings → generate reply → save outbound (PENDING) → send →
  update status (SENT/FAILED).
- `backend/app/api/v1/webhooks/whatsapp.py`:
  - `GET /api/v1/webhooks/whatsapp` — Meta verification handshake.
  - `POST /api/v1/webhooks/whatsapp` — signature verify (skipped in SIMULATED)
    → parse → orchestrator per message; always returns 200 unless body is
    malformed (Meta retries non-200; idempotency handles retries cleanly).
- Startup log warning if `WHATSAPP_SIMULATED=true` AND `APP_ENV=production`.

#### API routes

- `GET /api/v1/leads` — paginated list with `?status=` + `?intent=` filters.
- `GET /api/v1/leads/{id}` — detail.
- `GET /api/v1/conversations/{lead_id}` — most recent conversation + full
  message history ordered chronologically.

#### Tests (23 total, all passing on live ROG Postgres)

- `test_signature.py` (7) — HMAC valid, invalid, missing, wrong-prefix,
  body-tampered, wrong-secret, empty-secret.
- `test_llm_fallback.py` (4) — primary OK no fallback, primary timeout →
  fallback, both fail → LLMUnavailable, primary unconfigured → skip to fallback.
- `test_classifier.py` (7) — clean JSON, confidence clamp, prose-wrapped JSON,
  invalid JSON degrades, invalid enum degrades, LLMUnavailable degrades,
  budget coercion.
- `test_webhook_e2e.py` (4) — GET handshake accept, GET handshake reject,
  inbound text creates lead + reply, duplicate wa_message_id is idempotent
  (only 2 messages persist after 2 POSTs).
- `test_models.py` (2) — Lead/Conversation/Message roundtrip,
  AgentSettings singleton defaults.
- `test_health.py` (1) — health endpoint contract.

#### Scripts & docs

- `backend/scripts/simulate_inbound.py` — CLI to POST a simulated WhatsApp
  payload to the webhook for manual testing.
- `backend/scripts/llm_ab_test.py` — side-by-side LLM A/B with 5 Spanish
  realtor prompts.
- `docs/setup-whatsapp.md` — full production setup walkthrough (Meta App
  creation, secrets, webhook registration, troubleshooting matrix).
- `docs/architecture.md` — trust boundary + stack rationale (Postgres,
  Ollama-as-option, port choices).
- `docs/roadmap.md` — Phase 1 ✅ done, Phase 2-5 status.

## [0.0.1] — 2026-05-25

### Bootstrap

- Repo initialized with project skeleton (FastAPI + Next.js + Postgres + Redis)
- `docker-compose.yml` brings up the full stack locally
- Health endpoint at `GET /api/v1/health`
- Placeholder landing page on the frontend
- README + architecture + roadmap docs
- `.env.example` with the env vars required for Phase 1 (WhatsApp + LLM + DB)

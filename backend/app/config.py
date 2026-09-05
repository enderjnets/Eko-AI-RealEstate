"""Settings — read from env vars. Never put secrets in code."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Eko AI Realtors"
    # Reported by / and /api/v1/health and printed at startup. Kept in step
    # with frontend/lib/version.ts: it was left at 0.0.1 for eleven releases,
    # so the API could not tell an operator which build was live.
    APP_VERSION: str = "0.79.0"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://eko:eko_local_pass@db:5432/eko_realestate"
    # Connects as a role WITHOUT bypassrls, so the tenant policies actually bind.
    # Postgres superusers ignore RLS even with FORCE — pointing DATABASE_URL at
    # one makes every isolation test pass while isolating nothing, so the app
    # role and the migration role are deliberately different connections.
    DATABASE_URL_APP: str = (
        "postgresql+asyncpg://eko_app:eko_app_local_pass@db:5432/eko_realestate"
    )
    # Reserved for login lookup, background workers and the superuser panel —
    # the three paths with no single org to act as. Defaults to DATABASE_URL,
    # which owns the tables.
    DATABASE_URL_BYPASS: str = ""

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # ─── LLM (Phase 1) ──────────────────────────────────────────────────
    # Both providers speak the `anthropic-messages` HTTP protocol → we use the
    # `anthropic` Python SDK with a custom `base_url` per provider. Fallback is
    # INLINE per request: if PRIMARY times out or errors, the same request
    # retries against FALLBACK before erroring out.
    LLM_PRIMARY: str = "kimi"  # "kimi" | "minimax"
    LLM_FALLBACK: str = "minimax"
    LLM_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_TOKENS_DEFAULT: int = 600

    KIMI_API_KEY: str = ""
    KIMI_BASE_URL: str = "https://api.kimi.com/coding"
    KIMI_MODEL: str = "kimi-for-coding"

    MINIMAX_API_KEY: str = ""
    MINIMAX_BASE_URL: str = "https://api.minimax.io/anthropic"
    MINIMAX_MODEL: str = "MiniMax-M2.7"

    # Third link in the chain, and the first one that does not depend on a house.
    # Speaks the OpenAI chat protocol (not Anthropic), so it is handled apart —
    # see `_openai_chat_generate`. Free tier, which is why it sits ahead of the
    # ROG: it is always up, and the laptop is a bonus when it happens to be
    # awake. Without a key the link simply does not exist, exactly like Kimi and
    # MiniMax without theirs. No timeout of its own: it reuses
    # LLM_TIMEOUT_SECONDS, because Groq is fast and a fourth setting would be
    # three more edits for nothing.
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Local Google open model (Gemma) via Ollama — a zero-cost FINAL fallback so
    # the agent can still reply when the paid providers are out of quota. Speaks
    # Ollama's own /api/chat (not the Anthropic protocol), so it's handled apart.
    OLLAMA_ENABLED: bool = False
    OLLAMA_BASE_URL: str = "http://172.20.0.1:11434"
    OLLAMA_MODEL: str = "gemma3:4b"
    OLLAMA_TIMEOUT_SECONDS: float = 120.0  # local cold-load + generation can be slow

    # How often the monitor re-checks that the last-resort provider can answer.
    # Probing /api/tags is local and free and does not load the model, so this
    # can be frequent; it is the *alert* that has to be rare, not the check.
    LLM_MONITOR_INTERVAL_SECONDS: int = 300
    # Sender for operator alerts. NOT a tenant identity: a monitor has no org,
    # and an alert to us is not a reply to somebody's lead. Empty = alerts are
    # logged and not sent, which is stated out loud rather than failing quietly.
    OPS_ALERT_FROM: str = ""

    # ─── WhatsApp Business Cloud API (Phase 1) ──────────────────────────
    # OFF by default, and for most installs that is the final answer: a US
    # brokerage reaches clients by text, call and email, and WhatsApp is simply
    # not one of its channels. Enabling it is a decision with a Meta Business
    # app behind it, not a leftover to be tidied up.
    #
    # This exists because `WHATSAPP_SIMULATED` alone was a trap. It gates two
    # unrelated things — outbound sending AND inbound HMAC verification — so
    # turning simulation off without a configured app secret does not "go
    # live", it makes every inbound webhook return 403 until Meta disables the
    # subscription. The startup guard below refuses that combination outright.
    WHATSAPP_ENABLED: bool = False

    # Only consulted when WHATSAPP_ENABLED. SIMULATED=true means
    # whatsapp.send_text_message() LOGS the outbound payload instead of POSTing
    # to Meta, which is what dev and the test suite want.
    WHATSAPP_SIMULATED: bool = True
    WHATSAPP_VERIFY_TOKEN: str = "change-me"
    WHATSAPP_APP_SECRET: str = ""  # HMAC-SHA256 secret for inbound signature
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    WHATSAPP_GRAPH_API_VERSION: str = "v20.0"

    # ─── Email channel (Phase 3) ────────────────────────────────────────
    # Resend transactional API for outbound + Resend inbound webhook (Svix-signed).
    # When SIMULATED=true (dev default), outbound is LOGGED instead of sent.
    # The from-address uses a subdomain DEDICATED to Realtors — NEVER reuse Eko AI
    # Main's biz.ekoaiautomation.com (separate Resend domain, key + webhook secret).
    # See docs/setup-email.md.
    EMAIL_SIMULATED: bool = True
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "Eko AI Realtors <noreply@realtors.ekoaiautomation.com>"
    RESEND_WEBHOOK_SECRET: str = ""  # Svix-style HMAC secret, may start with `whsec_`

    # ─── Calendar (Phase 5) ─────────────────────────────────────────────
    # When SIMULATED=true (dev default), list_slots returns generated weekday
    # slots and create_booking returns synthetic calcom-sim-<uuid> ids — no
    # Cal.com account needed. Production: set CALCOM_API_KEY + EVENT_TYPE_ID,
    # flip SIMULATED to false.
    CALENDAR_SIMULATED: bool = True
    CALENDAR_PROVIDER: str = "calcom"  # calcom | google (only calcom in Phase 5)
    # The office timezone a new agency starts with. "UTC" was the old default
    # and it silently mis-schedules everything: BookingDialog offered 10:00 and
    # 14:00 UTC, which is 03:00 and 07:00 in Denver, and a caller who said "2pm"
    # got 14:00 UTC. Wrong by six or seven hours until someone opened Settings.
    DEFAULT_TIMEZONE: str = "America/Denver"

    # A reply that hit a provider blip used to be stamped FAILED and forgotten.
    DELIVERY_RETRY_ENABLED: bool = True
    DELIVERY_RETRY_INTERVAL_SECONDS: int = 120

    CALCOM_BASE_URL: str = "https://api.cal.com"
    CALCOM_API_KEY: str = ""
    CALCOM_EVENT_TYPE_ID: str = ""

    # ─── SMS (Phase 9 — Twilio) ─────────────────────────────────────────
    # When SMS_SIMULATED=true (dev default), send_sms() LOGS instead of calling
    # Twilio and the webhook accepts unsigned requests. Production: set the
    # TWILIO_* values and flip SIMULATED to false. TWILIO_WEBHOOK_URL is the exact
    # public URL configured in the Twilio console (used for signature validation
    # behind a proxy); if blank we reconstruct it from forwarded headers.
    # The public form takes name, email, phone and message, and until now all
    # four were optional — so a lead could arrive reachable only by SMS. That
    # was fine while SMS worked. It does not: Twilio accepts the message and the
    # carrier drops it (error 30034, the number is not registered for A2P
    # 10DLC), so a phone-only lead today cannot be reached by ANY automatic
    # channel and only a human calling them recovers it.
    #
    # A setting rather than a constant, because this is a statement about the
    # world and not about the product: when A2P registration completes, this
    # goes back to false without a deploy.
    CAPTURE_REQUIRE_EMAIL: bool = True

    # Interim funnel (28-ago-2026): appointments are arranged PERSONALLY — the
    # form notifies the agent and she calls back — because Cal.com's conflict
    # source is still only the brand calendar, so an automated booking can
    # double-book the agent. With this on, the automated lanes stop offering
    # or taking appointment times (they promise a call-back instead); booking
    # from the dashboard, by a human, is untouched. Flip back to false when the
    # agent's own calendar is connected and PROVEN (a busy hour of hers stops
    # being offered) — that flip is the reactivation, no deploy needed.
    BOOKING_OFFERS_PAUSED: bool = False

    # ─── Landing analytics ───────────────────────────────────────────────
    # What the marketing page reports about itself: page views, how far people
    # scrolled, which sections they reached, taps on "call" and on the consult
    # form. Anonymous by construction — no cookie, no stored IP, no raw user
    # agent — because the question is "did the video bring anybody", not "who".
    #
    # On by default: every day it is off is a day of traffic nobody can account
    # for, and the endpoint writes nothing that would be awkward to delete.
    LANDING_EVENTS_ENABLED: bool = True
    # The rolled-up session row is the record and is kept forever; this bounds
    # only the raw event stream behind it, which answers nothing after a
    # quarter and grows per interaction.
    LANDING_EVENTS_RETENTION_DAYS: int = 90
    # The only thing that bounds how many PERMANENT rows an anonymous caller
    # can create. The rate limit bounds the speed of writing them and not their
    # number, and sessions are never deleted by age — doing that would rewrite
    # the denominator of every historical funnel. Counted per agency, per local
    # day, on session CREATION: a visit already recorded keeps merging, so real
    # traffic is never truncated mid-page. Real traffic will not approach this;
    # a flood reaches it within the hour.
    LANDING_SESSIONS_PER_DAY: int = 20000

    SMS_SIMULATED: bool = True
    TWILIO_ACCOUNT_SID: str = ""
    # Two jobs used to ride on this one value: authenticating what we SEND, and
    # validating the signature on what we RECEIVE. Twilio only requires it for
    # the second — "Twilio hashes the signature with the HMAC-SHA1 hashing
    # algorithm using your account auth token as the secret key" — and there is
    # no alternative credential for that. So it stays, but it is no longer the
    # credential we send with.
    TWILIO_AUTH_TOKEN: str = ""
    # Sending uses an API Key instead, when one is configured. Twilio's own
    # guidance: "Use API keys for all applications. If a key is compromised or
    # no longer used, revoke it to prevent unauthorized access without affecting
    # your other applications."
    #
    # That is the whole point of splitting them. With one value doing both jobs,
    # a single leak hands over the ability to send messages at our expense AND
    # to forge inbound webhooks — and rotating it breaks both halves at once.
    # Revoking a key only stops sending, and can be done without touching the
    # signature path that inbound SMS depends on.
    #
    # The SID here is the API Key's own (`SK…`), NOT the Account SID: it is the
    # basic-auth username. The Account SID still identifies the account in the
    # request path either way. Both empty (the default) falls back to
    # (Account SID, Auth Token), so existing installs keep working untouched.
    TWILIO_API_KEY_SID: str = ""
    TWILIO_API_KEY_SECRET: str = ""
    TWILIO_PHONE_NUMBER: str = ""  # E.164, e.g. +13055551234
    TWILIO_WEBHOOK_URL: str = ""
    # A2P 10DLC: when a number is registered under a Messaging Service, Twilio
    # recommends sending via the service SID (uses the registered campaign + sender
    # pool). If set, send_sms uses MessagingServiceSid instead of From.
    TWILIO_MESSAGING_SERVICE_SID: str = ""
    # Public URL for delivery status callbacks. When set, send_sms asks Twilio to
    # POST status updates (sent→delivered/undelivered/failed + ErrorCode) here, and
    # the backend reflects the final status on the outbound Message.
    TWILIO_STATUS_CALLBACK_URL: str = ""

    # ─── Voice (Phase 13 — VAPI) ────────────────────────────────────────
    # Inbound voice: VAPI runs the call (STT + TTS + realtime LLM) and POSTs
    # server messages to our webhook. `tool-calls` are answered synchronously
    # (e.g. book_visit during the call); `end-of-call-report` ingests the full
    # transcript into the lead's timeline (channel="voice"). When VOICE_SIMULATED
    # =true (dev default), the webhook accepts unsigned requests so tests + the
    # demo work without VAPI. Outbound calling is out of scope this phase.
    VOICE_SIMULATED: bool = True
    VAPI_API_KEY: str = ""  # Bearer for the VAPI REST API (outbound calls, mgmt)
    VAPI_WEBHOOK_SECRET: str = ""  # shared secret sent as `x-vapi-secret` header
    VAPI_ASSISTANT_ID: str = ""  # the Eko AI Realtors assistant
    VAPI_PHONE_NUMBER_ID: str = ""  # the number routed to the assistant
    VAPI_BASE_URL: str = "https://api.vapi.ai"

    # ─── Listings / MLS (Phase 7) ───────────────────────────────────────
    # When SIMULATED=true (dev default), the listings service returns a curated
    # Miami dataset and sync_listings upserts it as MANUAL — no MLS feed needed.
    # Production: set RESO_BASE_URL + RESO_ACCESS_TOKEN (RESO Web API / OData,
    # the USA MLS standard) and flip SIMULATED to false.
    LISTINGS_SIMULATED: bool = True
    LISTINGS_PROVIDER: str = "reso"  # reso | idx | mls
    RESO_BASE_URL: str = ""
    RESO_ACCESS_TOKEN: str = ""
    # ─── MLS Grid / REcolorado (Phase 7b — replication) ─────────────────
    # REcolorado ships its RESO Web API through MLS Grid. We replicate the feed into
    # `properties` incrementally (by ModificationTimestamp) instead of proxying live.
    # Values below are confirmed against the MLS Grid API v2 docs + Best Practices
    # Guide: https://docs.mlsgrid.com/api-documentation/api-version-2.0
    # The sync WORKER is OFF by default so it never spins on errors before the token
    # exists — flip LISTINGS_SYNC_ENABLED on (with RESO creds set).
    RESO_ORIGINATING_SYSTEM: str = "recolorado"  # exact OriginatingSystemName, lowercase
    RESO_PAGE_SIZE: int = 1000  # $top cap when $expand is used (5000 without; 500 default)
    RESO_MAX_PAGES: int = 50  # pagination safety cap; crash-safe (cursor advances per page)
    # MLS Grid ceilings: 2 req/s, 7200 req/h, 40k req/24h, 4 GB/h, 60 GB/24h.
    # Exceeding them suspends the token, so space every page request.
    RESO_MIN_REQUEST_INTERVAL_SECONDS: float = 0.5
    LISTINGS_SYNC_ENABLED: bool = False  # in-process replication worker
    LISTINGS_SYNC_INTERVAL_SECONDS: int = 900  # 15 min — the cadence MLS Grid recommends

    # ─── Discovery / lead search (Phase 12) ─────────────────────────────
    # SIMULATED-first: when true (default) returns a curated synthetic set (demo
    # works with zero keys). When false, each source uses its real adapter if its
    # key is set — Colorado SOS is free (no key); Yelp/Google Maps/LinkedIn reuse
    # the keys from the Eko AI sales platform. See docs/setup-discovery.md.
    DISCOVERY_SIMULATED: bool = True
    YELP_API_KEY: str = ""           # Yelp Fusion (free tier) — legacy business search
    OUTSCRAPER_API_KEY: str = ""     # Google Maps via Outscraper — legacy
    SERPAPI_API_KEY: str = ""        # LinkedIn via SerpApi Google search — legacy
    ATTOM_API_KEY: str = ""          # ATTOM property/owner data — absentee/preforeclosure/high_equity
    FILE_IMPORT_MAX_MB: int = 25

    # ─── Content Studio (v0.52+) ────────────────────────────────────────
    # The cap is enforced by the upload route itself while streaming, not by
    # the body-buffering middleware.
    #
    # 95, not 500, and the number is measured rather than chosen. Against
    # production on 26-ago-2026: 99 MB reached our backend and answered; 120 MB
    # was cut at the edge by Cloudflare with a 413 that our app never saw. The
    # tunnel gives out around 100 MB, so a 500 MB cap was a promise the
    # infrastructure did not keep.
    #
    # 95 rather than 99: the ~100 MB ceiling is where the tunnel was OBSERVED to
    # break, not a documented figure, and a cap set at the edge of a measured
    # cliff fails intermittently instead of cleanly. The cost is real and is not
    # hand-waved — a 96 MB clip that would have squeezed through yesterday is
    # refused today — and a predictable refusal before the upload beats a
    # coin-flip failure after it.
    #
    # WHICH layer answers, corrected after an audit caught the first version of
    # this comment claiming the wrong one: for any client that declares a
    # Content-Length — every browser upload — the 413 comes from
    # `BodySizeLimit` in `main.py`, not from the route's streaming check
    # (`content.py`, `raise HTTPException(413, "Clip exceeds …")`). The route's
    # check is the guard for a CHUNKED body that declares no length. Both are
    # needed; only the middleware one is what a person sees.
    #
    # The honest consequence, and it is a real one: a 4K phone clip over 95 MB
    # cannot be uploaded at all. The answer to that is chunked upload, which is
    # its own piece of work. Until then the number tells the truth, and the
    # browser can warn BEFORE spending the upload instead of after.
    CONTENT_UPLOAD_MAX_MB: int = 95
    # Inside the container; compose mounts a volume here. Media is served only
    # through the authenticated route, never as static files.
    CONTENT_MEDIA_DIR: str = "/data/media"

    # The generation loop. Off by default: turning it on is a per-install
    # decision with an LLM bill attached, and the cap bounds that bill from
    # day one — the pipeline next door ran ten days broken because nobody had
    # put a number on its quota.
    CONTENT_STUDIO_ENABLED: bool = False
    # Bounds DRAFTS. The model bill is up to 2x this: a draft that trips the
    # Fair Housing filter gets exactly one rewrite call before it stops.
    # Dónde mandamos a quien ve el vídeo. Vacío = sin llamada a la acción: un
    # enlace a un dominio que todavía no resuelve es peor que ninguno, y este
    # repo ya decide así en la landing (una sección sin dato desaparece en vez
    # de inventárselo). Se rellena cuando denverhomestory.com esté vivo.
    CONTENT_CTA_URL: str = ""
    # La campaña que se etiqueta en el enlace del pie de cada vídeo. Un solo
    # valor para todos: lo que separa una red de otra es `utm_source`, y lo que
    # separa un vídeo de otro es `utm_content`. Cambiarlo por temporada
    # («otoño-2026») es lo que permite comparar tandas sin tocar código.
    CONTENT_UTM_CAMPAIGN: str = "video"

    CONTENT_MAX_DRAFTS_PER_DAY: int = 3
    CONTENT_STUDIO_INTERVAL_SECONDS: int = 3600
    # The render worker (lane A: uploaded clips -> vertical + burned brokerage
    # line). Separate switch from generation: an agency can film clips without
    # ever turning the writer on.
    CONTENT_RENDER_ENABLED: bool = False
    CONTENT_RENDER_INTERVAL_SECONDS: int = 900

    # ─── Publishing to the channels, through Buffer (v0.65) ─────────────
    # One integrator for YouTube, TikTok and Instagram. Simulated by default
    # like every other adapter here: turning it off is a deliberate act with an
    # audience attached.
    BUFFER_SIMULATED: bool = True
    BUFFER_ACCESS_TOKEN: str = ""
    # Which Buffer organization the token is expected to belong to. Not
    # decoration: the publisher asks Buffer for that org's channels and refuses
    # to post unless the configured ids are exactly what came back. The
    # pipeline next door published a video on the wrong channel because a
    # credential path was hard-coded and nothing compared the result against
    # what the profile declared.
    BUFFER_ORG_ID: str = ""
    BUFFER_CHANNEL_YOUTUBE: str = ""
    BUFFER_CHANNEL_TIKTOK: str = ""
    BUFFER_CHANNEL_INSTAGRAM: str = ""
    CONTENT_PUBLISH_ENABLED: bool = False
    CONTENT_PUBLISH_INTERVAL_SECONDS: int = 900
    # How many people actually watched. A public API key (no OAuth): the
    # counters on a published video are public data, so nothing here needs a
    # channel owner's consent, and `videos.list` costs ONE unit per call of up
    # to 50 ids against a 10,000/day quota — a six-hourly tick spends about 4.
    # Off by default: without a key the loop would tick for ever doing nothing.
    YOUTUBE_DATA_API_KEY: str = ""
    CONTENT_METRICS_ENABLED: bool = False
    CONTENT_METRICS_INTERVAL_SECONDS: int = 21600
    # PIECES per day, not posts: one piece is three platforms, and counting
    # posts would let a single video eat three days of budget.
    CONTENT_PUBLISH_MAX_PER_DAY: int = 4
    # Where Buffer fetches the video from. Buffer downloads WHEN THE POST GOES
    # OUT — hours or days later for a queued post — and its documentation says
    # not to use signed or expiring URLs, so this address is stable and the
    # gate is the piece's STATUS instead.
    CONTENT_PUBLIC_BASE_URL: str = ""

    # The doorbell for the approval queue. The owner's existing bot, reused as
    # an extra function — see `services/telegram_notify.py` for the trade that
    # decision carries. Empty means no notice is attempted at all.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    # A short. Conservative on purpose and measured against the platforms on
    # the first real post rather than remembered from a table.
    CONTENT_PUBLISH_MAX_SECONDS: int = 90
    # WHOSE content rail this is. One question, not three: the brokerage line
    # burned into every frame, the Buffer channels, the voice, the music and
    # the domain on the end card all belong to ONE agency, and a video made for
    # anybody else could never be published anyway.
    #
    # It started life as CONTENT_PUBLISH_ORG_ID, guarding only the publisher —
    # and hours later the writer was found generating a second draft every day
    # for the demo organization that migration 015 creates, because
    # `run_for_every_org` sweeps every tenant and nothing told it whose rail
    # this was. Two LLM bills a day, and two image bills once Kling has a key,
    # for content nobody would ever look at.
    #
    # 0 means "the only organization here"; with a second one present the rail
    # refuses to do anything until this names an agency.
    CONTENT_ORG_ID: int = 0

    # ─── The render worker (v0.66) ──────────────────────────────────────
    # When on, lane A stops rendering in this container and queues the work
    # instead. The worker runs on the machine with the media stack, adds
    # subtitles (a speech model has no business next to the process a lead is
    # waiting on) and hands the finished video back.
    #
    # Off means the local renderer keeps working exactly as before — that path
    # is the fallback for an install with no worker and for the days the render
    # machine is down, not dead code.
    RENDER_WORKER_ENABLED: bool = False
    # The worker's only credential. EMPTY MEANS THE QUEUE IS CLOSED (503), not
    # open: a missing secret that degrades to no authentication is how an
    # internal queue silently becomes a public one.
    RENDER_WORKER_TOKEN: str = ""

    # ─── Dashboard auth (Phase 11) ──────────────────────────────────────
    # One deploy = one office → a single shared dashboard password. When
    # AUTH_ENABLED=true, the data API + dashboard require login. Default false so
    # dev + the public demo stay open; the installer turns it on with a password.
    # Backend logs a WARN at startup if APP_ENV=production AND AUTH_ENABLED=false.
    AUTH_ENABLED: bool = False
    DASHBOARD_PASSWORD: str = ""
    # Session signing key. REQUIRED when AUTH_ENABLED — startup refuses
    # without it, and without at least 32 characters. It is deliberately
    # NOT derived from DASHBOARD_PASSWORD any more: the office shares that
    # with whoever answers the phone, and this key alone authenticates the
    # organization claim and the platform-operator claim.
    AUTH_SECRET: str = ""
    AUTH_TTL_HOURS: int = 168  # 7 days

    # ─── Public capture form (Cloudflare Turnstile) ──────────────────────
    # Empty = no captcha, which is the correct default for a fresh install:
    # the endpoint still has the honeypot, the per-IP limit and the global
    # ceiling, and demanding a Cloudflare account before a contact form works
    # would block the install on someone else's dashboard.
    # Set it and verification becomes mandatory AND fail-closed — a captcha
    # that passes everyone when Cloudflare has a bad minute is not a captcha.
    TURNSTILE_SECRET: str = ""

    # ─── Google Sign In (Google Identity Services) ───────────────────────
    # Coexists with DASHBOARD_PASSWORD. When GOOGLE_CLIENT_ID is set, /login
    # shows a "Sign in with Google" button. The backend validates the ID token
    # and resolves the verified email against the access list to a role.
    #
    # Access list precedence (see services/auth.resolve_email_access):
    #   GOOGLE_ADMIN_EMAILS (env)  → admin, immutable bootstrap (lockout-proof)
    #   allowed_users DB rows      → managed in the UI by admins (admin|member)
    #   GOOGLE_ALLOWED_EMAILS (env)→ member (back-compat static allow)
    #   GOOGLE_ALLOWED_DOMAIN (env)→ member (any @domain)
    #   else                       → DENIED (safe default)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_ADMIN_EMAILS: str = ""  # comma-separated; pinned admins, can't be removed via UI
    GOOGLE_ALLOWED_EMAILS: str = ""  # comma-separated lowercased emails (members)
    GOOGLE_ALLOWED_DOMAIN: str = ""  # e.g. "ekoaiautomation.com" (any user @ this domain)

    # ─── Platform operators (cross-tenant) ───────────────────────────────
    # The people who run the SaaS, as opposed to an admin of a client agency.
    # Only these emails get the `su` claim that unlocks /api/v1/platform — the
    # routes that create agencies, map their phone numbers and impersonate them.
    #
    # Without this, the only way to hold `su` was the shared DASHBOARD_PASSWORD
    # session, so a Google-only deployment (docs/setup-google-signin.md tells
    # you to set the password to a random string nobody knows) could never
    # onboard a second agency at all. It also gives impersonation a named actor
    # to record instead of "whoever had the office password".
    # Public self-registration into the demo organization. Advertised in
    # /auth/me since it shipped, and read nowhere — so the flag the frontend
    # renders a signup form from could never actually turn signup off.
    REGISTRATION_ENABLED: bool = True

    PLATFORM_ADMIN_EMAILS: str = ""  # comma-separated; empty = password-only

    @property
    def google_allowed_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.GOOGLE_ALLOWED_EMAILS.split(",") if e.strip()]

    @property
    def google_admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.GOOGLE_ADMIN_EMAILS.split(",") if e.strip()]

    @property
    def platform_admin_emails_list(self) -> list[str]:
        return [
            e.strip().lower() for e in self.PLATFORM_ADMIN_EMAILS.split(",") if e.strip()
        ]

    # ─── Sign in with Apple ──────────────────────────────────────────────
    # Coexists with Google + password. When APPLE_CLIENT_ID (the Services ID,
    # e.g. "com.ekoai.realtors.signin") is set, /login shows the "Sign in with
    # Apple" button. The backend verifies Apple's RS256 identity token (signature
    # against appleid.apple.com/auth/keys, iss + aud + exp) and resolves the
    # verified email against the SAME access list as Google (resolve_email_access).
    # The web popup flow returns the id_token directly, so no client secret /
    # .p8 key is needed for login. Apple Private Relay addresses
    # (@privaterelay.appleid.com) only log in if explicitly allow-listed.
    APPLE_CLIENT_ID: str = ""  # the Services ID — also the token `aud` we validate

    # ─── Follow-ups / nurture (Phase 10) ────────────────────────────────
    # In-process background worker that sends scheduled post-visit follow-ups +
    # visit reminders. Disable to run them only via scripts/run_followups.py (cron).
    FOLLOWUPS_ENABLED: bool = True
    FOLLOWUPS_INTERVAL_SECONDS: int = 300

    # In-process background worker that enriches discovery leads server-side, so
    # enrichment never depends on the browser staying open. Backfills leads that
    # predate classification or were skipped by dedupe on re-import.
    ENRICHMENT_ENABLED: bool = True
    ENRICHMENT_INTERVAL_SECONDS: int = 120

    # ─── The publishing queue ───────────────────────────────────────────
    # Approved videos used to leave with `shareNow` on the next tick, so six
    # posts went out in 107 seconds and "when will this publish?" had no answer
    # to give. With the queue on, each video is handed to Buffer with a due
    # date, ONE PER DAY PER CHANNEL — the owner's rule, in his words: "se
    # publican 1 por bloque de mejor horario, nunca dos a la vez".
    #
    # Buffer has no mutation for a channel's own posting schedule (measured:
    # 14 mutations, none of them schedule), so the rule has to live here, where
    # it can be tested. Turning this off restores the old behaviour without a
    # redeploy, which is the way back if the queue ever misbehaves.
    CONTENT_SCHEDULE_ENABLED: bool = True
    # Local time at the agency, `HH:MM`. One slot a day per channel, at an hour
    # that suits that channel: Buffer's own computed slots for these three sit
    # in the evening for YouTube and Instagram and in the morning for TikTok,
    # so the same video goes out at three different times of day — "never two
    # at once" holds across channels too, not just within one.
    CONTENT_SLOT_YOUTUBE: str = "20:30"
    CONTENT_SLOT_INSTAGRAM: str = "18:30"
    CONTENT_SLOT_TIKTOK: str = "08:30"
    # How much warning Buffer needs. A slot closer than this is not used today;
    # the piece goes to tomorrow's. Buffer fetches the video when the post goes
    # out, and a fetch that starts after the hour has passed is a post that
    # misses it.
    CONTENT_SCHEDULE_LEAD_MINUTES: int = 20

    # ─── CORS ───────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3004"

    @field_validator(
        "CONTENT_SLOT_YOUTUBE", "CONTENT_SLOT_INSTAGRAM", "CONTENT_SLOT_TIKTOK"
    )
    @classmethod
    def _valid_clock_time(cls, v: str) -> str:
        """A mistyped slot must fail at startup, not at the first post.

        Without this, `CONTENT_SLOT_YOUTUBE="8:30pm"` boots a healthy-looking
        container and the fault surfaces days later as "the video never got a
        date", inside a background loop nobody is watching.
        """
        try:
            hour, minute = v.split(":")
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError
            if len(hour) != 2 or len(minute) != 2:
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError(
                f"expected a 24-hour local time as HH:MM, got {v!r}"
            ) from None
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

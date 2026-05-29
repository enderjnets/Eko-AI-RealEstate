"""Settings — read from env vars. Never put secrets in code."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Eko AI Realtors"
    APP_VERSION: str = "0.0.1"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://eko:eko_local_pass@db:5432/eko_realestate"

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

    # ─── WhatsApp Business Cloud API (Phase 1) ──────────────────────────
    # SIMULATED=true (default) means whatsapp.send_text_message() LOGS the
    # outbound payload instead of POSTing to Meta. Required for dev/test
    # without a registered Meta Business app. Backend logs a WARN at startup
    # if SIMULATED=true AND APP_ENV=production.
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
    CALCOM_BASE_URL: str = "https://api.cal.com"
    CALCOM_API_KEY: str = ""
    CALCOM_EVENT_TYPE_ID: str = ""

    # ─── SMS (Phase 9 — Twilio) ─────────────────────────────────────────
    # When SMS_SIMULATED=true (dev default), send_sms() LOGS instead of calling
    # Twilio and the webhook accepts unsigned requests. Production: set the
    # TWILIO_* values and flip SIMULATED to false. TWILIO_WEBHOOK_URL is the exact
    # public URL configured in the Twilio console (used for signature validation
    # behind a proxy); if blank we reconstruct it from forwarded headers.
    SMS_SIMULATED: bool = True
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
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

    # ─── Listings / MLS (Phase 7) ───────────────────────────────────────
    # When SIMULATED=true (dev default), the listings service returns a curated
    # Miami dataset and sync_listings upserts it as MANUAL — no MLS feed needed.
    # Production: set RESO_BASE_URL + RESO_ACCESS_TOKEN (RESO Web API / OData,
    # the USA MLS standard) and flip SIMULATED to false.
    LISTINGS_SIMULATED: bool = True
    LISTINGS_PROVIDER: str = "reso"  # reso | idx | mls
    RESO_BASE_URL: str = ""
    RESO_ACCESS_TOKEN: str = ""

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

    # ─── Dashboard auth (Phase 11) ──────────────────────────────────────
    # One deploy = one office → a single shared dashboard password. When
    # AUTH_ENABLED=true, the data API + dashboard require login. Default false so
    # dev + the public demo stay open; the installer turns it on with a password.
    # Backend logs a WARN at startup if APP_ENV=production AND AUTH_ENABLED=false.
    AUTH_ENABLED: bool = False
    DASHBOARD_PASSWORD: str = ""
    AUTH_SECRET: str = ""  # token signing key; derived from the password if empty
    AUTH_TTL_HOURS: int = 168  # 7 days

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

    @property
    def google_allowed_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.GOOGLE_ALLOWED_EMAILS.split(",") if e.strip()]

    @property
    def google_admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.GOOGLE_ADMIN_EMAILS.split(",") if e.strip()]

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

    # ─── CORS ───────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3004"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

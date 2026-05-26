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
    EMAIL_SIMULATED: bool = True
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "Eko AI Realtors <noreply@realtor-demo.ekoaiautomation.com>"
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

    # ─── Listings / MLS (Phase 7) ───────────────────────────────────────
    # When SIMULATED=true (dev default), the listings service returns a curated
    # Miami dataset and sync_listings upserts it as MANUAL — no MLS feed needed.
    # Production: set RESO_BASE_URL + RESO_ACCESS_TOKEN (RESO Web API / OData,
    # the USA MLS standard) and flip SIMULATED to false.
    LISTINGS_SIMULATED: bool = True
    LISTINGS_PROVIDER: str = "reso"  # reso | idx | mls
    RESO_BASE_URL: str = ""
    RESO_ACCESS_TOKEN: str = ""

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

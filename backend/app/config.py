"""Settings — read from env vars. Never put secrets in code."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Eko AI Inmobiliario"
    APP_VERSION: str = "0.0.1"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://eko:eko_local_pass@db:5432/eko_realestate"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Local LLM (Ollama)
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "qwen2.5:14b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    # WhatsApp Business Cloud API
    WHATSAPP_VERIFY_TOKEN: str = "change-me"
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""

    # Calendar
    CALENDAR_PROVIDER: str = "calcom"  # calcom | google
    CALCOM_API_KEY: str = ""
    CALCOM_EVENT_TYPE_ID: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3003"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

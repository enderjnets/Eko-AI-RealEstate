"""Eko AI Realtors — FastAPI entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import conversations, health, leads, properties, visits
from app.api.v1 import settings as settings_api
from app.api.v1.webhooks import email as email_webhook
from app.api.v1.webhooks import sms as sms_webhook
from app.api.v1.webhooks import whatsapp as whatsapp_webhook
from app.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Backend for Eko AI Realtors — the on-prem AI agent for real-estate offices. "
        "WhatsApp 24/7 + lead capture + intent classification + visit booking."
    ),
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
)

# CORS: dev allows localhost; production tightens via env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(whatsapp_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(email_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(sms_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"])
app.include_router(visits.leads_calendar_router, prefix="/api/v1", tags=["calendar"])
app.include_router(visits.visits_router, prefix="/api/v1", tags=["visits"])
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(properties.router, prefix="/api/v1/properties", tags=["properties"])
app.include_router(properties.lead_matches_router, prefix="/api/v1", tags=["properties"])


@app.on_event("startup")
async def _startup() -> None:
    logger.info(
        "Eko AI Realtors %s starting · env=%s · LLM primary=%s fallback=%s",
        settings.APP_VERSION, settings.APP_ENV, settings.LLM_PRIMARY, settings.LLM_FALLBACK,
    )
    if settings.is_production and settings.WHATSAPP_SIMULATED:
        logger.warning(
            "⚠️  WHATSAPP_SIMULATED=true AND APP_ENV=production — outbound messages will only "
            "be LOGGED, not sent to Meta. Set WHATSAPP_SIMULATED=false before serving real "
            "customer traffic."
        )


@app.get("/")
async def root() -> dict[str, str]:
    """Tiny root endpoint so a healthcheck against / never returns 404."""
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}

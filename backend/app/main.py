"""Eko AI Realtors — FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import analytics, auth, conversations, health, leads, properties, visits
from app.api.v1 import settings as settings_api
from app.api.v1.auth import require_auth
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
# Public / unauthenticated: health, webhooks (own signature auth), auth itself.
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(whatsapp_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(email_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(sms_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])

# Protected data API — require_auth is a no-op unless AUTH_ENABLED.
_auth = [Depends(require_auth)]
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"], dependencies=_auth)
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"], dependencies=_auth)
app.include_router(visits.leads_calendar_router, prefix="/api/v1", tags=["calendar"], dependencies=_auth)
app.include_router(visits.visits_router, prefix="/api/v1", tags=["visits"], dependencies=_auth)
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"], dependencies=_auth)
app.include_router(properties.router, prefix="/api/v1/properties", tags=["properties"], dependencies=_auth)
app.include_router(properties.lead_matches_router, prefix="/api/v1", tags=["properties"], dependencies=_auth)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"], dependencies=_auth)


_followups_task: asyncio.Task | None = None


async def _followups_loop() -> None:
    """Background worker: periodically send due nurture follow-ups (Phase 10)."""
    from app.db.base import get_session_factory
    from app.services.followups import process_due_followups

    interval = max(30, settings.FOLLOWUPS_INTERVAL_SECONDS)
    Session = get_session_factory()
    while True:
        try:
            await asyncio.sleep(interval)
            async with Session() as session:
                await process_due_followups(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Follow-ups worker tick failed: %s", exc)


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
    if settings.is_production and not settings.AUTH_ENABLED:
        logger.warning(
            "⚠️  AUTH_ENABLED=false AND APP_ENV=production — the dashboard + data API are OPEN "
            "(no login). Set AUTH_ENABLED=true + DASHBOARD_PASSWORD before exposing customer data."
        )
    if settings.FOLLOWUPS_ENABLED:
        global _followups_task
        _followups_task = asyncio.create_task(_followups_loop())
        logger.info("Follow-ups worker started (every %ds)", settings.FOLLOWUPS_INTERVAL_SECONDS)


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _followups_task is not None:
        _followups_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _followups_task


@app.get("/")
async def root() -> dict[str, str]:
    """Tiny root endpoint so a healthcheck against / never returns 404."""
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}

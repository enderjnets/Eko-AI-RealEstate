"""Eko AI Realtors — FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    analytics,
    auth,
    conversations,
    discovery,
    health,
    inbox,
    leads,
    properties,
    team,
    visits,
)
from app.api.v1 import settings as settings_api
from app.api.v1.auth import require_admin, require_auth
from app.api.v1.webhooks import email as email_webhook
from app.api.v1.webhooks import sms as sms_webhook
from app.api.v1.webhooks import voice as voice_webhook
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


@app.middleware("http")
async def _record_user_activity(request, call_next):
    """Best-effort per-user engagement tracking: after each authenticated request
    to a tracked /api/v1 section, upsert the session-email's UserActivity row. The
    shared office password (no email) is not tracked. Errors here never affect the
    response."""
    response = await call_next(request)
    try:
        from app.api.v1.auth import _token_from_request
        from app.db.base import get_session_factory
        from app.services.activity import client_ip, record_request, section_for_path
        from app.services.auth import decode_token

        path = request.url.path
        if section_for_path(path):  # only tracked dashboard sections
            payload = decode_token(_token_from_request(request))
            email = (payload or {}).get("email")
            if email:
                async with get_session_factory()() as session:
                    await record_request(
                        session,
                        email=email,
                        source=None,  # set at login; never overwrite here
                        path=path,
                        ip=client_ip(request),
                        user_agent=request.headers.get("user-agent"),
                    )
    except Exception as exc:  # noqa: BLE001 — never break a request for telemetry
        logger.debug("activity middleware skipped: %s", exc)
    return response


# Routers
# Public / unauthenticated: health, webhooks (own signature auth), auth itself.
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(whatsapp_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(email_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(sms_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(voice_webhook.router, prefix="/api/v1/webhooks", tags=["webhooks"])

# Protected data API — require_auth is a no-op unless AUTH_ENABLED.
_auth = [Depends(require_auth)]
# Admin-only — settings + team management (hidden + 403 for members).
_admin = [Depends(require_admin)]
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"], dependencies=_auth)
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"], dependencies=_auth)
app.include_router(inbox.router, prefix="/api/v1/inbox", tags=["inbox"], dependencies=_auth)
app.include_router(visits.leads_calendar_router, prefix="/api/v1", tags=["calendar"], dependencies=_auth)
app.include_router(visits.visits_router, prefix="/api/v1", tags=["visits"], dependencies=_auth)
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"], dependencies=_admin)
app.include_router(team.router, prefix="/api/v1/team", tags=["team"], dependencies=_admin)
app.include_router(properties.router, prefix="/api/v1/properties", tags=["properties"], dependencies=_auth)
app.include_router(properties.lead_matches_router, prefix="/api/v1", tags=["properties"], dependencies=_auth)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"], dependencies=_auth)
app.include_router(discovery.router, prefix="/api/v1/discovery", tags=["discovery"], dependencies=_auth)


_followups_task: asyncio.Task | None = None
_enrichment_task: asyncio.Task | None = None
_listings_sync_task: asyncio.Task | None = None


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


async def _enrichment_loop() -> None:
    """Background worker: enrich discovery leads server-side so it never depends on
    the browser. Backfills leads that predate classification / were skipped on re-import."""
    from app.db.base import get_session_factory
    from app.services.enrichment import enrich_pending_leads

    interval = max(30, settings.ENRICHMENT_INTERVAL_SECONDS)
    Session = get_session_factory()
    while True:
        try:
            await asyncio.sleep(interval)
            async with Session() as session:
                result = await enrich_pending_leads(session, limit=10)
            if result["enriched"]:
                logger.info("Enrichment worker: enriched %d discovery lead(s)", result["enriched"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Enrichment worker tick failed: %s", exc)


async def _listings_sync_loop() -> None:
    """Background worker: replicate the MLS feed (RESO / MLS Grid) into `properties`
    on an interval. No-ops with a one-time warning if a real feed is selected but the
    RESO credentials are missing, so it never spins on errors before the token exists."""
    from app.db.base import get_session_factory
    from app.services.listings import sync_listings

    if not settings.LISTINGS_SIMULATED and (
        not settings.RESO_BASE_URL or not settings.RESO_ACCESS_TOKEN
    ):
        logger.warning(
            "Listings sync worker enabled but RESO_BASE_URL/RESO_ACCESS_TOKEN are unset "
            "(LISTINGS_SIMULATED=false) — worker idle until the feed is configured."
        )
        return

    interval = max(60, settings.LISTINGS_SYNC_INTERVAL_SECONDS)
    Session = get_session_factory()
    while True:
        try:
            await asyncio.sleep(interval)
            async with Session() as session:
                result = await sync_listings(session)
            if result["total"]:
                logger.info(
                    "Listings sync worker: %d created, %d updated",
                    result["created"],
                    result["updated"],
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Listings sync worker tick failed: %s", exc)


async def _seed_admin_users() -> None:
    """Ensure each GOOGLE_ADMIN_EMAILS entry exists as an admin in allowed_users so
    bootstrap admins show up in the Team list. Idempotent; promotes an existing row
    to admin if needed. Best-effort — never blocks startup."""
    from sqlalchemy import select

    from app.db.base import get_session_factory
    from app.models import AllowedUser
    from app.services.auth import ROLE_ADMIN

    pinned = settings.google_admin_emails_list
    if not pinned:
        return
    Session = get_session_factory()
    async with Session() as session:
        for email in pinned:
            row = (
                await session.execute(select(AllowedUser).where(AllowedUser.email == email))
            ).scalar_one_or_none()
            if row is None:
                session.add(AllowedUser(email=email, role=ROLE_ADMIN, added_by="bootstrap"))
            elif row.role != ROLE_ADMIN:
                row.role = ROLE_ADMIN
        await session.commit()


@app.on_event("startup")
async def _startup() -> None:
    logger.info(
        "Eko AI Realtors %s starting · env=%s · LLM primary=%s fallback=%s",
        settings.APP_VERSION, settings.APP_ENV, settings.LLM_PRIMARY, settings.LLM_FALLBACK,
    )
    try:
        await _seed_admin_users()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap admin seed skipped: %s", exc)
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
    if settings.ENRICHMENT_ENABLED:
        global _enrichment_task
        _enrichment_task = asyncio.create_task(_enrichment_loop())
        logger.info("Enrichment worker started (every %ds)", settings.ENRICHMENT_INTERVAL_SECONDS)

    if settings.LISTINGS_SYNC_ENABLED:
        global _listings_sync_task
        _listings_sync_task = asyncio.create_task(_listings_sync_loop())
        logger.info(
            "Listings sync worker started (every %ds)", settings.LISTINGS_SYNC_INTERVAL_SECONDS
        )


@app.on_event("shutdown")
async def _shutdown() -> None:
    for task in (_followups_task, _enrichment_task, _listings_sync_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@app.get("/")
async def root() -> dict[str, str]:
    """Tiny root endpoint so a healthcheck against / never returns 404."""
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}

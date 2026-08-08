"""Eko AI Realtors — FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError

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
from app.api.v1 import platform as platform_api
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



class TenantMiddleware:
    """Pin the acting organization for the whole request.

    Deliberately raw ASGI rather than `@app.middleware("http")`. Starlette's
    BaseHTTPMiddleware runs the downstream app in a *separate* anyio task, so a
    ContextVar set before `call_next` never reaches the endpoint — the org would
    silently stay unset and every request would see zero rows under default-deny.
    A plain ASGI middleware awaits the app in the same task, so the value holds.

    Failing to resolve an org is not an error here: it leaves the value unset,
    and RLS turns that into no rows rather than into everyone's rows.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request
        from starlette.responses import JSONResponse

        from app.api.v1.auth import _token_from_request
        from app.services.auth import token_is_impersonating, token_is_superuser
        from app.services.tenant_context import set_org_id
        from app.services.tenant_resolver import (
            TenantUnresolvable,
            active_orgs,
            needs_tenant,
            resolve_org_for_request,
        )

        path = scope.get("path", "")
        if not needs_tenant(path):
            set_org_id(None)
            await self.app(scope, receive, send)
            return
        try:
            token = _token_from_request(Request(scope))
        except Exception:  # noqa: BLE001 — a malformed header must not 500 the request
            token = None

        try:
            org_id = await resolve_org_for_request(path, token)
        except TenantUnresolvable as exc:
            # 503, not 500: the provider should retry, and the operator needs to
            # see this rather than discover it as another agency's leads.
            logger.error("request refused, no organization — %s", exc)
            await JSONResponse(
                {"detail": "tenant routing unavailable"}, status_code=503
            )(scope, receive, send)
            return

        # A token naming a suspended or deleted organization used to sail
        # through: reads returned nothing and writes 500'd on the RLS check.
        # Suspension has to end access, not just stop the background sweeps.
        #
        # Platform operators are exempt. Their token names organization 1 like
        # anyone else's, so suspending client zero — one PATCH, no confirmation
        # — used to 403 every subsequent request from that session including the
        # one that would un-suspend it, with no way back short of psql. An
        # operator's `su` claim is verified by the same signature as the org
        # claim, so trusting it here is not a downgrade.
        if (
            org_id is not None
            and not token_is_superuser(token)
            and not token_is_impersonating(token)
        ):
            status = (await active_orgs()).get(org_id)
            if status is None or status == "suspended":
                set_org_id(None)
                await JSONResponse(
                    {"detail": "organization is not active; sign in again"},
                    status_code=403,
                )(scope, receive, send)
                return

        set_org_id(org_id)
        await self.app(scope, receive, send)


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


# Registered LAST on purpose. add_middleware prepends, so the last one added is
# the OUTERMOST — which is what TenantMiddleware has to be. Registered before
# _record_user_activity it ended up inside a BaseHTTPMiddleware, whose call_next
# runs downstream in a separate anyio task; the org bound there never propagated
# back out, so the activity middleware ran with no org and every insert into
# user_activity was rejected and swallowed.
app.add_middleware(TenantMiddleware)

# CORS goes on LAST so it ends up OUTSIDE TenantMiddleware. The tenant layer
# answers some requests itself — 403 for a suspended organization, 503 when an
# inbound message cannot be attributed — and those short-circuit responses
# skipped CORS entirely while it was the inner layer. The browser then saw a
# network error instead of a readable status, so the dashboard could not tell
# the user their session had ended.
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
# Platform operator only — creating/suspending tenants and entering them.
# Its own require_platform_admin dependency is the gate; _admin would let any
# client agency's admin in.
app.include_router(platform_api.router, prefix="/api/v1/platform", tags=["platform"])
app.include_router(properties.router, prefix="/api/v1/properties", tags=["properties"], dependencies=_auth)
app.include_router(properties.lead_matches_router, prefix="/api/v1", tags=["properties"], dependencies=_auth)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"], dependencies=_auth)
app.include_router(discovery.router, prefix="/api/v1/discovery", tags=["discovery"], dependencies=_auth)


_followups_task: asyncio.Task | None = None
_enrichment_task: asyncio.Task | None = None
_listings_sync_task: asyncio.Task | None = None


async def _followups_loop() -> None:
    """Background worker: periodically send due nurture follow-ups (Phase 10)."""
    from app.services.followups import process_due_followups
    from app.services.tenant_context import run_for_every_org

    interval = max(30, settings.FOLLOWUPS_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(interval)
            # Per org, not once globally: a worker with no org bound sees zero
            # rows under default-deny RLS and would run forever doing nothing.
            await run_for_every_org(process_due_followups)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Follow-ups worker tick failed: %s", exc)


async def _enrichment_loop() -> None:
    """Background worker: enrich discovery leads server-side so it never depends on
    the browser. Backfills leads that predate classification / were skipped on re-import."""
    from app.services.enrichment import enrich_pending_leads
    from app.services.tenant_context import run_for_every_org

    interval = max(30, settings.ENRICHMENT_INTERVAL_SECONDS)
    # Accumulated across organizations. Keeping only the last org's result meant
    # a tenant that enriched ten leads was invisible if the next enriched none,
    # and with zero active orgs the value stayed None and the tick raised.
    totals: dict[str, int] = {}

    async def _enrich_one_org(session) -> None:
        one = await enrich_pending_leads(session, limit=10)
        for key, value in one.items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value

    while True:
        try:
            await asyncio.sleep(interval)
            # Per org, for the same reason as the follow-ups worker.
            await run_for_every_org(_enrich_one_org)
            if totals.get("enriched"):
                logger.info(
                    "Enrichment worker: enriched %d discovery lead(s) across all orgs",
                    totals["enriched"],
                )
            totals.clear()
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

    from app.db.base import get_bypass_session_factory
    from app.models import AllowedUser
    from app.models.organization import DEFAULT_ORG_ID
    from app.services.auth import ROLE_ADMIN

    pinned = settings.google_admin_emails_list
    if not pinned:
        return
    # Bypass: this runs at startup with no request and therefore no org, so an
    # RLS-enforcing session would find no rows and re-insert a duplicate on
    # every boot. The failure was invisible — the exception is swallowed by the
    # caller, so GOOGLE_ADMIN_EMAILS simply never reached the Team list.
    Session = get_bypass_session_factory()
    async with Session() as session:
        for email in pinned:
            # Scoped to the default org on purpose. This runs on a bypass
            # session, so an unfiltered lookup found the row wherever it lived
            # and promoted it — an operator email that a client agency had added
            # to their own team silently became an admin INSIDE that agency,
            # counted by their "cannot remove the last admin" guard. The
            # operator meanwhile signs into org 1 and never sees it.
            row = (
                await session.execute(
                    select(AllowedUser).where(
                        AllowedUser.email == email,
                        AllowedUser.org_id == DEFAULT_ORG_ID,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                # org_id explicit: a bypass session skips the before_flush stamp.
                session.add(
                    AllowedUser(
                        email=email,
                        role=ROLE_ADMIN,
                        added_by="bootstrap",
                        org_id=DEFAULT_ORG_ID,
                    )
                )
            elif row.role != ROLE_ADMIN:
                row.role = ROLE_ADMIN
            # Commit per email. Email is globally unique, so one address a
            # client agency already claimed used to roll back the whole batch
            # and no pinned admin was seeded at all — swallowed as a warning.
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning(
                    "Bootstrap admin %s is already registered to another "
                    "organization and was not seeded",
                    email,
                )


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
    # Assert the two database roles are what the isolation design assumes. Both
    # failure modes are silent: an app role that bypasses RLS isolates nothing,
    # and a bypass role that does NOT bypass makes every login deny and every
    # worker sweep zero organizations, with nothing in the logs either way.
    try:
        from sqlalchemy import text

        from app.db.base import get_bypass_engine, get_engine

        async with get_engine().connect() as conn:
            app_role = (
                await conn.execute(
                    text(
                        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
        if app_role.rolsuper or app_role.rolbypassrls:
            logger.error(
                "🔴 DATABASE_URL_APP connects as a superuser or a BYPASSRLS role. "
                "Row-level security is NOT being enforced and every agency can "
                "read every other agency's data. Point it at a role created with "
                "NOSUPERUSER NOBYPASSRLS."
            )

        async with get_bypass_engine().connect() as conn:
            bypass_role = (
                await conn.execute(
                    text(
                        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
        if not (bypass_role.rolsuper or bypass_role.rolbypassrls):
            logger.error(
                "🔴 The bypass connection cannot bypass RLS. Login will deny every "
                "user and the background workers will process zero organizations, "
                "both silently. Set DATABASE_URL_BYPASS to a role with BYPASSRLS."
            )
    except Exception as exc:  # noqa: BLE001 — a check must not block startup
        logger.warning("database role check skipped: %s", exc)

    if settings.GOOGLE_ALLOWED_DOMAIN or settings.google_allowed_emails_list:
        logger.warning(
            "⚠️  GOOGLE_ALLOWED_DOMAIN / GOOGLE_ALLOWED_EMAILS grant member access "
            "to the DEFAULT organization only — they predate multi-tenancy and have "
            "no per-org equivalent. A value left over from a single-tenant install "
            "hands everyone who matches it access to client zero's leads. Manage "
            "access through Settings → Team instead."
        )

    # How many organizations can actually take traffic — the demo org and any
    # suspended tenant do not count, which is why a plain COUNT(*) was the wrong
    # test: every install has the demo org, so it always read as "more than one".
    from app.models.organization import DEFAULT_ORG_ID

    try:
        from app.services.tenant_resolver import active_orgs, routable_candidates

        real_orgs = routable_candidates(await active_orgs())
    except Exception as exc:  # noqa: BLE001 — a check must not block startup
        logger.debug("org count check skipped: %s", exc)
        real_orgs = []

    if not settings.AUTH_ENABLED and len(real_orgs) > 1:
        # Hard failure, not a warning. With auth off there is no token, so every
        # request resolves to the default organization no matter who sent it:
        # agency B's dashboard is unreachable and every write it makes lands in
        # agency A. A warning in a startup log does not stop that, and the flag
        # defaults to false in docker-compose.
        raise RuntimeError(
            f"AUTH_ENABLED=false with {len(real_orgs)} active organizations "
            f"{real_orgs}. Every request would resolve to organization "
            f"{DEFAULT_ORG_ID} regardless of who sent it, so a second agency's "
            "data would be both unreachable and written into the first. Set "
            "AUTH_ENABLED=true."
        )

    if len(real_orgs) > 1:
        # A second agency without its own provider account is answered from the
        # first agency's number, so their lead replies to the first agency and
        # the rest of the conversation is written into the wrong tenant. Name
        # the agencies still on the shared account rather than saying "check
        # your configuration".
        try:
            from sqlalchemy import select as _select

            from app.db.base import get_bypass_session_factory
            from app.models.channel_route import ChannelRoute

            async with get_bypass_session_factory()() as session:
                owning = {
                    org_id
                    for (org_id,) in await session.execute(
                        _select(ChannelRoute.org_id).where(
                            ChannelRoute.credential_ref.is_not(None)
                        )
                    )
                }
            sharing = [o for o in real_orgs if o != DEFAULT_ORG_ID and o not in owning]
            if sharing:
                logger.warning(
                    "⚠️  organizations %s have no channel route with their own "
                    "credentials, so their replies go out from the default "
                    "organization's number and address. Their leads will answer "
                    "the wrong agency. Set the *_ref columns via "
                    "PATCH /api/v1/platform/routes/{id}/identity.",
                    sharing,
                )
        except Exception as exc:  # noqa: BLE001 — a warning must not block startup
            logger.debug("outbound identity check skipped: %s", exc)

    if settings.AUTH_ENABLED and len(real_orgs) > 1 and not settings.platform_admin_emails_list:
        logger.warning(
            "⚠️  %d client agencies and PLATFORM_ADMIN_EMAILS is empty, so the "
            "shared DASHBOARD_PASSWORD is the only key to the platform routes "
            "and impersonation has no named actor to audit. Set "
            "PLATFORM_ADMIN_EMAILS to the operators' addresses.",
            len(real_orgs),
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

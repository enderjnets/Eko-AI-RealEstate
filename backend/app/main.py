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
    console,
    conversations,
    discovery,
    health,
    inbox,
    leads,
    properties,
    public,
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
from app.config import Settings, get_settings

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
    # The schema too. Gating only the UI left `/openapi.json` serving the full
    # route and model inventory the DEBUG gate exists to withhold — confirmed
    # 200 on the live host with DEBUG=false.
    openapi_url="/openapi.json" if settings.DEBUG else None,
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

# Nothing here reads a request body larger than a form submission, except the
# one route that imports a client's contact file. One route accepts bodies from
# anonymous callers, there is no reverse proxy — the Cloudflare tunnel points
# straight at uvicorn — and uvicorn imposes no limit of its own, so a 43 MB
# JSON body was accepted, parsed into Python objects and answered 200,
# retaining ~200 MB. A handful of concurrent ones OOMs the single worker and
# takes every tenant's dashboard down with it.
#
# Registered here, between TenantMiddleware and CORS, so the 413 is wrapped by
# CORS. Outside it, a browser saw a bare network error instead of a status it
# could report.
#
# The limit is per path, not global. A single global cap set tight enough for
# the public form silently broke `/api/v1/discovery/upload`, which documents
# FILE_IMPORT_MAX_MB (25 MB by default) and enforces it itself — a realtor's
# 750 KB contact export was refused with no diagnostic.
# Paths whose bodies this middleware must NOT buffer, with the ceiling above
# which it refuses outright. `/api/v1/discovery/upload` is a platform-operator
# file import that documents FILE_IMPORT_MAX_MB and enforces it itself.
#
# Exact match, not a prefix: `startswith` also exempted `/api/v1/discovery/
# uploadZZZ`, which is not a route, so an anonymous caller could make the
# worker buffer megabytes and then answer 404.
#
# And streamed rather than buffered. The exemption is evaluated before any
# authentication — middleware has no session — so buffering it meant an
# anonymous request could make the single worker hold 25 MB before
# `require_platform_admin` got to say 403. The route reads the body itself and
# checks the size, so passing it through costs one copy instead of three.
_STREAM_PATHS: dict[str, int] = {
    "/api/v1/discovery/upload": settings.FILE_IMPORT_MAX_MB * 1024 * 1024,
}
DEFAULT_MAX_BODY_BYTES = 256 * 1024


class BodySizeLimit:
    """Refuse an oversized body before anything materialises it.

    Buffers up to the limit and replays it, rather than letting the request
    through and trying to intercept the response: an ASGI app that has already
    started responding cannot be handed a second response, and the first
    version of this raised inside httpx on any chunked upload it tried to stop.
    """

    def __init__(self, app: object) -> None:
        self.app = app

    @staticmethod
    def _limit_for(path: str) -> int:
        return _STREAM_PATHS.get(path, DEFAULT_MAX_BODY_BYTES)

    @staticmethod
    def _streams(path: str) -> bool:
        return path in _STREAM_PATHS

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        from starlette.responses import JSONResponse

        limit = self._limit_for(scope.get("path", ""))

        declared = None
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > limit:
            await JSONResponse({"detail": "body_too_large"}, status_code=413)(
                scope, receive, send
            )
            return

        if self._streams(scope.get("path", "")):
            # Header-checked above, then handed through untouched. The route
            # owns this body; buffering it here would only add a copy an
            # unauthenticated caller could pay for.
            await self.app(scope, receive, send)
            return

        # Content-Length is a claim, not a measurement, and a chunked request
        # carries none at all. Count what actually arrives.
        chunks: list[bytes] = []
        pending: dict | None = None
        total = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                # A disconnect. Hand it to the app AS a disconnect — replaying
                # it as a complete short body made every hung-up request run to
                # completion, and turned a `ClientDisconnect` into a truncated
                # payload the handler then tried to parse.
                pending = message
                break
            total += len(message.get("body", b""))
            if total > limit:
                await JSONResponse({"detail": "body_too_large"}, status_code=413)(
                    scope, receive, send
                )
                return
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay() -> dict:
            nonlocal replayed
            if pending is not None:
                return pending
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)


app.add_middleware(BodySizeLimit)

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

# Nothing in this application reads a request body larger than a form
# submission, and one route accepts bodies from anonymous callers. There is no
# reverse proxy in front of uvicorn — the Cloudflare tunnel points straight at
# it — and uvicorn imposes no limit of its own, so a 43 MB JSON body was
# accepted, parsed into Python objects and answered 200, retaining ~200 MB for
# one request. A handful of concurrent ones OOMs the single worker and takes
# every tenant's dashboard down with it.
#
# Enforced at the ASGI layer so the body is refused BEFORE pydantic
# materialises it, and enforced on the stream as well as the header because
# Content-Length is a claim, not a measurement.
# The public capture form. Mounted with the webhooks rather than below with the
# dashboard API because it shares their contract, not the dashboard's: no
# session, and the organization resolved inside the handler from something in
# the request. It must never acquire `_auth` — the whole point is that a
# stranger on a landing page can reach it.
app.include_router(public.router, prefix="/api/v1/public", tags=["public"])

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
app.include_router(console.router, prefix="/api/v1/console", tags=["console"], dependencies=_auth)
app.include_router(discovery.router, prefix="/api/v1/discovery", tags=["discovery"], dependencies=_auth)


# These three run IN the web process, which pins the app to a single uvicorn
# worker. Under `--workers N` each one would sweep every organization
# independently: N copies of every nurture SMS and email to the same lead, and N
# concurrent listings syncs. Nothing enforces the constraint at runtime, so it
# is written here, where someone reaching for --workers will be looking.
#
# The org-status cache in tenant_resolver has the same shape — invalidation is
# per process — but its window is 15 seconds and self-healing, which is minor
# next to duplicate outbound messages. Going multi-worker means moving these
# loops behind a leader lock or into their own service first.
_followups_task: asyncio.Task | None = None
_enrichment_task: asyncio.Task | None = None
_delivery_retry_task: asyncio.Task | None = None
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Enrichment worker tick failed: %s", exc)
        finally:
            # In `finally`, so a raising tick does not carry its counts into the
            # next one and report them again.
            totals.clear()


async def _delivery_retry_loop() -> None:
    """Send again the replies whose first attempt did not land.

    Every channel adapter is a single POST. Before this, a Meta 503 or a Twilio
    429 stamped the message FAILED and nothing ever looked at it again — the
    AI's answer to a lead who wrote at midnight was simply gone, with a status
    column as the only trace.
    """
    from app.services.delivery import retry_pending_sends
    from app.services.tenant_context import run_for_every_org

    interval = max(30, settings.DELIVERY_RETRY_INTERVAL_SECONDS)
    totals: dict[str, int] = {}

    async def _retry_one_org(session) -> None:
        one = await retry_pending_sends(session, limit=20)
        for key, value in one.items():
            totals[key] = totals.get(key, 0) + value

    while True:
        try:
            await asyncio.sleep(interval)
            await run_for_every_org(_retry_one_org)
            if totals.get("sent") or totals.get("failed"):
                logger.info(
                    "Delivery retry: %d resent, %d still failing across all orgs",
                    totals.get("sent", 0),
                    totals.get("failed", 0),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Delivery retry tick failed: %s", exc)
        finally:
            totals.clear()


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



async def _schema_is_empty() -> bool:
    """Whether `organizations` does not exist — i.e. migrations have not run.

    The distinction matters because an unreadable org count means two opposite
    things. Before migrations it means the install is new and there is nothing
    to isolate. Afterwards it means the session that is supposed to bypass RLS
    came back empty, which is the failure the checks exist for.
    """
    try:
        from sqlalchemy import text

        from app.db.base import get_bypass_engine

        async with get_bypass_engine().connect() as conn:
            found = (
                await conn.execute(text("SELECT to_regclass('public.organizations')"))
            ).scalar()
        return found is None
    except Exception:  # noqa: BLE001 — cannot prove it is new, so assume it is not
        return False



async def _startup_isolation_state() -> tuple[bool, list[int], bool]:
    """Probe the three facts the startup refusals are made of.

    Returns (row-level security is not being enforced, the organizations that
    can take traffic, whether that list could be read at all). A function
    rather than inline code so the dangerous combinations can be tested without
    booting a container — the version of this that lived inline shipped twice
    with the wrong condition.
    """
    # How many organizations can actually take traffic — the demo org and any
    # suspended tenant do not count, which is why a plain COUNT(*) was the wrong
    # test: every install has the demo org, so it always read as "more than one".
    org_count_known = True
    try:
        from app.services.tenant_resolver import active_orgs, routable_candidates

        real_orgs = routable_candidates(await active_orgs())
    except Exception as exc:  # noqa: BLE001 — handled below, not swallowed
        # Emphatically not `debug`. This probe runs on the bypass session; if
        # that role does not in fact bypass RLS, default-deny returns no rows
        # and an empty list silently disabled BOTH refusals below — a green
        # boot with RLS off and every agency sharing one dataset.
        real_orgs = []
        org_count_known = await _schema_is_empty()
        if org_count_known:
            # A first boot, before `alembic upgrade` has run. `organizations`
            # does not exist yet, so "no agencies" is the truth rather than a
            # symptom. Refusing here would be fatal in a way nothing could
            # recover: migrations run *after* the container starts, so a
            # crash-loop means the migration that creates the RLS role can
            # never run, and the documented install has no way out.
            logger.info("no organizations table yet; first boot before migrations")
        else:
            logger.error("could not count active organizations: %s", exc)

    # Assert the two database roles are what the isolation design assumes. Both
    # failure modes are silent: an app role that bypasses RLS isolates nothing,
    # and a bypass role that does NOT bypass makes every login deny and every
    # worker sweep zero organizations, with nothing in the logs either way.
    rls_is_off = False
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
            message = (
                "🔴 DATABASE_URL_APP connects as a superuser or a BYPASSRLS role. "
                "Row-level security is NOT being enforced and every agency can "
                "read every other agency's data. Point it at a role created with "
                "NOSUPERUSER NOBYPASSRLS."
            )
            # A log line was not enough. `db/base.py` falls back to DATABASE_URL
            # when DATABASE_URL_APP is blank, and that role owns the tables — so
            # one empty environment variable turns every endpoint into a
            # cross-tenant read and write, with this line as the only trace.
            # Refuse to serve more than one agency in that state; a
            # single-customer install has nothing to separate, so it may run.
            rls_is_off = True
            logger.error(message)

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
    return rls_is_off, real_orgs, org_count_known


def _must_refuse_to_serve(
    rls_is_off: bool, real_orgs: list[int], org_count_known: bool
) -> bool:
    """Whether starting up would put agencies inside each other's data.

    A function, not an inline condition, so it can be tested without standing
    up a second database. Two ways to get here: RLS is off and more than one
    agency is active, or RLS is off and we could not find out how many there
    are — which is itself a symptom, since the count is read on the session
    that is supposed to bypass RLS.
    """
    if not rls_is_off:
        return False
    return len(real_orgs) > 1 or not org_count_known


def unguarded_channels(s: Settings) -> dict[str, bool]:
    """Channel → whether an inbound POST would skip signature verification.

    Pulled out of the startup so it can be tested. Inside `_startup` it sits in
    a try/except that logs and continues — correct, because a config check must
    not block a boot, but it also means a mutation of this mapping could not be
    caught from there: the exception path silently produced an empty result.

    `whatsapp` is AND-ed with WHATSAPP_ENABLED because a disabled channel is not
    an injection vector whatever its simulation flag says — the webhook answers
    404 before it reaches verification. Reading the flag alone would crash-loop
    an install that has a legacy whatsapp route and has correctly switched the
    channel off, which is the same mistake as refusing a working one.
    """
    return {
        "sms": s.SMS_SIMULATED,
        "whatsapp": s.WHATSAPP_ENABLED and s.WHATSAPP_SIMULATED,
        "email": s.EMAIL_SIMULATED,
        "voice": s.VOICE_SIMULATED,
    }


async def _whatsapp_credentials_are_routed() -> bool:
    """True if some org supplies its own WhatsApp credentials via channel_routes.

    Without this the guard below reads only the GLOBAL `.env` values and would
    refuse to boot a multi-tenant install that is correctly configured
    per-organization — the shape `channel_routes.credential_ref` exists for.
    Refusing a working configuration is its own outage, so the check has to
    know about the mechanism it is guarding.
    """
    try:
        from sqlalchemy import text as _text

        from app.db.base import get_bypass_session_factory

        async with get_bypass_session_factory()() as session:
            found = await session.execute(
                _text(
                    "SELECT 1 FROM channel_routes "
                    "WHERE channel = 'whatsapp' AND credential_ref IS NOT NULL "
                    "LIMIT 1"
                )
            )
            return found.first() is not None
    except Exception:  # noqa: BLE001
        # No table yet (first boot, before migrations), or the probe failed.
        # Fall back to the strict reading: an install that cannot be shown to
        # have routed credentials is treated as relying on the globals.
        return False


def whatsapp_is_half_configured(s: Settings, *, credentials_are_routed: bool = False) -> str | None:
    """The reason WhatsApp must not start, or None.

    `WHATSAPP_SIMULATED` gates two unrelated things: whether outbound goes to
    Meta, and whether inbound webhooks are HMAC-verified. Turning simulation
    off therefore does not mean "go live" — with an empty app secret it means
    every inbound POST is rejected 403, Meta retries for days and then disables
    the subscription, and the only startup line that mentioned WhatsApp at all
    has just disappeared because simulation is off. The install ends up quieter
    and more broken than before.

    So the half-configured state is refused at boot rather than discovered from
    a customer saying their messages stopped arriving.
    """
    if not s.WHATSAPP_ENABLED or s.WHATSAPP_SIMULATED:
        return None
    if credentials_are_routed:
        # Per-org configuration in `channel_routes`. The globals are allowed to
        # be empty in that shape, and `_validate_refs` covers those rows.
        return None
    missing = [
        name
        for name, value in (
            ("WHATSAPP_APP_SECRET", s.WHATSAPP_APP_SECRET),
            ("WHATSAPP_ACCESS_TOKEN", s.WHATSAPP_ACCESS_TOKEN),
            ("WHATSAPP_PHONE_NUMBER_ID", s.WHATSAPP_PHONE_NUMBER_ID),
        )
        if not (value or "").strip()
    ]
    if not missing:
        return None
    return (
        "WhatsApp is enabled with live sending but " + ", ".join(missing) + " "
        + ("is" if len(missing) == 1 else "are")
        + " empty. Without the app secret every inbound webhook returns 403 "
        "until Meta disables the subscription; without the token and phone "
        "number id nothing can be sent. Set them, or set WHATSAPP_SIMULATED=true, "
        "or set WHATSAPP_ENABLED=false."
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
    from app.models.organization import DEFAULT_ORG_ID

    rls_is_off, real_orgs, org_count_known = await _startup_isolation_state()


    # The public capture form is the one route an anonymous stranger can write
    # through, so whether its strongest defence is on belongs in the startup
    # log next to the rest of the security posture — not left for someone to
    # infer from an empty variable.
    if not (settings.TURNSTILE_SECRET or "").strip():
        logger.warning(
            "⚠️  TURNSTILE_SECRET is empty — POST /api/v1/public/leads accepts "
            "submissions with no captcha. The honeypot, the per-IP limit and "
            "the global ceiling still apply, but a determined script outspends "
            "all three. Set it (and NEXT_PUBLIC_TURNSTILE_SITE_KEY, which must "
            "be baked into the frontend build) before advertising the form."
        )

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
    if settings.AUTH_ENABLED:
        # Checked at boot, not at first login. `_secret()` raises on use and
        # `decode_token` calls it on every request — so a deployment with this
        # unset booted green, kept /api/v1/health green (it needs no tenant),
        # and 500'd every authenticated request. A healthcheck-driven rollout
        # would have reported success while the product was entirely down.
        #
        # The length floor matters as much as the presence: this key alone
        # authenticates the platform-operator claim and the organization claim,
        # so AUTH_SECRET=changeme is a forgeable `su` with nothing underneath.
        if not settings.AUTH_SECRET:
            raise RuntimeError(
                "AUTH_ENABLED is true but AUTH_SECRET is not set. Session tokens "
                "carry the acting organization and the platform-operator claim, "
                "and the key is deliberately no longer derived from "
                "DASHBOARD_PASSWORD. Generate one: openssl rand -hex 32"
            )
        if len(settings.AUTH_SECRET) < 32:
            raise RuntimeError(
                f"AUTH_SECRET is {len(settings.AUTH_SECRET)} characters long. It "
                "is the only thing between a stranger and a forged "
                "platform-operator token; use at least 32. openssl rand -hex 32"
            )

    half_configured = whatsapp_is_half_configured(
        settings,
        credentials_are_routed=(
            await _whatsapp_credentials_are_routed()
            if settings.WHATSAPP_ENABLED and not settings.WHATSAPP_SIMULATED
            else False
        ),
    )
    if half_configured:
        raise RuntimeError(half_configured)

    if _must_refuse_to_serve(rls_is_off, real_orgs, org_count_known):
        # Outside the role check's own try/except on purpose, so the refusal is
        # not swallowed by the handler that logs role-probe failures.
        how_many = (
            f"{len(real_orgs)} agencies are active"
            if org_count_known
            else "the number of active agencies could not be read"
        )
        raise RuntimeError(
            f"Row-level security is not being enforced and {how_many}, so every "
            "agency can read and write the others' data. Point DATABASE_URL_APP "
            "at a NOSUPERUSER NOBYPASSRLS role before serving traffic."
        )

    if not settings.AUTH_ENABLED and (len(real_orgs) > 1 or not org_count_known):
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
        # A simulated channel skips signature verification entirely — that is
        # what makes it usable from curl. With a second agency onboarded and a
        # routed destination, anyone who can reach the port and knows an
        # agency's public phone number can POST an inbound message and have it
        # written into that agency's tenant, driving their AI and creating
        # visits. The flags default to true in docker-compose, so this is not a
        # hypothetical misconfiguration; it is the default one.
        #
        # Only channels that actually have a route matter: an unrouted channel
        # cannot be attributed to an agency at all, so the refusal already
        # covers it.
        try:
            from sqlalchemy import select as _select

            from app.db.base import get_bypass_session_factory
            from app.models.channel_route import ChannelRoute

            simulated = unguarded_channels(settings)
            async with get_bypass_session_factory()() as session:
                routed_channels = {
                    c for (c,) in await session.execute(_select(ChannelRoute.channel))
                }
            unguarded = sorted(
                c for c in routed_channels if simulated.get(c)
            )
        except Exception as exc:  # noqa: BLE001 — a check must not block startup
            logger.debug("simulated channel check skipped: %s", exc)
            unguarded = []

        if unguarded:
            raise RuntimeError(
                f"{', '.join(unguarded)} run in SIMULATED mode, which accepts "
                f"unsigned inbound messages, while {len(real_orgs)} agencies "
                "have routed destinations. Anyone who knows an agency's number "
                "could write leads and book visits inside their tenant. Set "
                f"{', '.join(c.upper() + '_SIMULATED' for c in unguarded)}=false "
                "and configure the provider secrets."
            )

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

    if settings.WHATSAPP_ENABLED and settings.is_production and settings.WHATSAPP_SIMULATED:
        # Only when the channel is actually in use. This warning used to fire on
        # every restart of every install, including the ones that will never
        # send a WhatsApp message, and a warning that is always there and never
        # actionable is a warning the operator learns to scroll past.
        logger.warning(
            "⚠️  WHATSAPP_SIMULATED=true AND APP_ENV=production — outbound WhatsApp "
            "will only be LOGGED, not sent to Meta."
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

    if settings.DELIVERY_RETRY_ENABLED:
        global _delivery_retry_task
        _delivery_retry_task = asyncio.create_task(_delivery_retry_loop())
        logger.info(
            "Delivery retry worker started (every %ds)",
            settings.DELIVERY_RETRY_INTERVAL_SECONDS,
        )

    if settings.LISTINGS_SYNC_ENABLED:
        global _listings_sync_task
        _listings_sync_task = asyncio.create_task(_listings_sync_loop())
        logger.info(
            "Listings sync worker started (every %ds)", settings.LISTINGS_SYNC_INTERVAL_SECONDS
        )


@app.on_event("shutdown")
async def _shutdown() -> None:
    for task in (_followups_task, _enrichment_task, _delivery_retry_task, _listings_sync_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@app.get("/")
async def root() -> dict[str, str]:
    """Tiny root endpoint so a healthcheck against / never returns 404."""
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}

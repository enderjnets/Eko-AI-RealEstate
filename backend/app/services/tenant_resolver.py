"""Decide which organization a request acts for, before it touches the database.

Three kinds of request reach this app and only one of them carries a session:

- **Authenticated** — the org comes from the signed token, and the org must
  still exist and not be suspended.
- **Inbound webhooks** (SMS, email, WhatsApp, voice) — no session at all. The
  org has to come from the destination the message arrived at: the Twilio
  number, the mailbox. That mapping does not exist yet, so this **refuses** to
  route them once a second real tenant is onboarded rather than guessing.
- **Everything else** (login, health, static) — no org, and none is needed.
  Under default-deny RLS that means zero rows, which is the correct answer for
  a request that has not proven who it is.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from app.models.organization import DEFAULT_ORG_ID, DEMO_ORG_ID

logger = logging.getLogger(__name__)

# Unauthenticated paths that legitimately write: the inbound channels.
WEBHOOK_PREFIX = "/api/v1/webhooks"

# Operator routes. They act across tenants by design, so they never resolve to
# one — and they must stay reachable when the deployment is in a state the rest
# of the app refuses to serve, since they are what fixes it.
PLATFORM_PREFIX = "/api/v1/platform"

# Paths that must answer without touching the database. `/health` exists to be
# reachable during an outage — routing it through the org-status lookup made it
# hang exactly when a monitor needs a straight answer.
NO_TENANT_PREFIXES = ("/api/v1/health", "/docs", "/redoc", "/openapi.json")


def needs_tenant(path: str) -> bool:
    return not path.startswith(NO_TENANT_PREFIXES)

# Orgs change rarely and this is consulted on every request, so the set of
# routable orgs is cached briefly. Short enough that suspending a tenant takes
# effect in seconds, long enough to keep the hot path off the database.
_CACHE_TTL_SECONDS = 15.0
_cache: tuple[float, dict[int, str]] | None = None

# Bumped by every invalidation. A read that starts before an invalidation and
# finishes after it must not install its now-stale snapshot: the read-through is
# a check-then-act across an await, so without this an in-flight `active_orgs()`
# could undo `reset_cache()` and keep a just-created tenant invisible — or a
# just-suspended one live — for a further 15 seconds. The dangerous half is
# creation: while the second agency is missing from the cache, the fallback in
# `webhook_org_or_refuse` sees a single candidate and files their unrouted
# inbound message into the first agency. That write is permanent; the cache
# expiring does not undo it.
_cache_generation = 0


class TenantUnresolvable(Exception):
    """This request cannot be attributed to an organization, so it is refused.

    Refusing is the recoverable outcome. The alternative — picking an
    organization anyway — writes one agency's data into another's tenant, and
    nobody notices until the wrong client reads it.
    """


class WebhookOrgUnresolved(TenantUnresolvable):
    """An inbound message arrived and we cannot tell which agency it is for."""


class SingleTenantModeViolated(TenantUnresolvable):
    """Auth is off — which pins every request to one org — but several exist."""


async def active_orgs() -> dict[int, str]:
    """`{org_id: status}` for every organization, briefly cached."""
    global _cache
    now = time.monotonic()
    cached = _cache
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.organization import Organization

    generation = _cache_generation
    async with get_bypass_session_factory()() as db:
        rows = (await db.execute(select(Organization.id, Organization.status))).all()
    result = {row[0]: row[1] for row in rows}
    if generation == _cache_generation:
        # Stamped now, not before the query: the round-trip is not cache age.
        _cache = (time.monotonic(), result)
    # The snapshot is still returned either way. It was accurate when the query
    # ran; anything that changed afterwards is a genuine race, not staleness.
    return result


def reset_cache() -> None:
    """Drop the cached org list. Called after creating or suspending a tenant."""
    global _cache, _cache_generation
    _cache = None
    _cache_generation += 1


async def resolve_org_for_request(path: str, token: str | None) -> int | None:
    """The organization this request acts for, or None for 'no org'.

    Raises WebhookOrgUnresolved when an inbound message cannot be attributed —
    failing the delivery is recoverable (providers retry, and the operator sees
    the error), whereas filing another agency's lead into the wrong tenant is a
    cross-tenant write that nobody notices until a client reads it.
    """
    from app.config import get_settings
    from app.services.auth import token_org_id

    if path.startswith(WEBHOOK_PREFIX):
        # Inbound messages are attributed by DESTINATION, which lives in the
        # request body — and this layer cannot read it. So it returns no org and
        # the handler decides, via webhook_org_or_refuse, before any write.
        #
        # This used to call a path-only resolver that raised as soon as a second
        # organization existed. That ran BEFORE the handler, so with auth on and
        # two tenants every webhook 503'd no matter how well channel_routes was
        # configured — the routing feature was unreachable in exactly the
        # configuration it was built for. Under default-deny RLS, returning None
        # here is safe: a handler that forgot to bind an org writes nothing.
        return None

    if token:
        org_id = token_org_id(token)
        if org_id is not None:
            return org_id

    if not get_settings().AUTH_ENABLED:
        # With auth off `require_auth` is already a no-op, so there is no token
        # to carry an org and exactly one tenant is expected. Guarded on the flag
        # rather than on "no token": in a real deployment an unauthenticated
        # request must resolve to no org at all, never to somebody's data.
        #
        # "Exactly one tenant is expected" was only ever a comment. Nothing
        # enforced it, and AUTH_ENABLED=false is the compose default — so
        # seeding a second agency made every dashboard request resolve to the
        # first one regardless of who was calling: agency B unreachable, and
        # every write landing in agency A. Startup refuses this combination
        # outright; this covers the org created while the process is running.
        if len(routable_candidates(await active_orgs())) > 1 and not path.startswith(
            PLATFORM_PREFIX
        ):
            # Platform paths are exempt so the state is recoverable. Refusing
            # them too meant the only route that could suspend or delete the
            # extra organization was itself refused, and the whole install
            # answered 503 until someone edited Postgres by hand.
            raise SingleTenantModeViolated(
                "AUTH_ENABLED is off, which pins every request to organization "
                f"{DEFAULT_ORG_ID}, but more than one active organization "
                "exists. Turn authentication on before onboarding a second "
                "agency."
            )
        return DEFAULT_ORG_ID

    return None


def routable_candidates(orgs: dict[int, str]) -> list[int]:
    """Organizations that may receive an inbound message that carries no route.

    The demo org is excluded deliberately, and so is any suspended one. Shared
    by the fallback below and by the startup check that refuses to run
    single-tenant mode against a database that has grown a second tenant.
    """
    return [
        org_id
        for org_id, status in orgs.items()
        if org_id != DEMO_ORG_ID and status != "suspended"
    ]


Destination = str | Sequence[str] | None


async def resolve_org_by_destination(
    channel: str, destination: Destination
) -> int | None:
    """The organization that owns an inbound destination, or None if unmapped.

    Takes several candidates because one message can carry more than one, in
    two different ways. An email names every recipient, and a lead who writes to
    agency B while CC'ing agency A produces both. A VAPI payload carries either
    the E.164 number or the opaque phone-number id depending on the message
    type, so the same call routes by two different keys.

    Matching all of them at once handles both: exactly one agency addressed is
    the answer, none falls through to the single-tenant fallback, and two is an
    ambiguity that has to be refused rather than settled by ordering — which is
    what the old "first entry of `to`" rule did, filing B's thread under A.

    Read on the bypass session by necessity: this runs *before* any org is
    bound, which is the whole problem it exists to solve.
    """
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute, normalize_destination

    candidates = [destination] if isinstance(destination, str) else list(destination or [])
    keys = {normalize_destination(c) for c in candidates}
    keys.discard("")
    if not keys:
        return None

    async with get_bypass_session_factory()() as db:
        owners = set(
            (
                await db.execute(
                    select(ChannelRoute.org_id).where(
                        ChannelRoute.channel == channel,
                        ChannelRoute.destination.in_(keys),
                    )
                )
            ).scalars()
        )
    if not owners:
        return None
    if len(owners) > 1:
        raise WebhookOrgUnresolved(
            f"inbound {channel} names destinations belonging to {len(owners)} "
            f"different agencies {sorted(owners)}. Refusing rather than picking "
            "one — a lead who writes to one agency and copies another must not "
            "silently become the second one's lead."
        )
    return owners.pop()


async def _owns_its_own_account(channel: str, org_id: int) -> bool:
    """Whether this organization has its own provider credentials on `channel`.

    Read on the bypass session: `channel_routes` is invisible to the app role,
    and this runs before any org is bound.
    """
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute

    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                select(ChannelRoute.id)
                .where(
                    ChannelRoute.channel == channel,
                    ChannelRoute.org_id == org_id,
                    ChannelRoute.credential_ref.is_not(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None


async def webhook_org_or_refuse(channel: str, destination: Destination) -> int:
    """The agency an inbound message belongs to, or raise.

    The single decision point for every channel, deliberately independent of
    AUTH_ENABLED. Routing it through `resolve_org_for_request` meant that with
    auth off — the dev and single-customer default — an unmapped destination
    silently resolved to the first organization, which is the misfiling this
    whole mechanism exists to stop. The destination is authoritative; the
    single-tenant fallback applies only when there is genuinely nothing to
    confuse it with.
    """
    orgs = await active_orgs()

    routed = await resolve_org_by_destination(channel, destination)
    if routed is not None:
        if routed == DEMO_ORG_ID:
            # Mapping a live destination at the demo org is always a mistake,
            # and an expensive one: `POST /auth/register` drops any anonymous
            # visitor into that org as a viewer, so the lead's phone number and
            # their whole transcript become public. `create_route` refuses this
            # too — this is the guard for rows that predate it or arrive by SQL.
            raise WebhookOrgUnresolved(
                f"{channel} destination {destination!r} is mapped to the demo "
                "organization, which anonymous sign-ups can read. Re-point the "
                "route at a real agency."
            )
        # Status is checked on the ROUTED branch too. It used to be checked only
        # on the fallback below, so a suspended agency kept receiving inbound
        # messages and getting rows written into it — suspension has to stop the
        # product working for them, not just stop their background sweeps.
        status = orgs.get(routed)
        if status is None or status == "suspended":
            raise WebhookOrgUnresolved(
                f"{channel} destination {destination!r} belongs to organization "
                f"{routed}, which is {status or 'no longer present'}"
            )
        return routed

    candidates = routable_candidates(orgs)
    if len(candidates) == 1:
        # The single-tenant fallback, but only for an agency that has not been
        # given its own provider account. If it has, an unmapped destination
        # means the message was verified against the *operator's* shared secret
        # while about to be filed under an agency that does not use it — so the
        # principal that proved authenticity is not the tenant receiving the
        # write. Anyone holding the shared credential could post a signed
        # message with an unmapped `To` and have a lead, a transcript and an
        # AI reply appear inside that agency.
        if await _owns_its_own_account(channel, candidates[0]):
            raise WebhookOrgUnresolved(
                f"inbound {channel} to {destination!r} matches no channel_route, "
                f"and organization {candidates[0]} uses its own provider "
                "credentials — so this message was not authenticated by them. "
                "Map the destination in channel_routes."
            )
        return candidates[0]
    if not candidates:
        raise WebhookOrgUnresolved("no active organization can receive inbound messages")
    raise WebhookOrgUnresolved(
        f"inbound {channel} to {destination!r} matches no channel_route and "
        f"{len(candidates)} active organizations exist, so it cannot be "
        "attributed to one. Map the destination in channel_routes."
    )

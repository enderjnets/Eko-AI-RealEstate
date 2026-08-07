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

from app.models.organization import DEFAULT_ORG_ID, DEMO_ORG_ID

logger = logging.getLogger(__name__)

# Unauthenticated paths that legitimately write: the inbound channels.
WEBHOOK_PREFIX = "/api/v1/webhooks"

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


class WebhookOrgUnresolved(Exception):
    """An inbound message arrived and we cannot tell which agency it is for."""


async def active_orgs() -> dict[int, str]:
    """`{org_id: status}` for every organization, briefly cached."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]

    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.organization import Organization

    async with get_bypass_session_factory()() as db:
        rows = (await db.execute(select(Organization.id, Organization.status))).all()
    result = {row[0]: row[1] for row in rows}
    _cache = (now, result)
    return result


def reset_cache() -> None:
    """Drop the cached org list. Called after creating or suspending a tenant."""
    global _cache
    _cache = None


async def resolve_org_for_request(path: str, token: str | None) -> int | None:
    """The organization this request acts for, or None for 'no org'.

    Raises WebhookOrgUnresolved when an inbound message cannot be attributed —
    failing the delivery is recoverable (providers retry, and the operator sees
    the error), whereas filing another agency's lead into the wrong tenant is a
    cross-tenant write that nobody notices until a client reads it.
    """
    from app.config import get_settings
    from app.services.auth import token_org_id

    if token:
        org_id = token_org_id(token)
        if org_id is not None:
            return org_id

    if not get_settings().AUTH_ENABLED:
        # With auth off `require_auth` is already a no-op, so there is no token
        # to carry an org and exactly one tenant is expected. Guarded on the flag
        # rather than on "no token": in a real deployment an unauthenticated
        # request must resolve to no org at all, never to somebody's data.
        return DEFAULT_ORG_ID

    if path.startswith(WEBHOOK_PREFIX):
        return await _resolve_webhook_org(path)

    return None


async def resolve_org_by_destination(channel: str, destination: str | None) -> int | None:
    """The organization that owns an inbound destination, or None if unmapped.

    Read on the bypass session by necessity: this runs *before* any org is
    bound, which is the whole problem it exists to solve.
    """
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute, normalize_destination

    key = normalize_destination(destination)
    if not key:
        return None
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                select(ChannelRoute.org_id).where(
                    ChannelRoute.channel == channel,
                    ChannelRoute.destination == key,
                )
            )
        ).scalar_one_or_none()


async def webhook_org_or_refuse(channel: str, destination: str | None) -> int:
    """The agency an inbound message belongs to, or raise.

    The single decision point for every channel, deliberately independent of
    AUTH_ENABLED. Routing it through `resolve_org_for_request` meant that with
    auth off — the dev and single-customer default — an unmapped destination
    silently resolved to the first organization, which is the misfiling this
    whole mechanism exists to stop. The destination is authoritative; the
    single-tenant fallback applies only when there is genuinely nothing to
    confuse it with.
    """
    routed = await resolve_org_by_destination(channel, destination)
    if routed is not None:
        return routed

    orgs = await active_orgs()
    candidates = [
        org_id
        for org_id, status in orgs.items()
        if org_id != DEMO_ORG_ID and status != "suspended"
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise WebhookOrgUnresolved("no active organization can receive inbound messages")
    raise WebhookOrgUnresolved(
        f"inbound {channel} to {destination!r} matches no channel_route and "
        f"{len(candidates)} active organizations exist, so it cannot be "
        "attributed to one. Map the destination in channel_routes."
    )


async def _resolve_webhook_org(path: str) -> int:
    """Attribute an inbound message when the destination is not yet known.

    The middleware cannot read the request body, so a webhook that carries its
    destination inside the payload is resolved by the handler via
    `resolve_org_by_destination`. This is the fallback for the case the handler
    cannot cover: with exactly one real tenant there is no ambiguity, and with
    more there is nothing to guess from — and guessing wrote agency B's leads
    and their whole conversation transcript into agency A's dashboard.
    """
    orgs = await active_orgs()
    candidates = [
        org_id
        for org_id, status in orgs.items()
        if org_id != DEMO_ORG_ID and status != "suspended"
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise WebhookOrgUnresolved("no active organization can receive inbound messages")
    raise WebhookOrgUnresolved(
        f"{len(candidates)} active organizations exist and {path} carries no "
        "destination this layer can read. Refusing rather than filing it under "
        "the wrong agency — map the destination in channel_routes."
    )

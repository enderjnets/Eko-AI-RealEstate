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


async def _resolve_webhook_org(path: str) -> int:
    """Attribute an inbound message to a tenant, or refuse.

    Routing by destination (which Twilio number, which mailbox) is Fase 3. Until
    it exists there is exactly one real tenant, so a single candidate is
    unambiguous. A second one makes every inbound message ambiguous, and the
    old behaviour — default to org 1 — wrote agency B's leads and their whole
    conversation transcript into agency A's dashboard while agency B saw
    nothing and their follow-ups never fired.
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
        f"{len(candidates)} active organizations exist and inbound routing by "
        f"destination is not built yet, so {path} cannot be attributed to one. "
        "Refusing rather than filing it under the wrong agency."
    )

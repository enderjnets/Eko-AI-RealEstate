"""Decide which organization a request acts for, before it touches the database.

Three kinds of request reach this app and only one of them carries a session:

- **Authenticated** — the org comes from the signed token.
- **Inbound webhooks** (SMS, email, WhatsApp, voice) — no session at all. The
  org has to be derived from the destination the message arrived at: the Twilio
  number, the mailbox. Until per-org channel settings exist (Fase 3) there is
  exactly one real tenant, so they resolve to DEFAULT_ORG_ID and log it. The
  warning is the point: when a second tenant is onboarded and this still
  hardcodes org 1, the logs say so instead of silently filing another agency's
  leads under client zero.
- **Everything else** (login, health, static) — no org, and none is needed.
  Under default-deny RLS that means zero rows, which is the correct answer for
  a request that has not proven who it is.
"""
from __future__ import annotations

import logging

from app.models.organization import DEFAULT_ORG_ID

logger = logging.getLogger(__name__)

# Unauthenticated paths that legitimately write: the inbound channels.
WEBHOOK_PREFIX = "/api/v1/webhooks"


def resolve_org_for_path(path: str, token: str | None) -> int | None:
    from app.config import get_settings
    from app.services.auth import token_org_id

    if token:
        org_id = token_org_id(token)
        if org_id is not None:
            return org_id

    # With auth off (dev, demo, the single-customer installer) `require_auth` is
    # already a no-op, so there is no token to carry an org and exactly one
    # tenant exists. Guarded on the flag rather than on "no token": in a real
    # deployment an unauthenticated request must resolve to no org at all, never
    # to somebody's data.
    if not get_settings().AUTH_ENABLED:
        return DEFAULT_ORG_ID

    if path.startswith(WEBHOOK_PREFIX):
        # TODO(Fase 3): map the destination (Twilio number / mailbox) to an org.
        logger.info(
            "webhook %s routed to the default org — per-org channel routing is not built yet",
            path,
        )
        return DEFAULT_ORG_ID

    return None

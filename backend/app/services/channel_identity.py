"""Which credentials and which sending address this organization uses.

Inbound has been attributed by destination since `channel_routes` existed, but
outbound kept a single global identity per channel — one Twilio number, one
WhatsApp phone-number id, one Resend from-address. The consequence needed no
adversary: agency B's lead was answered from agency A's number, replied to A's
number, and the rest of their conversation was written into A's tenant. That
made onboarding a second agency unsafe regardless of how well isolation worked
everywhere else.

Two things are deliberate here.

**Secrets are referenced, not stored.** A route row names an environment
variable — `credential_ref = "TWILIO_AUTH_TOKEN_ACME"` — and this module reads
it. Keys stay in `.env`, per the repo's standing rule, and the database holds
only the mapping. It costs a restart to onboard an agency, which is the right
trade while agencies are onboarded by hand; encrypting secrets at rest is what
self-service would need, and this shape does not block it.

**Absent means global.** A row with no refs, or no row at all, yields exactly
the settings a single-customer install already runs on. Nothing changes for the
existing deployment until someone deliberately gives an agency its own account.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.config import get_settings
from app.models.channel_route import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_VOICE,
    CHANNEL_WHATSAPP,
)
from app.services.tenant_context import get_org_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelIdentity:
    """Everything a channel needs to speak as one particular agency."""

    org_id: int | None
    channel: str
    # The address/number/id this agency sends from, when the route names one.
    destination: str | None = None
    # Twilio account SID, WhatsApp phone-number id, Resend domain.
    provider_account: str | None = None
    # The sending credential: Twilio auth token, WhatsApp access token, API key.
    credential: str | None = None
    # The secret this agency's *inbound* payloads are signed with.
    inbound_secret: str | None = None
    verify_token: str | None = None
    sender_override: str | None = None
    webhook_url: str | None = None

    @property
    def is_own_account(self) -> bool:
        """Whether this agency brings its own provider account."""
        return self.credential is not None


def _env(ref: str | None) -> str | None:
    """The value of the environment variable a route row names.

    A ref pointing at a variable that is not set is a configuration mistake with
    a silent failure mode — the send would quietly fall back to the operator's
    own account and reply to the agency's lead from the wrong number, which is
    the exact bug this module exists to end. So it is loud.
    """
    if not ref:
        return None
    value = os.environ.get(ref)
    if value:
        return value
    logger.error(
        "channel route names %s but that environment variable is empty; "
        "refusing to fall back to the shared account",
        ref,
    )
    raise MissingChannelCredential(ref)


class MissingChannelCredential(RuntimeError):
    """A route names an environment variable that is not set."""


async def resolve_outbound_identity(channel: str) -> ChannelIdentity:
    """The identity the acting organization sends on `channel` with.

    Read on the bypass session: `channel_routes` is not visible to the app role
    (migration 021 revoked it, and the rows now name credentials), and this is
    called from inside a request that is already bound to an organization.
    """
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute

    org_id = get_org_id()
    if org_id is None:
        return _global_identity(channel, org_id=None)

    async with get_bypass_session_factory()() as db:
        rows = (
            await db.execute(
                select(ChannelRoute)
                .where(ChannelRoute.channel == channel, ChannelRoute.org_id == org_id)
                .order_by(ChannelRoute.id)
            )
        ).scalars().all()

    routed = next((r for r in rows if r.credential_ref), None)
    if routed is None:
        # The agency may still own a destination without owning an account — an
        # extra number on the operator's Twilio, say. Take its identity and the
        # global credentials.
        plain = rows[0] if rows else None
        base = _global_identity(channel, org_id=org_id)
        if plain is None:
            return base
        return ChannelIdentity(
            org_id=org_id,
            channel=channel,
            destination=plain.destination,
            provider_account=base.provider_account,
            credential=base.credential,
            inbound_secret=base.inbound_secret,
            verify_token=base.verify_token,
            sender_override=plain.sender_override or base.sender_override,
            webhook_url=plain.webhook_url or base.webhook_url,
        )

    if len([r for r in rows if r.credential_ref]) > 1:
        # Several numbers on one agency's own account is legitimate, but nothing
        # records which one a conversation arrived at, so a follow-up sent a day
        # later cannot know which to reply from. Say so instead of picking one
        # in silence.
        logger.warning(
            "organization %s has %d %s routes with their own credentials; "
            "replying from the first (%s). Outbound cannot yet distinguish them.",
            org_id, len([r for r in rows if r.credential_ref]), channel,
            routed.destination,
        )

    return ChannelIdentity(
        org_id=org_id,
        channel=channel,
        destination=routed.destination,
        provider_account=_env(routed.provider_account_ref),
        credential=_env(routed.credential_ref),
        inbound_secret=_env(routed.inbound_secret_ref),
        verify_token=_env(routed.verify_token_ref),
        sender_override=routed.sender_override,
        webhook_url=routed.webhook_url,
    )


def _global_identity(channel: str, *, org_id: int | None) -> ChannelIdentity:
    """The single-customer configuration, straight out of `.env`."""
    s = get_settings()
    if channel == CHANNEL_SMS:
        return ChannelIdentity(
            org_id=org_id,
            channel=channel,
            destination=s.TWILIO_PHONE_NUMBER or None,
            provider_account=s.TWILIO_ACCOUNT_SID or None,
            credential=s.TWILIO_AUTH_TOKEN or None,
            inbound_secret=s.TWILIO_AUTH_TOKEN or None,
            sender_override=s.TWILIO_MESSAGING_SERVICE_SID or None,
            webhook_url=s.TWILIO_WEBHOOK_URL or None,
        )
    if channel == CHANNEL_WHATSAPP:
        return ChannelIdentity(
            org_id=org_id,
            channel=channel,
            destination=s.WHATSAPP_PHONE_NUMBER_ID or None,
            credential=s.WHATSAPP_ACCESS_TOKEN or None,
            inbound_secret=s.WHATSAPP_APP_SECRET or None,
            verify_token=s.WHATSAPP_VERIFY_TOKEN or None,
        )
    if channel == CHANNEL_EMAIL:
        return ChannelIdentity(
            org_id=org_id,
            channel=channel,
            destination=s.RESEND_FROM or None,
            credential=s.RESEND_API_KEY or None,
            inbound_secret=s.RESEND_WEBHOOK_SECRET or None,
        )
    if channel == CHANNEL_VOICE:
        return ChannelIdentity(
            org_id=org_id,
            channel=channel,
            destination=s.VAPI_PHONE_NUMBER_ID or None,
            credential=s.VAPI_API_KEY or None,
            inbound_secret=s.VAPI_WEBHOOK_SECRET or None,
            sender_override=s.VAPI_ASSISTANT_ID or None,
        )
    return ChannelIdentity(org_id=org_id, channel=channel)


async def known_verify_tokens(channel: str) -> list[str]:
    """Every handshake token configured for this channel, operator's included.

    Only the WhatsApp setup handshake needs this: it is the one inbound message
    with no destination in it at all, so the token cannot be narrowed to an
    organization first.
    """
    from sqlalchemy import select

    from app.db.base import get_bypass_session_factory
    from app.models.channel_route import ChannelRoute

    tokens: list[str] = []
    global_token = _global_identity(channel, org_id=None).verify_token
    if global_token:
        tokens.append(global_token)

    async with get_bypass_session_factory()() as db:
        refs = (
            await db.execute(
                select(ChannelRoute.verify_token_ref).where(
                    ChannelRoute.channel == channel,
                    ChannelRoute.verify_token_ref.is_not(None),
                )
            )
        ).scalars().all()
    for ref in refs:
        try:
            value = _env(ref)
        except MissingChannelCredential:
            # One agency's misconfiguration must not block the others' setup.
            continue
        if value:
            tokens.append(value)
    return tokens


async def resolve_inbound_secret(channel: str, destination: object) -> ChannelIdentity:
    """The identity that owns an inbound destination, for signature checking.

    Chicken and egg: the secret depends on which agency was written to, and the
    destination is inside the payload the secret is supposed to authenticate.
    The way out is that the destination is only used to *look up* a key — a
    forged one either names no route, and the global secret applies, or names
    another agency's, whose signature the forger cannot produce.
    """
    from app.services.tenant_resolver import resolve_org_by_destination

    try:
        org_id = await resolve_org_by_destination(channel, destination)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — an ambiguous destination is not our call
        org_id = None
    if org_id is None:
        return _global_identity(channel, org_id=None)

    from app.services.tenant_context import org_scope

    with org_scope(org_id):
        return await resolve_outbound_identity(channel)

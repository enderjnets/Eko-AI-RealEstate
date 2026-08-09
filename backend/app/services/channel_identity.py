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
from collections.abc import Sequence
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


Destination = str | Sequence[str] | None


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



def _env_or_none(ref: str | None) -> str | None:
    """`_env`, but a missing variable is None instead of an exception.

    For refs that are not the one being used right now. Raising would let a
    stale inbound reference break an unrelated outbound send; the error is
    already logged, and a None secret fails closed at verification time.
    """
    try:
        return _env(ref)
    except MissingChannelCredential:
        return None



def _resolve(ref: str | None, fallback: str | None) -> str | None:
    """The value behind a route's reference, or the global one — never both.

    The distinction that matters: **no ref** means "this agency uses the shared
    configuration", so the fallback applies. A ref that is *named* but whose
    variable is missing means the agency has its own credential and we cannot
    read it — and quietly substituting the operator's would accept, as that
    agency, anything signed with the secret the operator shares. The previous
    shape was `_env_or_none(ref) or base`, whose comment claimed to fail closed
    while the `or` on the same line did the opposite.

    A named-but-unresolvable ref therefore yields None, and every consumer
    treats None as a refusal: the four signature verifiers reject an empty
    secret, and each `send_*` refuses to dispatch without its credential.
    """
    if not ref:
        return fallback
    return _env_or_none(ref)


async def resolve_outbound_identity(
    channel: str, *, destination: Destination = None
) -> ChannelIdentity:
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

    # When the caller knows which destination the message arrived at, that row
    # is the answer. Picking `rows[0]` instead meant an agency with two numbers
    # on one channel had inbound to the second verified against the FIRST one's
    # secret — the HMAC fails and real leads are dropped with a 403. Nothing
    # forbids two destinations per agency per channel; only `(channel,
    # destination)` is unique.
    if destination is not None:
        from app.models.channel_route import normalize_destination

        candidates = (
            [destination] if isinstance(destination, str) else list(destination)
        )
        keys = {normalize_destination(d) for d in candidates if isinstance(d, str)}
        keys.discard("")
        matched = [r for r in rows if r.destination in keys]
        if not matched:
            # A destination this organization does not own. Falling back to the
            # whole row set would re-pick some other route's secret, which is
            # the round-12 defect one caller away. Unreachable today — the org
            # is resolved *from* a matching route — but the safe answer to "not
            # yours" is the global configuration, never a sibling's.
            return _global_identity(channel, org_id=org_id)
        rows = matched

    routed = next((r for r in rows if r.credential_ref), None)
    if routed is None:
        # The agency may own a destination without owning a sending account —
        # an extra number on the operator's Twilio, say — and it may equally own
        # its *inbound* secret without owning the outbound credential: its own
        # Meta app while replies still go out through the shared WABA. Each ref
        # is taken on its own merits.
        #
        # Reading only `credential_ref` here discarded a per-agency
        # `inbound_secret_ref` entirely, so their genuine traffic failed
        # verification against the operator's secret while a message signed with
        # that shared secret sailed in. Every field falls back independently.
        plain = rows[0] if rows else None
        base = _global_identity(channel, org_id=org_id)
        if plain is None:
            return base
        return ChannelIdentity(
            org_id=org_id,
            channel=channel,
            destination=plain.destination,
            provider_account=_resolve(
                plain.provider_account_ref, base.provider_account
            ),
            credential=_resolve(plain.credential_ref, base.credential),
            inbound_secret=_resolve(plain.inbound_secret_ref, base.inbound_secret),
            verify_token=_resolve(plain.verify_token_ref, base.verify_token),
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

    credential = _resolve(routed.credential_ref, None)
    return ChannelIdentity(
        org_id=org_id,
        channel=channel,
        destination=routed.destination,
        # `_resolve` per field, not `_env` per field. `_env` raises, and raising
        # while picking an *inbound* secret because an unrelated *outbound*
        # variable is unset 503'd every message to that number. Each field is
        # needed by a different caller, so each fails on its own: a missing
        # secret becomes None and the verifier rejects; a missing credential
        # becomes None and the send guard refuses. Neither borrows the
        # operator's.
        provider_account=_resolve(routed.provider_account_ref, None),
        credential=credential,
        # Twilio signs inbound with the same auth token used to send, so a route
        # that names `credential_ref` and leaves `inbound_secret_ref` NULL is the
        # natural onboarding shape — and it silently 403'd every inbound message
        # for that agency as error 11200, which `_validate_refs` cannot detect.
        # Their own token, never the operator's: this only reuses what the same
        # row already named.
        inbound_secret=(
            _resolve(routed.inbound_secret_ref, None)
            or (credential if channel == CHANNEL_SMS else None)
        ),
        verify_token=_resolve(routed.verify_token_ref, None),
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


async def inbound_secret_or_503(channel: str, destination: object) -> ChannelIdentity:
    """`resolve_inbound_secret`, with a missing credential turned into a 503.

    Only that one. It is a configuration error — a route names an environment
    variable nobody set — and it is deterministic: without this, every inbound
    message to that number 500s before the signature is even checked, until
    someone redeploys, with one log line as the only clue. 503 is honest: the
    provider retries and the fix makes those retries succeed.

    An *ambiguous* destination is not turned into anything. It used to raise
    503 here, which had two consequences. The handler's own refusal — the one
    that answers 200 precisely so a provider does not disable the endpoint —
    became unreachable for that case, so the flagship behaviour was inert
    wherever it mattered. And the 503 arrived before any signature check, so an
    unauthenticated caller could tell 503 from 403 and enumerate which numbers
    belong to which agency. Falling through to the global secret means the
    signature fails closed with a plain 403, and a genuinely signed message
    reaches the handler's 200 refusal.
    """
    from fastapi import HTTPException

    from app.services.tenant_resolver import WebhookOrgUnresolved

    try:
        return await resolve_inbound_secret(channel, destination)
    except WebhookOrgUnresolved:
        return _global_identity(channel, org_id=None)
    except MissingChannelCredential as exc:
        logger.error("cannot verify inbound %s — %s", channel, exc)
        raise HTTPException(
            status_code=503, detail="inbound verification unavailable"
        ) from exc


async def resolve_inbound_secret(channel: str, destination: object) -> ChannelIdentity:
    """The identity that owns an inbound destination, for signature checking.

    Chicken and egg: the secret depends on which agency was written to, and the
    destination is inside the payload the secret is supposed to authenticate.
    The way out is that the destination is only used to *look up* a key — a
    forged one either names no route, and the global secret applies, or names
    another agency's, whose signature the forger cannot produce.

    A destination naming two agencies raises `WebhookOrgUnresolved`, which
    `inbound_secret_or_503` turns into the global identity rather than a 503:
    the signature then fails closed with a plain 403, and the handler's own
    refusal — which answers 200 so the provider does not disable the endpoint —
    stays reachable.
    """
    from app.services.tenant_resolver import (
        resolve_org_by_destination,
    )

    # `WebhookOrgUnresolved` propagates on purpose. It means the payload names
    # two agencies at once, and the handler turns that into a 503. Swallowing it
    # here — as a bare `except` did — quietly picked the operator's secret
    # instead, so a message legitimately signed with an agency's own key failed
    # verification and the log blamed the signature. The same `except` also
    # turned pool timeouts and database errors into a silent global fallback.
    org_id = await resolve_org_by_destination(channel, destination)  # type: ignore[arg-type]
    if org_id is None:
        return _global_identity(channel, org_id=None)

    from app.services.tenant_context import org_scope

    with org_scope(org_id):
        # The destination is passed on so the agency's *matching* route is used.
        # Without it the lowest-id route answered for all of them, and an agency
        # with two numbers had the second one's inbound verified against the
        # first one's secret.
        # The whole candidate set, not the first entry: an email names every
        # recipient and only one of them is the agency's own address.
        return await resolve_outbound_identity(channel, destination=destination)

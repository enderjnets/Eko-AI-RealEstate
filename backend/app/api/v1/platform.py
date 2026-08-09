"""Platform operator routes — creating, suspending and entering client agencies.

These are the only endpoints that legitimately act across tenants, so they run
on the bypass session and are gated by `require_platform_admin` rather than
`require_admin`: the latter authorises the admin of *some* organization, and
every client agency has one.

Impersonation is deliberately explicit and recorded. The alternative — letting
the operator read every tenant ambiently — means one compromised account exposes
every client at once, and leaves no answer to "who looked at our data?".
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import (
    _set_session_cookie,
    _token_from_request,
    require_platform_admin,
)
from app.config import get_settings
from app.db.base import get_bypass_db
from app.models.channel_route import (
    CHANNEL_CALENDAR,
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_VOICE,
    CHANNEL_WHATSAPP,
)
from app.models.organization import (
    DEMO_ORG_ID,
    PLAN_PILOT,
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
    Organization,
)
from app.services import tenant_resolver
from app.services.auth import ROLE_ADMIN, decode_token, make_token

router = APIRouter(dependencies=[Depends(require_platform_admin)])


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    status: str
    plan: str
    created_at: datetime


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    plan: str = Field(default=PLAN_PILOT, max_length=24)


class OrgStatusIn(BaseModel):
    status: str = Field(pattern=f"^({STATUS_ACTIVE}|{STATUS_SUSPENDED}|trial)$")


@router.get("/organizations", response_model=list[OrgOut])
async def list_organizations(db: AsyncSession = Depends(get_bypass_db)) -> list[OrgOut]:
    rows = (
        await db.execute(select(Organization).order_by(Organization.id))
    ).scalars().all()
    return [OrgOut.model_validate(r) for r in rows]


@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_organization(
    body: OrgCreateIn, db: AsyncSession = Depends(get_bypass_db)
) -> OrgOut:
    await _refuse_if_onboarding_opens_a_simulated_channel(db)

    org = Organization(name=body.name.strip(), slug=body.slug, plan=body.plan)
    db.add(org)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="slug_already_exists") from exc
    await db.refresh(org)
    # The resolver caches the org list for 15s; without this a brand-new tenant
    # would be unroutable, and a suspension would keep working, for that long.
    tenant_resolver.reset_cache()
    return OrgOut.model_validate(org)


@router.patch("/organizations/{org_id}", response_model=OrgOut)
async def set_organization_status(
    org_id: int, body: OrgStatusIn, db: AsyncSession = Depends(get_bypass_db)
) -> OrgOut:
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    org.status = body.status
    await db.commit()
    await db.refresh(org)
    tenant_resolver.reset_cache()
    return OrgOut.model_validate(org)


@router.post("/impersonate/{org_id}")
async def impersonate(
    org_id: int,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict:
    """Swap the operator's session for one that acts inside `org_id`.

    Recorded before the cookie is issued, so the audit row exists even if the
    response never reaches the client. Suspended organizations are still
    enterable — that is usually exactly when an operator needs to look — which
    is what the `impersonating` mark on the token buys.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")

    # Name the operator, not just the org they entered. The audit row used to be
    # keyed on a synthetic "impersonation:org-N" address with the IP and user
    # agent hardcoded to None, so "who read our data on Tuesday?" could only be
    # answered with "someone". With PLATFORM_ADMIN_EMAILS there is a real actor
    # to record; it falls back to the anonymous form for a password session.
    from app.services.activity import record_login

    claims = decode_token(_token_from_request(request)) or {}
    # Keyed on the pair, not on the operator alone: `record_login` upserts, so
    # a single "impersonation:<operator>" key would have one operator's visits
    # to agency B overwrite their visits to agency A. This is still a counter
    # with a last-seen, not a per-event log — enough to answer "who, which
    # agency, how often, most recently when", which is the open gap.
    actor = claims.get("email") or "shared-password"
    await record_login(
        db,
        email=f"impersonation:{actor}:org-{org_id}",
        source="impersonate",
        org_id=org_id,
        # No IP, no user agent. The row lands in the *client's* user_activity,
        # which their own admins read back on the team page — deliberately, since
        # "who looked at our data" is their question to ask. But the operator's
        # address and device answer nothing for them, and handing every agency
        # those after each support visit is a platform-to-tenant leak.
        ip=None,
        user_agent=None,
    )
    _set_session_cookie(
        response,
        make_token(
            email=None, role=ROLE_ADMIN, org_id=org_id, impersonating=True
        ),
    )
    return {"ok": True, "org_id": org_id, "slug": org.slug}


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    channel: str
    destination: str
    label: str | None = None
    # The *names* of the environment variables holding this agency's
    # credentials, never the values. Safe to return, and the operator needs to
    # see which variables a route expects in order to set them.
    provider_account_ref: str | None = None
    credential_ref: str | None = None
    inbound_secret_ref: str | None = None
    verify_token_ref: str | None = None
    sender_override: str | None = None
    webhook_url: str | None = None


# An environment variable name, not a secret. Rejecting anything else is what
# stops an operator from pasting a live token into a database column by mistake
# — the field names invite exactly that.
_ENV_REF = r"^[A-Z][A-Z0-9_]{2,119}$"

def _forbidden_refs() -> frozenset[str]:
    """Environment variable names a route may not point at.

    Every field of Settings, computed rather than listed. The resolved value is
    handed to a provider as a bearer token or basic-auth password, so a ref
    naming AUTH_SECRET would post the deployment's signing key to Twilio, and
    one naming DATABASE_URL would post the database credentials to Meta. A
    hand-written denylist covered seven names and missed fifteen — including
    every provider secret, so an operator could also point one agency's route at
    another agency's variable, letting the second sign inbound messages into the
    first.

    The rule that generalises: an agency's credential lives in a variable of its
    own (TWILIO_AUTH_TOKEN_ACME), never in one this application already reads.
    """
    from app.config import Settings

    return frozenset(Settings.model_fields) | {
        "DATABASE_URL_BYPASS",
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
    }


async def _refs_claimed_elsewhere(
    db: AsyncSession, refs: list[str], *, org_id: int, route_id: int | None
) -> list[str]:
    """Which of these variables another organization's route already names.

    A credential belongs to one agency. Copying agency two's route to make
    agency three's — which is what the manual onboarding flow invites — left
    three pointing at two's token, so two held the secret that authenticates
    three's inbound messages and could inject leads and transcripts into their
    tenant. Nothing checked, and the validator's own comment claimed otherwise.
    """
    from sqlalchemy import or_

    from app.models.channel_route import ChannelRoute

    if not refs:
        return []

    # Serialise concurrent writers naming the same variable. Without this the
    # check is read-then-write across an await: two onboarding calls for
    # different agencies could both find no conflict and both commit, leaving
    # one holding the secret that authenticates the other's inbound messages —
    # the outcome the check exists to prevent.
    #
    # A unique index cannot express the rule: the same agency reusing one
    # credential across its own routes is the ordinary arrangement (a Twilio
    # account behind two numbers), so uniqueness would forbid the legitimate
    # case and still permit nothing useful. The lock is held to end of
    # transaction and is keyed on the variable name, so it costs nothing except
    # to a second writer claiming that exact name.
    for ref in sorted(set(refs)):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:ref))"), {"ref": ref}
        )
    conditions = [
        ChannelRoute.provider_account_ref.in_(refs),
        ChannelRoute.credential_ref.in_(refs),
        ChannelRoute.inbound_secret_ref.in_(refs),
        ChannelRoute.verify_token_ref.in_(refs),
    ]
    query = select(ChannelRoute).where(
        ChannelRoute.org_id != org_id, or_(*conditions)
    )
    if route_id is not None:
        query = query.where(ChannelRoute.id != route_id)
    rows = (await db.execute(query)).scalars().all()
    claimed = {
        ref
        for row in rows
        for ref in refs
        if ref
        in {
            row.provider_account_ref,
            row.credential_ref,
            row.inbound_secret_ref,
            row.verify_token_ref,
        }
    }
    return sorted(claimed)


def _named_refs(body: RouteIdentityIn) -> list[str]:
    return [
        ref
        for ref in (
            body.provider_account_ref,
            body.credential_ref,
            body.inbound_secret_ref,
            body.verify_token_ref,
        )
        if ref
    ]




async def _refuse_if_onboarding_opens_a_simulated_channel(db: AsyncSession) -> None:
    """The mirror of `_refuse_if_channel_is_simulated`, for the other order.

    A single-tenant install may legitimately run a simulated channel with a
    route on it — nothing to misattribute. Creating the *second* organization
    is what turns that into "anyone who knows the first agency's number can
    write into their tenant", and this endpoint had no check, so the invariant
    startup refuses was violable at runtime by onboarding.
    """
    from sqlalchemy import select as _select

    from app.models.channel_route import ChannelRoute

    settings = get_settings()
    simulated = {
        CHANNEL_SMS: settings.SMS_SIMULATED,
        CHANNEL_WHATSAPP: settings.WHATSAPP_SIMULATED,
        CHANNEL_EMAIL: settings.EMAIL_SIMULATED,
        CHANNEL_VOICE: settings.VOICE_SIMULATED,
    }
    if not any(simulated.values()):
        return
    routed = {c for (c,) in await db.execute(_select(ChannelRoute.channel).distinct())}
    exposed = sorted(c for c in routed if simulated.get(c))
    if not exposed:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "error": "channels_in_simulated_mode_are_routed",
            "channels": exposed,
            "hint": (
                "These accept unsigned inbound and already have destinations "
                "mapped. A second organization makes that exploitable. Set "
                + ", ".join(f"{c.upper()}_SIMULATED=false" for c in exposed)
                + " and configure the provider secrets first."
            ),
        },
    )


async def _refuse_if_channel_is_simulated(channel: str) -> None:
    """A simulated channel accepts unsigned inbound; a route makes it reachable.

    Startup refuses the combination, but only at startup — and organizations and
    routes are created through this API on a running process. Without the same
    check here, onboarding a second agency left every webhook skipping signature
    verification until the next restart, so anyone who knew that agency's public
    number could write leads and book visits inside their tenant.
    """
    settings = get_settings()
    simulated = {
        CHANNEL_SMS: settings.SMS_SIMULATED,
        CHANNEL_WHATSAPP: settings.WHATSAPP_SIMULATED,
        CHANNEL_EMAIL: settings.EMAIL_SIMULATED,
        CHANNEL_VOICE: settings.VOICE_SIMULATED,
    }
    if channel == CHANNEL_CALENDAR or not simulated.get(channel):
        return
    real = tenant_resolver.routable_candidates(await tenant_resolver.active_orgs())
    if len(real) < 2:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "error": "channel_is_in_simulated_mode",
            "channel": channel,
            "hint": (
                f"{channel.upper()}_SIMULATED accepts unsigned inbound. Turn it "
                "off and configure the provider secret before routing a "
                "destination to it."
            ),
        },
    )


async def _refuse_shared_refs(
    db: AsyncSession, body: RouteIdentityIn, *, org_id: int, route_id: int | None
) -> None:
    shared = await _refs_claimed_elsewhere(
        db, _named_refs(body), org_id=org_id, route_id=route_id
    )
    if shared:
        raise HTTPException(
            status_code=409,
            detail={"error": "credential_belongs_to_another_organization",
                    "names": shared},
        )


def _refuse_a_route_that_cannot_verify(body: RouteCreateIn | RouteIdentityIn,
                                       channel: str) -> None:
    """An agency on its own account must be able to receive, not only send.

    For Twilio the auth token is both, so `credential_ref` alone is complete.
    Everywhere else the sending credential and the signing secret are different
    values — Meta's access token is not its app secret — so naming only the
    credential leaves `inbound_secret` unresolvable, and every genuine inbound
    message for that agency 403s forever with nothing to explain it. Both
    fields are individually valid, so no other check can see it.
    """
    if channel in (CHANNEL_SMS, CHANNEL_CALENDAR):
        # Twilio signs inbound with the sending token, and nothing is ever
        # delivered TO a calendar.
        return
    if body.credential_ref and not body.inbound_secret_ref:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "inbound_secret_ref_required",
                "channel": channel,
                "hint": (
                    f"On {channel} the sending credential and the signing secret "
                    "are different values, so a route with only credential_ref "
                    "would reject every inbound message. Name both."
                ),
            },
        )


def _validate_refs(body: RouteIdentityIn) -> None:
    """Shared by create and patch. It lived only in patch, so the create path
    wrote whatever it was given — the control was bypassed by using the other
    endpoint."""
    named = _named_refs(body)
    forbidden = sorted({r for r in named if r in _forbidden_refs()})
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail={"error": "refers_to_a_deployment_secret", "names": forbidden},
        )
    missing = [ref for ref in named if not os.environ.get(ref)]
    if missing:
        # Saving a reference to a variable that is not set produces a route that
        # refuses every send at runtime. Better to fail here, where the operator
        # is looking, than during a lead's first message.
        raise HTTPException(
            status_code=400,
            detail={"error": "environment_variables_not_set", "names": missing},
        )


class RouteIdentityIn(BaseModel):
    """The credentials half of a route, set separately from creating it."""

    provider_account_ref: str | None = Field(default=None, pattern=_ENV_REF)
    credential_ref: str | None = Field(default=None, pattern=_ENV_REF)
    inbound_secret_ref: str | None = Field(default=None, pattern=_ENV_REF)
    verify_token_ref: str | None = Field(default=None, pattern=_ENV_REF)
    sender_override: str | None = Field(default=None, max_length=254)
    webhook_url: str | None = Field(default=None, max_length=500)


class RouteCreateIn(RouteIdentityIn):
    org_id: int
    channel: str = Field(pattern=r"^(whatsapp|sms|email|voice|calendar)$")
    destination: str = Field(min_length=3, max_length=254)
    label: str | None = Field(default=None, max_length=120)


@router.get("/routes", response_model=list[RouteOut])
async def list_routes(db: AsyncSession = Depends(get_bypass_db)) -> list[RouteOut]:
    from app.models.channel_route import ChannelRoute

    rows = (
        await db.execute(select(ChannelRoute).order_by(ChannelRoute.id))
    ).scalars().all()
    return [RouteOut.model_validate(r) for r in rows]


@router.post("/routes", response_model=RouteOut, status_code=201)
async def create_route(
    body: RouteCreateIn, db: AsyncSession = Depends(get_bypass_db)
) -> RouteOut:
    """Point an inbound destination at an agency.

    Until a destination is mapped, inbound messages for a second tenant are
    refused rather than filed under the first — so this is the prerequisite for
    onboarding client number two.
    """
    from app.models.channel_route import ChannelRoute, normalize_destination

    org = (
        await db.execute(select(Organization).where(Organization.id == body.org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    if body.org_id == DEMO_ORG_ID:
        # Organization ids are small integers and the docs example uses 3, so a
        # typo lands here easily. The demo org is what `POST /auth/register`
        # drops anonymous visitors into as viewers, so a live route pointed at
        # it publishes real leads' phone numbers and transcripts.
        raise HTTPException(status_code=400, detail="cannot_route_to_demo_org")
    _validate_refs(body)
    _refuse_a_route_that_cannot_verify(body, body.channel)
    await _refuse_if_channel_is_simulated(body.channel)
    await _refuse_shared_refs(db, body, org_id=body.org_id, route_id=None)

    route = ChannelRoute(
        org_id=body.org_id,
        channel=body.channel,
        destination=normalize_destination(body.destination),
        label=body.label,
        provider_account_ref=body.provider_account_ref,
        credential_ref=body.credential_ref,
        inbound_secret_ref=body.inbound_secret_ref,
        verify_token_ref=body.verify_token_ref,
        sender_override=body.sender_override,
        webhook_url=body.webhook_url,
    )
    db.add(route)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # A destination belongs to exactly one agency; two claiming it is the
        # ambiguity this table exists to prevent.
        raise HTTPException(
            status_code=409, detail="destination_already_routed"
        ) from exc
    await db.refresh(route)
    return RouteOut.model_validate(route)


@router.delete("/routes/{route_id}")
async def delete_route(route_id: int, db: AsyncSession = Depends(get_bypass_db)) -> dict:
    from app.models.channel_route import ChannelRoute

    route = (
        await db.execute(select(ChannelRoute).where(ChannelRoute.id == route_id))
    ).scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="route_not_found")
    await db.delete(route)
    await db.commit()
    return {"ok": True}


@router.delete("/members/{email}")
async def release_member(
    email: str,
    force: bool = False,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict:
    """Free a globally-unique email that is held by the wrong organization.

    `allowed_users.email` is unique across every tenant, and any agency's admin
    can add a row through the ordinary team page. So one agency could claim an
    address belonging to another — or an operator's own — and nothing in the API
    could take it back: the team router's delete runs under RLS and cannot see a
    row in someone else's org, and this router could only ever invite. The
    remedy was psql.

    Returns which organization was holding it, because the operator needs to
    know whether this was a mistake or a squat.
    """
    from app.api.v1.team import _norm_email
    from app.models import AllowedUser

    normalised = _norm_email(email)
    row = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == normalised))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="email_not_found")
    held_by = row.org_id

    if row.role == ROLE_ADMIN and not force:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(AllowedUser)
                .where(
                    AllowedUser.org_id == held_by,
                    AllowedUser.role == ROLE_ADMIN,
                    AllowedUser.email != normalised,
                )
            )
        ).scalar_one()
        if remaining == 0:
            # The team router refuses this for the same reason: an agency with no
            # admin cannot reach /settings or /team, both of which require one,
            # so its staff are locked out of their own dashboard with only the
            # operator able to repair it. Freeing a squatted address must not be
            # able to do that by accident.
            # `force` exists because the two rules genuinely conflict: a squatted
            # row can also be the holding org's only admin, and refusing outright
            # would make the squat permanent again — which is the thing this
            # route was added to end. The operator gets told what they are about
            # to do rather than being stopped by it.
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "would_leave_organization_without_an_admin",
                    "org_id": held_by,
                    "hint": "re-send with ?force=true, then invite an admin",
                },
            )

    await db.delete(row)
    await db.commit()
    return {"ok": True, "email": normalised, "was_held_by_org": held_by}


@router.patch("/routes/{route_id}/identity")
async def set_route_identity(
    route_id: int, body: RouteIdentityIn, db: AsyncSession = Depends(get_bypass_db)
) -> RouteOut:
    """Point a route at the agency's own provider account.

    This is what makes a second agency safe to onboard. Until a route names its
    own credentials, replies to that agency's leads go out from the operator's
    number — so the lead answers the operator, and the rest of their
    conversation is written into the operator's tenant.

    The values are environment variable NAMES. Set the variables, restart, then
    call this. Fields left null are cleared, so an agency can be handed back to
    the shared account by patching them away.
    """
    from app.models.channel_route import ChannelRoute

    route = (
        await db.execute(select(ChannelRoute).where(ChannelRoute.id == route_id))
    ).scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="route_not_found")

    _validate_refs(body)
    _refuse_a_route_that_cannot_verify(body, route.channel)
    await _refuse_shared_refs(db, body, org_id=route.org_id, route_id=route.id)

    for field, value in body.model_dump().items():
        setattr(route, field, value)
    await db.commit()
    await db.refresh(route)
    return RouteOut.model_validate(route)


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    # `viewer` is deliberately absent. It is a role of the `accounts` table, not
    # of `allowed_users`: `resolve_email_access` reads anything that is not
    # "admin" as a member, so inviting a read-only auditor as `viewer` silently
    # handed them write access to the agency's leads. The team router restricts
    # this to the same two values.
    role: str = Field(default="admin", pattern=r"^(admin|member)$")


@router.post("/organizations/{org_id}/members", status_code=201)
async def invite_member(
    org_id: int, body: InviteIn, db: AsyncSession = Depends(get_bypass_db)
) -> dict:
    """Give a person access to a client agency.

    The last step of onboarding: without it a newly created organization has no
    one who can log into it, so `create_organization` on its own produces a
    tenant nobody can reach.

    Runs on the bypass session because the operator is acting on a tenant that
    is not their own — `add_member` in the team router does the same job from
    inside an agency, scoped by RLS.
    """
    from app.api.v1.team import _norm_email
    from app.models import AllowedUser

    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    if org.status == "suspended":
        # The row would be created and the sign-in would then 403 at the
        # suspension gate, which reads as "the invite silently did nothing".
        raise HTTPException(status_code=409, detail="organization_is_suspended")

    # An unvalidated string here is not cosmetic: `allowed_users.email` is
    # globally unique, so a typo permanently consumes the slot for a real
    # address and can only be removed by an admin of that org — who may be the
    # very person being invited.
    email = _norm_email(body.email)
    row = AllowedUser(email=email, role=body.role, added_by="platform", org_id=org_id)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Email is globally unique — identity is one person, one organization —
        # so this is the operator being told the person already belongs
        # somewhere, not a constraint surprising them.
        raise HTTPException(
            status_code=409, detail="email_already_belongs_to_an_organization"
        ) from exc
    await db.refresh(row)
    return {"id": row.id, "email": row.email, "role": row.role, "org_id": org_id}

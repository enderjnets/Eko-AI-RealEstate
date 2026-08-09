"""Auth API — login (password + Google) / logout / session check + the
require_auth and require_admin gates.

The session token carries identity + role. Password login → admin (master key).
Google login → the role resolved from the access list (services/auth).
"""
from __future__ import annotations

import hmac
import logging
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_bypass_db
from app.models.organization import DEFAULT_ORG_ID, DEMO_ORG_ID
from app.services.auth import (
    COOKIE_NAME,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_VIEWER,
    SAFE_METHODS,
    AppleAuthError,
    GoogleAuthError,
    check_password,
    decode_token,
    hash_password,
    make_token,
    resolve_email_access,
    resolve_email_org,
    token_is_superuser,
    token_org_id,
    token_role,
    verify_apple_id_token,
    verify_google_id_token,
    verify_password,
    verify_token,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _safe_record_login(
    db: AsyncSession, email: str, source: str, request: Request, org_id: int | None = None
) -> None:
    """Best-effort: bump the user's login_count. Never break login on a telemetry error."""
    try:
        from app.services.activity import client_ip, record_login

        await record_login(
            db, email=email, source=source, org_id=org_id,
            ip=client_ip(request), user_agent=request.headers.get("user-agent"),
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("record_login skipped for %s: %s", email, exc)

log = logging.getLogger(__name__)
router = APIRouter()


def _token_from_request(request: Request) -> str | None:
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def current_role(request: Request) -> str:
    """Role of the current session. When AUTH_ENABLED is false (dev/demo without
    login) everyone is admin; otherwise the token's role (None token → member)."""
    if not get_settings().AUTH_ENABLED:
        return ROLE_ADMIN
    return token_role(_token_from_request(request)) or ROLE_MEMBER


async def require_auth(request: Request) -> None:
    """Dependency for protected data routes. No-op when AUTH_ENABLED is false.

    Read-only enforcement: a `viewer` (self-registered demo account) may only use
    safe HTTP methods (GET/HEAD/OPTIONS); any write is rejected with 403. This is
    the single choke-point — every mutating data route depends on require_auth."""
    if not get_settings().AUTH_ENABLED:
        return
    token = _token_from_request(request)
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    # A signature-valid token whose `org` claim is not a usable id leaves the
    # request org-less. Reads then fail closed and correctly return nothing, but
    # writes hit the RLS WITH CHECK and surface as an opaque 500 — a dashboard
    # that is silently empty and errors on save, with nothing telling the user to
    # sign in again. Reject it as unauthenticated instead.
    if token_org_id(token) is None:
        raise HTTPException(
            status_code=401, detail="Session has no organization; sign in again"
        )
    if current_role(request) == ROLE_VIEWER and request.method not in SAFE_METHODS:
        raise HTTPException(status_code=403, detail="view_only")


async def require_admin(request: Request) -> None:
    """Dependency for admin-only routes (team + settings). No-op when AUTH_ENABLED
    is false; otherwise requires a valid session whose role is admin."""
    if not get_settings().AUTH_ENABLED:
        return
    token = _token_from_request(request)
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if token_org_id(token) is None:
        raise HTTPException(
            status_code=401, detail="Session has no organization; sign in again"
        )
    if current_role(request) != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admins only")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


class GoogleLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_token: str


class AppleLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_token: str


class RegisterIn(BaseModel):
    """Public self-registration for a read-only ("viewer") demo account."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=280)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=160)


class AccountLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class MeOut(BaseModel):
    authenticated: bool
    auth_enabled: bool
    role: str = ROLE_MEMBER
    google_signin_enabled: bool = False
    apple_signin_enabled: bool = False
    registration_enabled: bool = True
    # Operator-only controls hide themselves when this is false — the MLS sync
    # button, discovery. The gate is the backend's; this only spares a tenant a
    # 403 on a button they were invited to press.
    is_platform_operator: bool = False


def _set_session_cookie(
    response: Response, token: str, request: Request | None
) -> None:
    s = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_is_secure(request),
        max_age=s.AUTH_TTL_HOURS * 3600,
        path="/",
    )


def _cookie_is_secure(request: Request | None) -> bool:
    """Whether to mark the session cookie `Secure`.

    Decided per request rather than from `APP_ENV`. The same install is reached
    two ways: over TLS at its domain, and over plain http on the LAN. Keying
    `Secure` off the environment forces one answer for both — in production the
    browser refuses to keep the cookie on the LAN address and nobody can hold a
    session there, which is why this install was still marked `development` and
    therefore sending session cookies over http on the domain too.

    Per request, each gets the right answer: `Secure` behind TLS, and a working
    session on the LAN, with no environment flag deciding a security property
    it cannot actually observe.
    """
    if request is None:
        # No request in hand — take the strict answer.
        return True
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    scheme = forwarded or request.url.scheme
    return scheme == "https"


def _is_platform_operator(email: str | None) -> bool:
    """Whether this verified email runs the platform, rather than an agency.

    The `su` claim is what unlocks /api/v1/platform. Before this existed the
    only issuer was the shared-password login, so the Google-only deployment
    the docs recommend — password set to a random string nobody knows — had no
    way to reach the routes that onboard agency number two.
    """
    if not email:
        return False
    return email.lower().strip() in get_settings().platform_admin_emails_list


async def _sso_session(
    email: str, db: AsyncSession
) -> tuple[str, int, bool] | None:
    """Resolve a verified SSO email to (role, org_id, superuser), or None to deny.

    Both halves have to succeed. `resolve_email_access` can say yes from env
    alone (GOOGLE_ALLOWED_DOMAIN), while the organization only comes from an
    `allowed_users` row — so a domain left over from onboarding another agency
    used to mint a valid member session pointed at client zero. No org means no
    session.
    """
    role = await resolve_email_access(email, db)
    if role is None:
        return None
    org_id = await resolve_email_org(email, db)
    if org_id is None:
        return None
    return role, org_id, _is_platform_operator(email)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, bool]:
    s = get_settings()
    if not s.AUTH_ENABLED:
        return {"ok": True, "auth_enabled": False}
    if not check_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    # NEVER a platform key, not even as a fallback. This password is handed to
    # the agency: install.sh calls it "protects /leads" and the office shares it
    # with whoever answers the phone. Keeping it as the issuer of `su` while
    # PLATFORM_ADMIN_EMAILS was empty — which is the shipped default — meant
    # client zero's receptionist could list every tenant, read every agency's
    # routed numbers, and impersonate into any of them. That is the boundary
    # collapse this whole mechanism exists to prevent, reintroduced through a
    # convenience.
    #
    # There is no lockout to fear: an operator with no PLATFORM_ADMIN_EMAILS set
    # has an empty platform anyway, and setting an environment variable is
    # something only they can do.
    _set_session_cookie(
        response,
        make_token(role=ROLE_ADMIN, org_id=DEFAULT_ORG_ID),
        request,
    )
    return {"ok": True, "auth_enabled": True}


@router.post("/login/google")
async def login_google(
    body: GoogleLoginIn,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict[str, bool]:
    """Validate a Google ID token (from the @react-oauth/google client), resolve
    the verified email against the access list to a role, and — if allowed —
    issue the same HMAC session cookie as the password flow."""
    s = get_settings()
    if not s.AUTH_ENABLED:
        return {"ok": True, "auth_enabled": False}
    try:
        email = verify_google_id_token(body.id_token)
    except GoogleAuthError as e:
        log.warning("google_signin_failed reason=%s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    session = await _sso_session(email, db)
    if session is None:
        log.warning("google_signin_denied email=%s", email)
        raise HTTPException(status_code=401, detail="email_not_in_allow_list")
    role, org_id, superuser = session
    _set_session_cookie(
        response,
        make_token(email=email, role=role, org_id=org_id, superuser=superuser),
        request,
    )
    await _safe_record_login(db, email, "google", request, org_id)
    return {"ok": True, "auth_enabled": True}


@router.post("/login/google/callback")
async def login_google_callback(
    request: Request,
    credential: str = Form(...),
    g_csrf_token: str = Form(default=""),
    db: AsyncSession = Depends(get_bypass_db),
) -> RedirectResponse:
    """Redirect-mode landing for "Sign in with Google" (`ux_mode=redirect`).

    Google posts the ID token here as a top-level form navigation (the popup
    flow is unreliable on mobile — phones open it as a new tab and the credential
    never returns). We verify Google's double-submit-cookie CSRF token, validate
    the ID token + access list with the same helpers as the JSON flow, set the
    session cookie, and 303 back into the app. Failures redirect to /login with
    a flag instead of surfacing a raw error to the user."""
    s = get_settings()
    if not s.AUTH_ENABLED:
        return RedirectResponse("/leads", status_code=303)
    cookie_csrf = request.cookies.get("g_csrf_token", "")
    if not g_csrf_token or not cookie_csrf or not hmac.compare_digest(g_csrf_token, cookie_csrf):
        log.warning("google_signin_csrf_failed")
        return RedirectResponse("/login?error=google_failed", status_code=303)
    try:
        email = verify_google_id_token(credential)
    except GoogleAuthError as e:
        log.warning("google_signin_failed reason=%s", e)
        return RedirectResponse("/login?error=google_failed", status_code=303)
    session = await _sso_session(email, db)
    if session is None:
        log.warning("google_signin_denied email=%s", email)
        return RedirectResponse("/login?error=google_denied", status_code=303)
    role, org_id, superuser = session
    resp = RedirectResponse("/leads", status_code=303)
    _set_session_cookie(
        resp,
        make_token(email=email, role=role, org_id=org_id, superuser=superuser),
        request,
    )
    await _safe_record_login(db, email, "google", request, org_id)
    return resp


@router.post("/login/apple")
async def login_apple(
    body: AppleLoginIn,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict[str, bool]:
    """Validate an Apple identity token (from the Sign in with Apple JS popup),
    resolve the verified email against the access list to a role, and — if
    allowed — issue the same HMAC session cookie as the Google/password flows."""
    s = get_settings()
    if not s.AUTH_ENABLED:
        return {"ok": True, "auth_enabled": False}
    try:
        email = verify_apple_id_token(body.id_token)
    except AppleAuthError as e:
        log.warning("apple_signin_failed reason=%s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e
    session = await _sso_session(email, db)
    if session is None:
        log.warning("apple_signin_denied email=%s", email)
        raise HTTPException(status_code=401, detail="email_not_in_allow_list")
    role, org_id, superuser = session
    _set_session_cookie(
        response,
        make_token(email=email, role=role, org_id=org_id, superuser=superuser),
        request,
    )
    await _safe_record_login(db, email, "apple", request, org_id)
    return {"ok": True, "auth_enabled": True}


@router.post("/register", status_code=201)
async def register(
    body: RegisterIn,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict[str, object]:
    """Public self-registration → a read-only ("viewer") demo account.

    Creates the account with a hashed password + profile, then signs the visitor
    in (sets the session cookie) so they land straight in the dashboard. These
    accounts can browse everything but cannot mutate anything (enforced server-side
    in require_auth)."""
    if not get_settings().REGISTRATION_ENABLED:
        # The flag was advertised in /auth/me from the day it shipped and
        # read nowhere else, so the switch the frontend renders its signup
        # form from could never actually turn signup off.
        raise HTTPException(status_code=403, detail="registration_disabled")

    from app.models import Account

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="invalid_email")

    existing = (
        await db.execute(select(Account).where(Account.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="email_already_registered")

    account = Account(
        email=email,
        # Explicit: this runs on a bypass session (no org bound), so the
        # before_flush stamp does not fire and the row would have no org.
        org_id=DEMO_ORG_ID,
        password_hash=hash_password(body.password),
        role=ROLE_VIEWER,
        name=body.name.strip(),
        phone=(body.phone or None),
        address=(body.address or None),
        state=(body.state or None),
        country=(body.country or None),
        company=(body.company or None),
    )
    db.add(account)
    await db.commit()
    account_org_id = account.org_id
    log.info("New viewer account registered: %s", email)

    # Sign them in immediately (cookie). When AUTH_ENABLED is false the cookie is
    # simply ignored — the dashboard is already open in that mode.
    _set_session_cookie(
        response,
        make_token(email=email, role=ROLE_VIEWER, org_id=DEMO_ORG_ID),
        request,
    )
    await _safe_record_login(db, email, "account", request, account_org_id)
    return {"ok": True, "role": ROLE_VIEWER, "auth_enabled": get_settings().AUTH_ENABLED}


@router.post("/login/account")
async def login_account(
    body: AccountLoginIn,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_bypass_db),
) -> dict[str, object]:
    """Email + password login for a self-registered (viewer/member) account."""
    from app.models import Account

    email = body.email.strip().lower()
    account = (
        await db.execute(select(Account).where(Account.email == email))
    ).scalar_one_or_none()
    if account is None or not verify_password(body.password, account.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    account_org_id = account.org_id
    # account.org_id was loaded with the row above; ignoring it was how every
    # self-registered user ended up acting for the default organization.
    _set_session_cookie(
        response,
        make_token(
            email=email,
            role=account.role or ROLE_VIEWER,
            org_id=account.org_id or DEMO_ORG_ID,
        ),
        request,
    )
    await _safe_record_login(db, email, "account", request, account_org_id)
    return {"ok": True, "role": account.role or ROLE_VIEWER, "auth_enabled": get_settings().AUTH_ENABLED}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


def _viewer_is_operator(request: Request) -> bool:
    """Whether this session would pass `require_platform_admin`.

    Deliberately re-reads the email from the token and re-checks the env list,
    rather than trusting the `su` claim alone — the same order the real gate
    uses, so the button cannot appear for someone the gate would refuse.
    """
    if not get_settings().platform_admin_emails_list:
        return False
    from app.services.auth import decode_token, token_is_superuser

    token = _token_from_request(request)
    if not token_is_superuser(token):
        return False
    payload = decode_token(token) or {}
    # The same three the real gate applies, in the same order. Checking only
    # `su` and the email list showed the button to an operator signed in as a
    # member, or holding a token minted before organizations existed — a 403
    # on a control that had just been made visible to fix a 403.
    # Via the same readers the real gate uses. Reading `org` straight off the
    # payload was stricter than `token_org_id`, which maps a missing claim to
    # the default organization — so a `su` token minted before organizations
    # existed was refused the button while the API accepted it. The inverse of
    # the bug this function was added to fix.
    if token_role(token) != ROLE_ADMIN or token_org_id(token) is None:
        return False
    return _is_platform_operator(payload.get("email"))


@router.get("/me", response_model=MeOut)
async def me(request: Request) -> MeOut:
    s = get_settings()
    # An office's allow-list (env or DB) governs both providers; a social button
    # only makes sense once a client ID is set AND some allow-list source exists.
    allow_list_configured = bool(
        s.google_admin_emails_list or s.google_allowed_emails_list or s.GOOGLE_ALLOWED_DOMAIN
    )
    google_enabled = bool(s.GOOGLE_CLIENT_ID) and allow_list_configured
    apple_enabled = bool(s.APPLE_CLIENT_ID) and allow_list_configured
    if not s.AUTH_ENABLED:
        return MeOut(
            authenticated=True,
            auth_enabled=False,
            role=ROLE_ADMIN,
            google_signin_enabled=google_enabled,
            apple_signin_enabled=apple_enabled,
            registration_enabled=s.REGISTRATION_ENABLED,
        )
    authed = verify_token(_token_from_request(request))
    return MeOut(
        authenticated=authed,
        auth_enabled=True,
        role=current_role(request) if authed else ROLE_MEMBER,
        google_signin_enabled=google_enabled,
        apple_signin_enabled=apple_enabled,
        registration_enabled=s.REGISTRATION_ENABLED,
        is_platform_operator=authed and _viewer_is_operator(request),
    )


async def require_platform_admin(request: Request) -> None:
    """Routes that belong to the operator of the platform, not to any tenant.

    require_admin is not enough on its own: it authorises the admin OF SOME
    organization, and every client agency has one. Anything reaching across
    tenants — the demo signup list, tenant lifecycle, impersonation — needs the
    `su` claim, which only the emails in PLATFORM_ADMIN_EMAILS receive.

    Naming the default organization is deliberately NOT what grants this. That
    org is a real client agency (slug `client-zero`), so its own admins would
    have inherited platform rights, and so would any token issued before
    multi-tenancy, which carries no org at all.

    Three conditions, none of which is sufficient alone.

    **Authentication must be on.** With `AUTH_ENABLED=false` — the compose
    default — tokens are signed with a constant published in this repository,
    so a `su` claim proves nothing; and `require_admin` is a no-op, which made
    these routes outright anonymous. There is no configuration in which an
    unauthenticated caller creates tenants, so this gate does not stand down
    the way the others do.

    **An operator list must exist.** An empty PLATFORM_ADMIN_EMAILS means
    nobody has been designated, and the answer to "who may do this" is nobody —
    not "whoever holds a token".

    **The token's own email must still be on that list**, not merely its `su`
    bit. Re-reading it is what makes removal take effect: dropping someone from
    the env retires their access at the next request instead of whenever their
    week-long cookie happens to expire.
    """
    settings = get_settings()
    if not settings.AUTH_ENABLED or not settings.platform_admin_emails_list:
        raise HTTPException(status_code=403, detail="Platform operators only")

    token = _token_from_request(request)
    if not token_is_superuser(token):
        raise HTTPException(status_code=403, detail="Platform operators only")
    claims = decode_token(token) or {}
    email = str(claims.get("email") or "").lower().strip()
    if email not in settings.platform_admin_emails_list:
        raise HTTPException(status_code=403, detail="Platform operators only")

    await require_admin(request)

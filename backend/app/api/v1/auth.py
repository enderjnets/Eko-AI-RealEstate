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
    hash_password,
    make_token,
    resolve_email_access,
    resolve_email_org,
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
    if not verify_token(_token_from_request(request)):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if current_role(request) == ROLE_VIEWER and request.method not in SAFE_METHODS:
        raise HTTPException(status_code=403, detail="view_only")


async def require_admin(request: Request) -> None:
    """Dependency for admin-only routes (team + settings). No-op when AUTH_ENABLED
    is false; otherwise requires a valid session whose role is admin."""
    if not get_settings().AUTH_ENABLED:
        return
    if not verify_token(_token_from_request(request)):
        raise HTTPException(status_code=401, detail="Not authenticated")
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


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=s.is_production,
        max_age=s.AUTH_TTL_HOURS * 3600,
        path="/",
    )


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict[str, bool]:
    s = get_settings()
    if not s.AUTH_ENABLED:
        return {"ok": True, "auth_enabled": False}
    if not check_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    # The shared password is the operator's master key, not a client agency's,
    # so it acts for the default org and carries platform superuser rights.
    _set_session_cookie(
        response, make_token(role=ROLE_ADMIN, org_id=DEFAULT_ORG_ID, superuser=True)
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
    role = await resolve_email_access(email, db)
    org_id = await resolve_email_org(email, db)
    if role is None:
        log.warning("google_signin_denied email=%s", email)
        raise HTTPException(status_code=401, detail="email_not_in_allow_list")
    _set_session_cookie(response, make_token(email=email, role=role, org_id=org_id))
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
    role = await resolve_email_access(email, db)
    org_id = await resolve_email_org(email, db)
    if role is None:
        log.warning("google_signin_denied email=%s", email)
        return RedirectResponse("/login?error=google_denied", status_code=303)
    resp = RedirectResponse("/leads", status_code=303)
    _set_session_cookie(resp, make_token(email=email, role=role, org_id=org_id))
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
    role = await resolve_email_access(email, db)
    org_id = await resolve_email_org(email, db)
    if role is None:
        log.warning("apple_signin_denied email=%s", email)
        raise HTTPException(status_code=401, detail="email_not_in_allow_list")
    _set_session_cookie(response, make_token(email=email, role=role, org_id=org_id))
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
        response, make_token(email=email, role=ROLE_VIEWER, org_id=DEMO_ORG_ID)
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
    )
    await _safe_record_login(db, email, "account", request, account_org_id)
    return {"ok": True, "role": account.role or ROLE_VIEWER, "auth_enabled": get_settings().AUTH_ENABLED}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


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
        )
    authed = verify_token(_token_from_request(request))
    return MeOut(
        authenticated=authed,
        auth_enabled=True,
        role=current_role(request) if authed else ROLE_MEMBER,
        google_signin_enabled=google_enabled,
        apple_signin_enabled=apple_enabled,
    )

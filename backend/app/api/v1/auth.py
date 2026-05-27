"""Auth API — login (password + Google) / logout / session check + the
require_auth and require_admin gates.

The session token carries identity + role. Password login → admin (master key).
Google login → the role resolved from the access list (services/auth).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.services.auth import (
    COOKIE_NAME,
    ROLE_ADMIN,
    ROLE_MEMBER,
    AppleAuthError,
    GoogleAuthError,
    check_password,
    make_token,
    resolve_email_access,
    token_role,
    verify_apple_id_token,
    verify_google_id_token,
    verify_token,
)

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
    """Dependency for protected data routes. No-op when AUTH_ENABLED is false."""
    if not get_settings().AUTH_ENABLED:
        return
    if not verify_token(_token_from_request(request)):
        raise HTTPException(status_code=401, detail="Not authenticated")


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


class MeOut(BaseModel):
    authenticated: bool
    auth_enabled: bool
    role: str = ROLE_MEMBER
    google_signin_enabled: bool = False
    apple_signin_enabled: bool = False


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
    _set_session_cookie(response, make_token(role=ROLE_ADMIN))
    return {"ok": True, "auth_enabled": True}


@router.post("/login/google")
async def login_google(
    body: GoogleLoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
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
    if role is None:
        log.warning("google_signin_denied email=%s", email)
        raise HTTPException(status_code=401, detail="email_not_in_allow_list")
    _set_session_cookie(response, make_token(email=email, role=role))
    return {"ok": True, "auth_enabled": True}


@router.post("/login/apple")
async def login_apple(
    body: AppleLoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
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
    if role is None:
        log.warning("apple_signin_denied email=%s", email)
        raise HTTPException(status_code=401, detail="email_not_in_allow_list")
    _set_session_cookie(response, make_token(email=email, role=role))
    return {"ok": True, "auth_enabled": True}


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

"""Auth API — dashboard login / logout / session check + the require_auth gate."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.services.auth import COOKIE_NAME, check_password, make_token, verify_token

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


async def require_auth(request: Request) -> None:
    """Dependency for protected data routes. No-op when AUTH_ENABLED is false."""
    if not get_settings().AUTH_ENABLED:
        return
    if not verify_token(_token_from_request(request)):
        raise HTTPException(status_code=401, detail="Not authenticated")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


class MeOut(BaseModel):
    authenticated: bool
    auth_enabled: bool


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict[str, bool]:
    s = get_settings()
    if not s.AUTH_ENABLED:
        return {"ok": True, "auth_enabled": False}
    if not check_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = make_token()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=s.is_production,
        max_age=s.AUTH_TTL_HOURS * 3600,
        path="/",
    )
    return {"ok": True, "auth_enabled": True}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
async def me(request: Request) -> MeOut:
    s = get_settings()
    if not s.AUTH_ENABLED:
        return MeOut(authenticated=True, auth_enabled=False)
    return MeOut(authenticated=verify_token(_token_from_request(request)), auth_enabled=True)

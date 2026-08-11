"""The one unauthenticated route that is not a provider webhook.

Everything here exists because the caller is a stranger. The tenant comes from
a form key looked up in `channel_routes` — never from the request claiming an
organization — and the org is bound before the first write, exactly like the
webhook handlers do it. Under default-deny RLS a missed binding writes nothing,
which is the failure mode we want: a lost submission is recoverable, a
submission filed into another agency's dashboard is not.
"""
from __future__ import annotations

import logging
import time
from collections import deque

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models.channel_route import CHANNEL_WEB
from app.services.capture import (
    MAX_CONSENT_TEXT,
    MAX_MESSAGE,
    MAX_NAME,
    CaptureRejected,
    FormSubmission,
    capture_lead,
)
from app.services.tenant_context import set_org_id
from app.services.tenant_resolver import WebhookOrgUnresolved, webhook_org_or_refuse

log = logging.getLogger(__name__)
router = APIRouter()

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# ── Rate limiting ────────────────────────────────────────────────────────
# Two windows, and the second is the one that matters. A per-IP limit alone is
# decorative behind a proxy: the client IP is read from a header, and anyone
# willing to rotate that header has an unlimited per-IP budget. The global
# ceiling is what bounds the damage regardless of how many identities the
# caller invents.
#
# In-process counters are correct here only because the app is pinned to a
# single uvicorn worker — the same constraint main.py documents for the three
# background loops. Under `--workers N` these become N independent budgets and
# belong in Redis alongside those loops.
PER_IP_LIMIT = 5
PER_IP_WINDOW = 600.0
GLOBAL_LIMIT = 60
GLOBAL_WINDOW = 600.0
# Bounded so a flood of distinct (or forged) addresses cannot grow the map
# without limit — the memory itself would otherwise be the attack.
MAX_TRACKED_IPS = 5_000

_hits: dict[str, deque[float]] = {}
_global_hits: deque[float] = deque()


def _prune(window: deque[float], now: float, span: float) -> None:
    while window and now - window[0] > span:
        window.popleft()


def _rate_limited(ip: str, now: float | None = None) -> bool:
    """Record this attempt and say whether it should be refused."""
    stamp = time.monotonic() if now is None else now

    _prune(_global_hits, stamp, GLOBAL_WINDOW)
    if len(_global_hits) >= GLOBAL_LIMIT:
        return True

    window = _hits.get(ip)
    if window is None:
        if len(_hits) >= MAX_TRACKED_IPS:
            # Drop the coldest tracked address rather than refuse service.
            # Sorting 5k deques is cheap next to a DB write and only happens
            # under genuine flood conditions.
            coldest = min(_hits, key=lambda k: _hits[k][-1] if _hits[k] else 0.0)
            _hits.pop(coldest, None)
        window = _hits[ip] = deque()
    _prune(window, stamp, PER_IP_WINDOW)
    if len(window) >= PER_IP_LIMIT:
        return True

    window.append(stamp)
    _global_hits.append(stamp)
    return False


def reset_rate_limits() -> None:
    """Test seam. Nothing in the app calls this."""
    _hits.clear()
    _global_hits.clear()


def client_ip(request: Request) -> str:
    """The visitor's address, as well as it can be known.

    `CF-Connecting-IP` first: Cloudflare overwrites it on every request, so a
    client cannot forge it through the tunnel this install actually runs behind.
    `X-Forwarded-For` is next and is only as trustworthy as whatever set it —
    hence the global ceiling above, which does not depend on any of this being
    honest.
    """
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf[:45]
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:45]
    return (request.client.host if request.client else "unknown")[:45]


async def _turnstile_ok(token: str | None, ip: str) -> bool:
    """Verify a Turnstile token, or pass when no secret is configured.

    Configured-but-unreachable fails CLOSED. A captcha that waves everyone
    through whenever Cloudflare has a bad minute is not a captcha, and this is
    the only defence here that a determined script cannot simply outspend.
    """
    secret = (get_settings().TURNSTILE_SECRET or "").strip()
    if not secret:
        return True
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                TURNSTILE_VERIFY_URL,
                data={"secret": secret, "response": token, "remoteip": ip},
            )
            return bool(response.json().get("success"))
    except Exception as exc:  # noqa: BLE001
        log.error("Turnstile verification failed to complete: %s", exc)
        return False


class PublicLeadIn(BaseModel):
    # The public key of the form, as configured in channel_routes. Optional:
    # a single-agency install has nothing to disambiguate, and requiring a key
    # there would mean every customer must run a platform API call before their
    # own contact form works.
    form: str | None = Field(default=None, max_length=254)
    name: str | None = Field(default=None, max_length=MAX_NAME)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=MAX_MESSAGE)
    consent: bool = False
    consent_text: str | None = Field(default=None, max_length=MAX_CONSENT_TEXT)
    utm: dict[str, str] | None = None
    turnstile_token: str | None = Field(default=None, max_length=4_000)
    # Honeypot. Named for something a browser autofill would plausibly target
    # and hidden in the markup, so a human never sees it and a bot fills it in.
    website: str | None = Field(default=None, max_length=200)


@router.post("/leads", status_code=202)
async def capture(
    body: PublicLeadIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    ip = client_ip(request)

    if body.website:
        # Answer exactly like a good submission. Telling a bot it was detected
        # is free tuning feedback for whoever wrote it.
        log.info("Honeypot tripped from %s", ip)
        return {"ok": True}

    if _rate_limited(ip):
        log.warning("Rate limit refused a capture from %s", ip)
        raise HTTPException(status_code=429, detail="too_many_requests")

    if not await _turnstile_ok(body.turnstile_token, ip):
        raise HTTPException(status_code=400, detail="captcha_failed")

    try:
        org_id = await webhook_org_or_refuse(CHANNEL_WEB, body.form)
    except WebhookOrgUnresolved as exc:
        # 404, not 503. The form key is public — it ships in the landing page —
        # but the set of valid keys is not, and a distinguishable error turns
        # this endpoint into an oracle for enumerating an operator's tenants.
        log.error("refusing web capture — %s", exc)
        raise HTTPException(status_code=404, detail="unknown_form") from exc

    set_org_id(org_id)

    submission = FormSubmission(
        name=body.name,
        email=body.email,
        phone=body.phone,
        message=body.message,
        consent=body.consent,
        consent_text=body.consent_text,
        attribution=body.utm or {},
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    try:
        await capture_lead(submission, db)
    except CaptureRejected as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=exc.code) from exc
    except Exception:
        await db.rollback()
        log.exception("Web capture failed")
        raise HTTPException(status_code=500, detail="capture_failed") from None

    await db.commit()
    # Deliberately says nothing about whether the lead was new, merged or
    # duplicate: that is a membership oracle for anyone who wants to test
    # whether an address is in an agency's book.
    return {"ok": True}

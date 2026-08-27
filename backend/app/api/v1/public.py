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
    validate_submission,
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


def _ip_limited(ip: str, now: float | None = None) -> bool:
    """Charge this address for an attempt and say whether it is over budget.

    Charged for EVERY attempt that reaches it, including honeypot hits and
    submissions the captcha will reject. The budget is per address and bounded,
    so spending it on refused work costs the caller and nobody else.
    """
    stamp = time.monotonic() if now is None else now
    window = _hits.get(ip)
    if window is None:
        if len(_hits) >= MAX_TRACKED_IPS:
            # Drop the coldest tracked address rather than refuse service.
            coldest = min(_hits, key=lambda k: _hits[k][-1] if _hits[k] else 0.0)
            _hits.pop(coldest, None)
        window = _hits[ip] = deque()
    _prune(window, stamp, PER_IP_WINDOW)
    if len(window) >= PER_IP_LIMIT:
        return True
    window.append(stamp)
    return False


def _global_limited(now: float | None = None) -> bool:
    """Charge the platform-wide budget, and say whether it is exhausted.

    Deliberately charged LAST — after the honeypot, after the per-IP budget and
    after the captcha. It used to be charged first, which made it a kill switch
    anyone could hold down: sixty tokenless posts from sixty forged addresses
    were each refused with 400 and each still consumed a slot, so the captcha
    that is supposed to be the defence a script cannot outspend was bypassed
    for availability, and every agency on the install lost lead capture for ten
    minutes. Now a request only spends this budget once it has proven it is
    worth writing.
    """
    stamp = time.monotonic() if now is None else now
    _prune(_global_hits, stamp, GLOBAL_WINDOW)
    if len(_global_hits) >= GLOBAL_LIMIT:
        return True
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
    return _client_ip_parts(request)[0]


def _client_ip_parts(request: Request) -> tuple[str, bool]:
    """(address, came_from_a_proxy_header).

    The flag matters for Turnstile. When neither header is present the socket
    peer is NOT the visitor: the POST is proxied by the Next.js server through
    its `/api/*` rewrite, so `request.client.host` is the frontend container's
    address on the Docker bridge. Sending that to Cloudflare as `remoteip` is a
    classic source of spurious verification failures — the field is optional,
    and omitting it is better than asserting something false.
    """
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf[:45], True
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:45], True
    return (request.client.host if request.client else "unknown")[:45], False


async def _turnstile_ok(token: str | None, ip: str | None) -> bool:
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
    payload = {"secret": secret, "response": token}
    if ip:
        payload["remoteip"] = ip
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=payload)
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

    # No trimming validator here, deliberately, and it took writing one to find
    # out why: `services/capture.py` already normalises every field that is
    # stored — `clean_text` for name and message (which trims AND collapses
    # runs of whitespace), `normalize_email` and `normalize_phone` for the
    # other two. A validator on this model changed nothing that reached the
    # database; measured on identical POSTs, the stored row was byte-identical
    # with and without it. Code that does nothing is worse than absent: it
    # reads as coverage.
    #
    # Two fields must never acquire one, which is the part worth writing down:
    #
    # - `website` is the honeypot, tested below as `if body.website` — before
    #   the captcha and before tenant resolution. A whitespace-only value is
    #   truthy, so a bot filling the hidden field with spaces is caught today.
    #   Trimming it to None would wave that bot straight through.
    # - `consent_text` reaches `clean_text` like the rest, so it is already
    #   collapsed rather than stored verbatim. Worth knowing before anyone
    #   relies on it reading back exactly as the person saw it.


@router.post("/leads", status_code=202)
async def capture(
    body: PublicLeadIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    ip, ip_is_from_a_proxy_header = _client_ip_parts(request)

    # ── Order matters, and each step is placed for a reason ──────────────
    # 1. Per-IP budget first, charged even for the honeypot. It used to sit
    #    AFTER the honeypot branch, so `{"website": "bot"}` was an unmetered
    #    endpoint: two hundred consecutive posts all answered 202 and left
    #    every counter untouched.
    if _ip_limited(ip):
        log.warning("Rate limit refused a capture from %s", ip)
        raise HTTPException(status_code=429, detail="too_many_requests")

    if body.website:
        # Answer exactly like a good submission. Telling a bot it was detected
        # is free tuning feedback for whoever wrote it.
        log.info("Honeypot tripped from %s", ip)
        return {"ok": True}

    # 2. Shape of the submission, BEFORE the tenant is resolved. A probe with
    #    no email and no phone used to return 422 for a live form key and 404
    #    for a dead one, which made this a quiet enumeration oracle: unlike a
    #    202 probe it writes no lead, so a scan left no trace anywhere the
    #    operator looks. Same answer now regardless of the key.
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
        validate_submission(submission)
    except CaptureRejected as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc

    # A lead we cannot reach is not a lead. Every field on this form is optional,
    # which was correct while there were two automatic channels; SMS is not one
    # of them today (Twilio accepts and the carrier drops it — error 30034,
    # measured), so a phone-only submission produces a row nobody can answer.
    # Refusing it in front of the person, while they are still on the page and
    # can add an address, is better than accepting it and going quiet.
    #
    # After the captcha check would be wrong: this costs nothing to evaluate and
    # tells an honest visitor what to fix, whereas a bot never gets this far.
    if get_settings().CAPTURE_REQUIRE_EMAIL and not (submission.email or "").strip():
        raise HTTPException(status_code=422, detail="email_required")

    # 3. Captcha before the global budget is touched. A request the captcha
    #    will refuse must not be able to spend a slot: that turned the ceiling
    #    into a kill switch anyone could hold down without solving anything.
    if not await _turnstile_ok(
        body.turnstile_token, ip if ip_is_from_a_proxy_header else None
    ):
        raise HTTPException(status_code=400, detail="captcha_failed")

    # 4. The platform-wide budget, charged BEFORE the tenant lookup rather than
    #    after it. Resolving a form key is a database round trip, and with the
    #    charge at the end a caller rotating the IP header could drive an
    #    unbounded number of them: the per-IP budget resets with every forged
    #    address, so nothing counted the work. Charging here means the ceiling
    #    bounds real work, not just successful writes.
    if _global_limited():
        log.error(
            "Global capture ceiling reached — lead capture is refused for "
            "every agency until the window clears. If this is not a flood, "
            "raise GLOBAL_LIMIT; if it is, configure TURNSTILE_SECRET."
        )
        raise HTTPException(status_code=429, detail="too_many_requests")

    try:
        org_id = await webhook_org_or_refuse(
            CHANNEL_WEB,
            body.form,
            # A key that was supplied must match a route. Without this, an
            # agency offboarded the ordinary way — suspend, delete routes —
            # leaves a live landing page whose submissions get filed into
            # whichever agency remains.
            fallback_when_unmapped=not body.form,
        )
    except WebhookOrgUnresolved as exc:
        # 404, not 503. The form key is public — it ships in the landing page —
        # but the set of valid keys is not, and a distinguishable error turns
        # this endpoint into an oracle for enumerating an operator's tenants.
        log.error("refusing web capture — %s", exc)
        raise HTTPException(status_code=404, detail="unknown_form") from exc

    set_org_id(org_id)

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

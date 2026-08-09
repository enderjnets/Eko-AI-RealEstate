"""Per-user engagement tracking — aggregate-only, keyed by session email.

A lightweight middleware calls `record_request` on each authenticated /api/v1
request; the login endpoints call `record_login`. Everything is best-effort: a
failure here must never break the actual request (the caller swallows errors).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import DEFAULT_ORG_ID
from app.services.tenant_context import get_org_id

log = logging.getLogger(__name__)

# First path segment after /api/v1/ → the dashboard section it belongs to.
_SECTION_MAP = {
    "leads": "leads",
    "conversations": "leads",
    "inbox": "inbox",
    "visits": "calendar",
    "properties": "properties",
    "analytics": "analytics",
    "discovery": "discovery",
    "settings": "settings",
    "team": "settings",
}


def section_for_path(path: str) -> str | None:
    """Map an /api/v1/<seg>/... path to a section key (or None if not tracked)."""
    parts = [p for p in path.split("/") if p]
    # parts like ["api", "v1", "<seg>", ...]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
        return _SECTION_MAP.get(parts[2])
    return None


def parse_device(ua: str | None) -> str | None:
    """Best-effort 'Browser · OS' label from a User-Agent string."""
    if not ua:
        return None
    u = ua.lower()
    if "edg/" in u or "edge" in u:
        browser = "Edge"
    elif "chrome" in u and "chromium" not in u:
        browser = "Chrome"
    elif "firefox" in u:
        browser = "Firefox"
    elif "safari" in u:
        browser = "Safari"
    else:
        browser = "Browser"
    if "iphone" in u:
        os_name = "iPhone"
    elif "ipad" in u:
        os_name = "iPad"
    elif "android" in u:
        os_name = "Android"
    elif "mac os x" in u or "macintosh" in u:
        os_name = "macOS"
    elif "windows" in u:
        os_name = "Windows"
    elif "linux" in u:
        os_name = "Linux"
    else:
        os_name = "Unknown OS"
    return f"{browser} · {os_name}"


def client_ip(request) -> str | None:
    """Best client IP behind the Cloudflare tunnel / proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else None


async def _get_or_create(
    db: AsyncSession, email: str, source: str | None, org_id: int | None = None
):
    """Find or create this user's activity row, always inside one organization.

    `org_id` is passed explicitly because the login endpoints call this on a
    bypass session, where nothing is bound and nothing gets stamped. Without it
    the lookup matched on email alone across every tenant: a self-registered
    viewer's telemetry was filed under client zero, and an org-1 login could
    overwrite an org-2 user's last IP and device — which their admin then saw in
    their own activity panel.
    """
    from app.models import UserActivity

    effective_org = org_id or get_org_id() or DEFAULT_ORG_ID
    row = (
        await db.execute(
            select(UserActivity).where(
                UserActivity.email == email, UserActivity.org_id == effective_org
            )
        )
    ).scalar_one_or_none()
    if row is None:
        now = datetime.now(UTC)
        # org_id explicit rather than relying on the before_flush stamp: this
        # also runs from the login endpoints, which use a bypass session (there
        # is no org bound until the user is identified) and so are not stamped.
        row = UserActivity(
            email=email,
            source=source,
            first_seen=now,
            last_seen=now,
            sections={},
            org_id=effective_org,
        )
        db.add(row)
        await db.flush()
    elif source and not row.source:
        row.source = source
    return row


def _bump_active_day(row, now: datetime) -> None:
    today = now.date()
    if row.last_active_day != today:
        row.active_days = (row.active_days or 0) + 1
        row.last_active_day = today


async def record_request(
    db: AsyncSession,
    *,
    email: str,
    source: str | None,
    path: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Upsert the user's activity row for one authenticated request."""
    now = datetime.now(UTC)
    row = await _get_or_create(db, email, source)
    row.last_seen = now
    row.request_count = (row.request_count or 0) + 1
    if ip:
        row.last_ip = ip
    if user_agent:
        row.last_user_agent = user_agent[:400]
        row.device = parse_device(user_agent)
    section = section_for_path(path)
    if section:
        s = dict(row.sections or {})
        s[section] = s.get(section, 0) + 1
        row.sections = s  # reassign so SQLAlchemy tracks the JSON change
    _bump_active_day(row, now)
    await db.commit()


async def record_login(
    db: AsyncSession,
    *,
    email: str,
    source: str | None,
    ip: str | None = None,
    user_agent: str | None = None,
    org_id: int | None = None,
) -> None:
    """Increment login_count + refresh last_seen on a successful login."""
    now = datetime.now(UTC)
    row = await _get_or_create(db, email, source, org_id)
    row.login_count = (row.login_count or 0) + 1
    row.last_seen = now
    if ip:
        row.last_ip = ip
    if user_agent:
        row.last_user_agent = user_agent[:400]
        row.device = parse_device(user_agent)
    _bump_active_day(row, now)
    await db.commit()

"""Turning a browser beacon into a row somebody can read.

Everything here that classifies is a pure function over strings, so the rules
are testable without a database and without a browser. The one function that
touches the database is the purge at the bottom.

The classification is deliberately coarse. `device` has four values, `browser`
and `os` are families, and the raw user agent is never stored — a user agent
string is close enough to an identifier that keeping it would undo the point of
not setting a cookie. What a report needs is "phones outnumber desktops four to
one", and that survives the reduction intact.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import bindparam, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.landing import LANDING_SECTIONS, LandingEvent, LandingSession

log = logging.getLogger(__name__)

# How much of any single free-text value ever reaches the database. The columns
# are Text so nothing can 500 on length; this is what keeps a hostile beacon
# from writing a megabyte one field at a time.
MAX_VALUE = 200

_SOURCE_BY_HOST: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|\.)youtube\.com$|(^|\.)youtu\.be$"), "youtube"),
    (re.compile(r"(^|\.)tiktok\.com$"), "tiktok"),
    (re.compile(r"(^|\.)instagram\.com$"), "instagram"),
    (re.compile(r"(^|\.)facebook\.com$|(^|\.)fb\.com$|(^|\.)fb\.me$"), "facebook"),
    (re.compile(r"(^|\.)google\.[a-z.]+$"), "google"),
    (re.compile(r"(^|\.)bing\.com$|(^|\.)duckduckgo\.com$|(^|\.)search\.yahoo\.com$"), "search"),
)

# The names a UTM may carry for each of our own channels. Anything else that
# arrives as utm_source is kept verbatim on the row and classified as `other`,
# so a campaign we did not anticipate is counted rather than discarded.
_SOURCE_BY_UTM: dict[str, str] = {
    "youtube": "youtube",
    "yt": "youtube",
    "youtube_shorts": "youtube",
    "shorts": "youtube",
    "tiktok": "tiktok",
    "tt": "tiktok",
    "instagram": "instagram",
    "ig": "instagram",
    "facebook": "facebook",
    "fb": "facebook",
    "meta": "facebook",
    "google": "google",
    "bing": "search",
    "email": "email",
    "newsletter": "email",
    "direct": "direct",
}

_IN_APP = (
    (re.compile(r"instagram", re.I), "instagram"),
    (re.compile(r"bytedancewebview|musical_ly|tiktok|aweme", re.I), "tiktok"),
    (re.compile(r"\bfban|\bfbav|\bfb_iab", re.I), "facebook"),
)


def clip(value: Any, limit: int = MAX_VALUE) -> str | None:
    """A trimmed string of at most `limit` characters, or None if empty."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:limit]


def referrer_host_of(url: str | None) -> str | None:
    """The bare host a referrer points at, lowercased and without `www.`.

    Android's in-app browsers hand over `android-app://com.google.android.youtube`
    rather than an https URL, which `urlsplit` parses into a netloc-less shape.
    Mapping those back to the site they mean is the difference between counting
    a YouTube visit and filing it under `direct`.
    """
    raw = clip(url, 500)
    if raw is None:
        return None
    if raw.startswith("android-app://"):
        package = raw[len("android-app://") :].strip("/").lower()
        return {
            "com.google.android.youtube": "youtube.com",
            "com.zhiliaoapp.musically": "tiktok.com",
            "com.ss.android.ugc.trill": "tiktok.com",
            "com.instagram.android": "instagram.com",
            "com.facebook.katana": "facebook.com",
        }.get(package)
    try:
        host = urlsplit(raw).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def source_of(utm_source: str | None, referrer_host: str | None) -> str:
    """Which channel sent this visit.

    A UTM wins over the referrer because it is the thing we put on the link
    ourselves; the referrer is a fallback for the platforms that strip query
    parameters. When there is neither, `direct` — which on this site mostly
    means somebody typed the domain after hearing it in a video, so it is a
    real answer and not a gap.
    """
    tag = (utm_source or "").strip().lower()
    if tag:
        return _SOURCE_BY_UTM.get(tag, "other")
    if not referrer_host:
        return "direct"
    for pattern, name in _SOURCE_BY_HOST:
        if pattern.search(referrer_host):
            return name
    return "other"


def device_of(user_agent: str | None) -> str:
    ua = user_agent or ""
    if not ua:
        return "unknown"
    if re.search(r"ipad|tablet|playbook|silk", ua, re.I):
        return "tablet"
    if re.search(r"android", ua, re.I) and not re.search(r"mobile", ua, re.I):
        # Android without "Mobile" is the tablet form factor, per Google's own
        # convention. Checked after the explicit tablet words above.
        return "tablet"
    if re.search(r"mobi|iphone|ipod|android|windows phone", ua, re.I):
        return "phone"
    if re.search(r"mac os|windows|linux|cros", ua, re.I):
        return "desktop"
    return "unknown"


def browser_of(user_agent: str | None) -> str | None:
    ua = user_agent or ""
    if not ua:
        return None
    # Order matters: every one of these ships "Safari" in its token list, and
    # most ship "Chrome" too, so the specific names have to be tested first.
    for pattern, name in (
        (r"edg[ea]?/", "Edge"),
        (r"opr/|opera", "Opera"),
        (r"samsungbrowser", "Samsung Internet"),
        (r"firefox|fxios", "Firefox"),
        (r"crios|chrome|chromium", "Chrome"),
        (r"safari", "Safari"),
    ):
        if re.search(pattern, ua, re.I):
            return name
    return None


def os_of(user_agent: str | None) -> str | None:
    ua = user_agent or ""
    if not ua:
        return None
    for pattern, name in (
        (r"iphone|ipad|ipod|ios", "iOS"),
        (r"android", "Android"),
        (r"mac os|macintosh", "macOS"),
        (r"windows", "Windows"),
        (r"cros", "ChromeOS"),
        (r"linux", "Linux"),
    ):
        if re.search(pattern, ua, re.I):
            return name
    return None


def in_app_of(user_agent: str | None) -> str | None:
    """The social app whose embedded browser this is, if it is one."""
    ua = user_agent or ""
    for pattern, name in _IN_APP:
        if pattern.search(ua):
            return name
    return None


def geo_of(headers: Mapping[str, str]) -> tuple[str | None, str | None, str | None]:
    """Country, region and city as Cloudflare saw them.

    Only the country header is on by default; region and city need the "Add
    visitor location headers" managed transform switched on for the zone, so
    they are absent until somebody clicks it — which is why every one of them
    is nullable and no report may assume them.

    `XX` and `T1` are Cloudflare's own placeholders for "unknown" and "Tor
    exit"; stored as-is they would show up as a country in every breakdown.
    """
    def _one(name: str) -> str | None:
        value = clip(headers.get(name), 80)
        if value is None or value.upper() in {"XX", "T1"}:
            return None
        return value

    return _one("cf-ipcountry"), _one("cf-region-code"), _one("cf-ipcity")


@dataclass(frozen=True)
class SessionDelta:
    """What one batch of beacons adds to a session row.

    A value, not a mutation, and that is the whole reason this shape exists.
    The counters used to be folded into a loaded ORM object and written back,
    which is a read-modify-write: two beacons for the same visit — and there
    always are two, since `sendBeacon` fires on both `visibilitychange` and
    `pagehide` — each read the same starting values and the second overwrote
    the first. Clicks were lost, and `max_scroll_pct` could go DOWN, which is
    exactly what this module promises cannot happen.

    Computed here, applied by the caller as one UPDATE of SQL expressions
    (`count + :n`, `GREATEST(...)`, `COALESCE(...)`), so the database resolves
    the concurrency instead of the process.
    """

    events: int
    cta_clicks: int
    tel_clicks: int
    max_scroll_pct: int | None
    sections: list[str]
    form_started: bool
    form_submitted: bool


def fold_events(events: Sequence[tuple[str, dict[str, Any]]]) -> SessionDelta:
    """Reduce a batch to the single delta it represents."""
    cta = tel = 0
    scroll: int | None = None
    sections: list[str] = []
    started = submitted = False

    for kind, meta in events:
        if kind == "scroll":
            pct = meta.get("pct")
            if isinstance(pct, int) and not isinstance(pct, bool) and 0 <= pct <= 100:
                scroll = pct if scroll is None else max(scroll, pct)
        elif kind == "section_view":
            section = meta.get("section")
            if section in LANDING_SECTIONS and section not in sections:
                sections.append(section)
        elif kind == "cta_click":
            cta += 1
        elif kind == "tel_click":
            tel += 1
        elif kind == "form_start":
            started = True
        elif kind == "form_submit":
            # Recorded on the session even though the lead POST sets it too.
            # The two disagreeing is the interesting case: `form_submitted_at
            # IS NOT NULL AND lead_id IS NULL` is "they pressed send and no
            # lead ever arrived" — a captcha refusal, a dropped connection — 
            # which is invisible if only the successful path writes it.
            submitted = True

    return SessionDelta(
        events=len(events),
        cta_clicks=cta,
        tel_clicks=tel,
        max_scroll_pct=scroll,
        sections=sections,
        form_started=started,
        form_submitted=submitted,
    )


def merge_values(delta: SessionDelta, now: datetime) -> dict[str, Any]:
    """The `UPDATE ... SET` mapping that applies `delta` atomically.

    Every entry is an expression over the row's current value, never a Python
    computation of it. `sections_viewed` becomes the sorted union of what was
    there and what arrived: sorted rather than first-seen because a set is what
    the reporting needs and an aggregate's order is not guaranteed anyway.
    """
    values: dict[str, Any] = {
        "last_seen_at": now,
        "event_count": LandingSession.event_count + delta.events,
    }
    if delta.cta_clicks:
        values["cta_clicks"] = LandingSession.cta_clicks + delta.cta_clicks
    if delta.tel_clicks:
        values["tel_clicks"] = LandingSession.tel_clicks + delta.tel_clicks
    if delta.max_scroll_pct is not None:
        values["max_scroll_pct"] = func.greatest(
            LandingSession.max_scroll_pct, delta.max_scroll_pct
        )
    if delta.form_started:
        values["form_started_at"] = func.coalesce(LandingSession.form_started_at, now)
    if delta.form_submitted:
        values["form_submitted_at"] = func.coalesce(LandingSession.form_submitted_at, now)
    if delta.sections:
        values["sections_viewed"] = text(
            "(SELECT COALESCE(jsonb_agg(DISTINCT s ORDER BY s), '[]'::jsonb) "
            "FROM jsonb_array_elements("
            "landing_sessions.sections_viewed || CAST(:new_sections AS jsonb)) AS s)"
        ).bindparams(bindparam("new_sections", json.dumps(delta.sections)))
    return values


def new_events(
    org_id: int,
    session_id: int,
    events: Sequence[tuple[str, dict[str, Any]]],
    now: datetime,
) -> list[LandingEvent]:
    """The raw rows for a batch. `org_id` is passed in from the session's own
    row, never re-derived, so the two tables cannot disagree about whose visit
    this was."""
    return [
        LandingEvent(org_id=org_id, session_id=session_id, type=kind, at=now, meta=meta or None)
        for kind, meta in events
    ]


async def purge_landing_events(db: AsyncSession) -> int:
    """Delete raw events past the retention window; keep every session.

    The sessions are the record — they carry the same facts already merged —
    so this bounds the table that grows per interaction without changing a
    single number any report has ever shown. What bounds the SESSION table is
    the per-day cap in the endpoint, not a purge: deleting sessions by age
    would silently rewrite the denominator of every historical funnel.

    The `org_id` predicate is redundant under RLS and deliberate anyway: with
    `DATABASE_URL_APP` unset the app falls back to a connection that may bypass
    policies entirely, and a sweep meant for one agency would then delete every
    agency's rows.
    """
    from app.config import get_settings
    from app.services.tenant_context import get_org_id

    org_id = get_org_id()
    if org_id is None:
        # Nothing bound: under default-deny this would match nothing anyway,
        # and under a bypass connection it would match everything.
        log.warning("Landing purge skipped — no organization is bound")
        return 0

    days = max(1, get_settings().LANDING_EVENTS_RETENTION_DAYS)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        delete(LandingEvent).where(
            LandingEvent.org_id == org_id, LandingEvent.at < cutoff
        )
    )
    deleted = result.rowcount or 0
    # Committed either way: an open write transaction left for the session to
    # roll back is what the zero-row case used to leave behind on every tick.
    await db.commit()
    if deleted:
        log.info("Purged %d landing events older than %d days", deleted, days)
    return deleted

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

from sqlalchemy import and_, bindparam, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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

_AUTOMATED_USER_AGENTS: tuple[tuple[str, str], ...] = (
    ("headlesschrome", "ua_headless_chrome"),
    ("googlebot", "ua_googlebot"),
    ("bingbot", "ua_bingbot"),
    ("facebookexternalhit", "ua_facebookexternalhit"),
    ("lighthouse", "ua_lighthouse"),
    ("curl", "ua_curl"),
    ("wget", "ua_wget"),
    ("python-requests", "ua_python_requests"),
    ("bytespider", "ua_bytespider"),
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


def classify_traffic(
    user_agent: str | None,
    webdriver: bool,
    attribution: dict[str, str],
    qa_device: bool = False,
) -> tuple[str, str | None]:
    source = attribution.get("utm_source")
    medium = attribution.get("utm_medium")
    if source == "eko_qa" and medium == "test":
        return "test", "explicit_qa"
    # A browser that told us it is ours, and keeps telling us on every later
    # visit. First, because it is the only claim here somebody made on purpose:
    # the QA UTM above says "this link is a test", this says "this device is",
    # and our own devices reach the page by ordinary links most of the time.
    if qa_device:
        return "test", "persistent_qa"
    if webdriver:
        return "automated", "webdriver"

    normalized_user_agent = (user_agent or "").lower()
    for signature, reason in _AUTOMATED_USER_AGENTS:
        if signature in normalized_user_agent:
            return "automated", reason
    return "unknown", None


# How close to its own publication a visit has to land before arriving there by
# watching the video stops being a possible explanation.
PUBLISH_PREVIEW_SECONDS = 90

# How long a visit is left alone before its silence is taken as an answer. A
# real reader can sit on the first screen for a while — the tracker records
# nothing until they scroll — and judging them at the moment the beacon lands
# would file every slow reader as a machine.
SETTLED_MINUTES = 60


# Two checkers following the same link arrive within a second of each other;
# the widest real gap on record is 21 seconds, and the batch that produced it
# spanned eight minutes overall. A minute is wide enough for a slow one and
# far too narrow for two people who happened to watch the same short.
PAIRED_CHECK_SECONDS = 60

# How far back the pairing looks. The sweep runs every five minutes, so a row
# is judged within the hour of settling and this only ever excludes rows a long
# outage left behind. It is here because nothing purges `landing_sessions` and
# the join is quadratic inside each campaign: without a floor, every row ever
# recorded would be compared against every other one, for ever, on every tick.
PAIRED_CHECK_LOOKBACK_DAYS = 30



def is_publish_preview(gap_seconds: float | None, event_count: int) -> bool:
    """Whether a visit is the network fetching its own link preview.

    When a post goes out, the network renders the link in a real browser to
    build the preview card. That browser runs our JavaScript, so it writes a
    `landing_sessions` row like anybody else — and it does not announce itself
    in the user agent, which is why `classify_traffic` lets it through. What
    gives it away is the clock: measured in production on 15-sep-2026, nine of
    these landed between **one and thirty-one seconds** after the publication
    they were tagged with, in pairs, from Clonee and Boardman (AWS Ireland and
    AWS Oregon). Nobody watches a video and clicks through in one second.

    Two conditions, and the second is what keeps this honest. The window alone
    would also catch the first real viewer of a post that happens to land fast,
    so the visit must ALSO have done nothing at all — one `page_view`, no
    scroll, no click. A person who arrives in that window and then reads is
    left alone. Control on the same data: of every session inside the window,
    exactly one had done anything, and it keeps its `unknown`.

    The gap is taken as an absolute value because a platform fetches the link
    when the post is created, which can be a few seconds before we stamp
    `published_at` — and because one piece publishes to three channels at
    slightly different times, so the nearest of them is the honest reference.
    """
    if gap_seconds is None:
        return False
    if event_count > 1:
        return False
    return abs(gap_seconds) <= PUBLISH_PREVIEW_SECONDS


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
    form_errors: int
    max_scroll_pct: int | None
    sections: list[str]
    form_started: bool
    form_submitted: bool


def fold_events(events: Sequence[tuple[str, dict[str, Any]]]) -> SessionDelta:
    """Reduce a batch to the single delta it represents."""
    cta = tel = errors = 0
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
        elif kind == "form_error":
            # Contado, no colapsado a un booleano: quien se estrella tres veces
            # y se va no es quien se estrella una y lo consigue. Se guardaba en
            # `landing_events` desde siempre y no lo leia nadie — el unico
            # fallo del embudo que no aparecia en ninguna pantalla.
            errors += 1
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
        form_errors=errors,
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
    if delta.form_errors:
        values["form_error_count"] = (
            LandingSession.form_error_count + delta.form_errors
        )
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


async def classify_publish_previews(db: AsyncSession) -> int:
    """Mark the visits that were a network fetching its own link preview.

    This runs after the fact, and it has to: at the moment the beacon arrives
    the row is one `page_view` old and indistinguishable from a person who has
    not scrolled yet. `SETTLED_MINUTES` is how long that person is given.

    It only ever writes over `unknown`. A row already called `test` or
    `automated` was decided by something that knew more — the explicit QA
    marker, `navigator.webdriver`, a user agent that named itself — and this
    rule is the weakest evidence of the three.
    """
    from app.models.content import ContentPublication
    from app.services.tenant_context import get_org_id

    org_id = get_org_id()
    if org_id is None:
        log.warning("Landing classification skipped — no organization is bound")
        return 0

    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES)
    gap = func.abs(
        func.extract(
            "epoch", LandingSession.first_seen_at - ContentPublication.published_at
        )
    )
    candidates = (
        await db.execute(
            select(LandingSession.id)
            .join(
                ContentPublication,
                and_(
                    ContentPublication.org_id == org_id,
                    ContentPublication.published_at.is_not(None),
                    LandingSession.utm_content
                    == func.concat("piece-", ContentPublication.piece_id),
                    gap <= PUBLISH_PREVIEW_SECONDS,
                ),
            )
            .where(
                LandingSession.org_id == org_id,
                LandingSession.traffic_class == "unknown",
                LandingSession.event_count <= 1,
                LandingSession.last_seen_at < settled,
            )
            # One piece publishes to three channels, so the same session joins
            # up to three publication rows. Without this it would be updated
            # three times and counted three times.
            .distinct()
        )
    ).scalars().all()

    if not candidates:
        return 0

    await db.execute(
        update(LandingSession)
        .where(LandingSession.org_id == org_id, LandingSession.id.in_(candidates))
        .values(
            traffic_class="automated",
            traffic_class_reason="publish_preview",
            traffic_classified_at=datetime.now(UTC),
        )
    )
    await db.commit()
    log.info("Classified %d landing session(s) as publish previews", len(candidates))
    return len(candidates)


async def classify_paired_link_checks(db: AsyncSession) -> int:
    """Mark the visits that were two machines fetching the same link at once.

    A link posted or edited on a platform is fetched by several checkers within
    seconds, each from a different egress point, and each arrives here as a
    separate session in a separate city. Measured on the live rail, twice:
    sixteen rows on 16-sep after descriptions were edited, and ten rows on
    15-sep between 21:59 and 22:07 UTC on five videos published ten days
    earlier. The trigger is not recorded anywhere — those edits are made by
    hand in YouTube Studio — so the signature is what carries this, not a log.

    **Different cities is the whole rule**, and it is why this is not
    `one_shot_no_scroll` under another name. One person opening a link twice is
    one city; two people in two cities opening the same link inside a minute,
    both bouncing without scrolling, touching nothing and filling nothing, is
    not two people. The sharpest pair on record is 24 MILLISECONDS apart, New
    York and Denver, on the same video.

    And it is why there is no list of cities here. Denver appears in that pair,
    and a rule that excused it by name would be blind exactly where a machine
    room with a Denver address is. The two real Denver visits in the same range
    fall outside on their own terms: one carries no UTM, the other scrolled.

    Like its neighbours, it only ever writes over `unknown`.
    """
    from app.services.tenant_context import get_org_id

    org_id = get_org_id()
    if org_id is None:
        log.warning("Paired link-check sweep skipped — no organization is bound")
        return 0

    now = datetime.now(UTC)
    settled = now - timedelta(minutes=SETTLED_MINUTES)
    lookback = now - timedelta(days=PAIRED_CHECK_LOOKBACK_DAYS)
    other = aliased(LandingSession)

    def _did_nothing(row):
        return (
            func.coalesce(row.max_scroll_pct, 0) == 0,
            row.cta_clicks == 0,
            row.tel_clicks == 0,
            row.form_started_at.is_(None),
            # A session attached to a LEAD is never a machine, whatever the
            # rest of its row says — and it can look exactly like one. The
            # public capture endpoint creates a session row for a form post
            # that carries a key the beacon never registered, which happens
            # whenever a content blocker eats the tracking call and lets the
            # form through. That row is born with no scroll, no clicks and no
            # form_started_at, and it carries the campaign of the link the
            # person followed — so a link checker fetching the same link from
            # another city within the minute would have taken the two of them
            # down together. A false `automated` throws away the only kind of
            # row that matters.
            row.lead_id.is_(None),
            # And the row where the two disagree: `merge_values` writes
            # form_submitted_at from the beacon's own form_submit event, so
            # "pressed send and no lead ever arrived" — a captcha refusal, a
            # dropped connection — is a row with a submission and no lead. It
            # has nothing else to distinguish it from a checker.
            row.form_submitted_at.is_(None),
            row.traffic_class == "unknown",
            row.last_seen_at < settled,
            # Not indexable — the time test is between two rows, not against a
            # constant — so this is the one predicate that keeps the join from
            # growing without limit. Sessions are never purged, and without a
            # floor a row from September 2026 would be re-paired against every
            # other row every five minutes for ever.
            row.first_seen_at > lookback,
            row.org_id == org_id,
            row.city.is_not(None),
        )

    candidates = (
        await db.execute(
            select(LandingSession.id)
            .join(
                other,
                and_(
                    # Both halves are marked, so the join is written once and
                    # read from either side rather than `a.id < b.id`.
                    other.id != LandingSession.id,
                    other.utm_source == LandingSession.utm_source,
                    other.utm_content == LandingSession.utm_content,
                    # NULL never equals NULL in SQL, so a session with no
                    # campaign can never pair — which is right: without a link
                    # there is nothing for a checker to have followed.
                    LandingSession.utm_source.is_not(None),
                    LandingSession.utm_content.is_not(None),
                    other.city != LandingSession.city,
                    func.abs(
                        func.extract(
                            "epoch",
                            LandingSession.first_seen_at - other.first_seen_at,
                        )
                    )
                    <= PAIRED_CHECK_SECONDS,
                    *_did_nothing(other),
                ),
            )
            .where(*_did_nothing(LandingSession))
            # A link fetched by three checkers pairs each row with two others.
            .distinct()
        )
    ).scalars().all()

    if not candidates:
        return 0

    await db.execute(
        update(LandingSession)
        .where(LandingSession.org_id == org_id, LandingSession.id.in_(candidates))
        .values(
            traffic_class="automated",
            traffic_class_reason="paired_link_check",
            traffic_classified_at=datetime.now(UTC),
        )
    )
    await db.commit()
    log.info("Classified %d landing session(s) as paired link checks", len(candidates))
    return len(candidates)


async def classify_datacenter_visits(db: AsyncSession) -> int:
    """Mark the visits that came from a machine room and did nothing.

    Two conditions, and the second is what keeps this honest.

    **A data-centre city.** `datacenter_cities.py` carries the list and the
    evidence for every entry. It is deliberately short, and deliberately
    excludes Dublin, San Jose, Chicago and every other place that is a real
    city as well as a cloud region.

    **And zero scroll.** Not "little" — none. A machine that renders the page
    to build a link preview never scrolls; a person who happens to be sitting
    in Ashburn does. This is what lets Ashburn stay on the list at all, and it
    is why Boydton is not on it: four visits from there scrolled to 100%, so
    whatever they are, they are not this.

    The asymmetry behind both: the operation has **zero leads**, so a false
    `automated` discards the only kind of row that matters, while a false
    `unknown` only makes a denominator noisier. When the evidence is thin, the
    row keeps `unknown`.

    Like the preview sweep, it runs after the fact and only ever writes over
    `unknown`. A row already called `test` or `automated` was decided by
    something that knew more.

    ── What this deliberately does NOT do ──────────────────────────────────
    The plan that asked for this also asked for a second rule: one event and
    zero scroll, anywhere, filed as `automated`. That rule was measured before
    being written, and it was **not** implemented. Of the sessions it would
    have caught, about thirty-six are Denver-area cities — Aurora, Denver,
    Parker, The Pinery, Wheat Ridge — and **thirteen of those arrived inside
    the Facebook app**, which no crawler and none of our own tooling does.

    What they are cannot be settled. Some are very likely us: before the
    `?eko_qa=1` marker existed there was no way to tell our own browsers from
    a stranger's, and we are in the same metro area. Others, the in-app ones
    especially, came from the 11-sep share. That uncertainty is the argument:
    `unknown` is the honest label for a row nobody can identify, and filing it
    as `automated` would launder a guess into a fact — one that makes the
    30-sep re-evaluation read better than the truth. The metric that matters
    already excludes them by requiring scroll >= 50%, so the rule would have
    cost the diagnosis and bought nothing.
    """
    from app.services.datacenter_cities import DATACENTER_CITIES
    from app.services.tenant_context import get_org_id

    org_id = get_org_id()
    if org_id is None:
        log.warning("Datacenter classification skipped — no organization is bound")
        return 0

    now = datetime.now(UTC)
    settled = now - timedelta(minutes=SETTLED_MINUTES)
    result = await db.execute(
        update(LandingSession)
        .where(
            LandingSession.org_id == org_id,
            LandingSession.traffic_class == "unknown",
            LandingSession.city.is_not(None),
            func.lower(func.trim(LandingSession.city)).in_(sorted(DATACENTER_CITIES)),
            func.coalesce(LandingSession.max_scroll_pct, 0) == 0,
            LandingSession.last_seen_at < settled,
        )
        .values(
            traffic_class="automated",
            traffic_class_reason="datacenter_city",
            traffic_classified_at=now,
        )
    )
    await db.commit()
    changed = result.rowcount or 0
    if changed:
        log.info("Classified %d landing session(s) as data-centre visits", changed)
    return changed


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

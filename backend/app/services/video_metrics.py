"""How many people watched each published video.

The funnel starts at the landing page, which means a video that reached four
people and a video that reached four thousand and persuaded nobody look
identical from inside the product. They are opposite problems needing opposite
fixes — make better videos, or fix the page — and telling them apart needs a
number from outside.

**Only YouTube can be read by a machine.** Its `videos.list` endpoint serves the
public counters of any public video to a plain API key: no OAuth, no channel
ownership, no review. TikTok and Instagram publish nothing comparable — their
APIs hand view counts only to a first-party app that has passed platform
review, which is a project, not a call — so those numbers are typed by hand
from the console and stored with `source="manual"` so nobody later mistakes an
estimate for a measurement.

The module is deliberately **not** named `content_*`. `test_content_gate_is_absolute`
sweeps files whose name contains `content` looking for anything that writes a
piece's status, and this writes no status; a name that drags it into that sweep
would make a passing test mean something other than what it says.

Nothing here raises. A quota refusal, a deleted video, a key someone typo'd —
each is a day without a reading, which is a gap in a chart. Turning any of them
into an exception would take down a background loop that also has nothing to do
with them.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AgentSettings,
    ContentMetric,
    ContentPublication,
    PublicationPlatform,
    PublicationStatus,
)
from app.services.tenant_context import get_org_id

log = logging.getLogger(__name__)

DEFAULT_TZ = "America/Denver"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3/videos"

# YouTube accepts up to 50 ids in one call, and one call costs one quota unit
# whether it carries 1 id or 50. Batching is not an optimisation here, it is the
# difference between 4 units a day and 200.
BATCH = 50

# The four shapes a YouTube address takes in the wild. `/shorts/` is the one
# that matters most for us — everything this agency publishes is a Short, and
# the reconciliation stores exactly what Buffer reports, which for our own first
# published video was `https://www.youtube.com/shorts/iUThdDk6zBY`.
_ID = r"([A-Za-z0-9_-]{11})"
_PATTERNS = (
    re.compile(rf"[?&]v={_ID}"),
    re.compile(rf"/shorts/{_ID}"),
    re.compile(rf"youtu\.be/{_ID}"),
    re.compile(rf"/embed/{_ID}"),
)


def youtube_video_id(url: str | None) -> str | None:
    """The 11-character id inside a YouTube address, or `None`.

    `None` for a TikTok link, an Instagram link, an empty column, or a YouTube
    URL in a shape we do not know. Returning `None` rather than guessing is what
    keeps a wrong id out of a batch: YouTube answers a request for an unknown id
    with a 200 and no item, so a bad guess would look exactly like a deleted
    video and be recorded as "no data" for ever.
    """
    if not url:
        return None
    for pattern in _PATTERNS:
        found = pattern.search(url)
        if found:
            return found.group(1)
    return None


def _count(stats: dict, key: str) -> int | None:
    """One public counter, or `None` when the platform did not publish it.

    Every value in YouTube's `statistics` is a **string**, and keys go missing
    rather than arriving as zero: `likeCount` is absent when a channel hides
    likes, `commentCount` when comments are off. `int()` on a missing key would
    raise inside a loop whose whole job is to keep ticking, and a default of `0`
    would say "nobody liked it" when the truth is "the platform did not say".
    """
    raw = stats.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def fetch_youtube_stats(
    ids: list[str], key: str
) -> dict[str, dict[str, int | None]]:
    """Public counters for up to 50 video ids, keyed by id.

    An id that is missing from the result is missing from the answer — a video
    that was deleted or made private comes back as a 200 with an empty `items`,
    which is "no data for this id", not a failure of the call.
    """
    if not ids or not key:
        return {}
    out: dict[str, dict[str, int | None]] = {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                YOUTUBE_API,
                params={
                    "part": "statistics",
                    "id": ",".join(ids[:BATCH]),
                    "key": key,
                },
            )
        if response.status_code != 200:
            # 403 is the quota wall and also what a key restricted to HTTP
            # referrers returns to a server. Both are the operator's to fix and
            # neither is worth an exception in a background loop.
            log.warning(
                "YouTube stats refused (%s): %s",
                response.status_code,
                response.text[:200],
            )
            return {}
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("YouTube stats unreachable: %s", exc)
        return {}

    for item in payload.get("items") or []:
        video_id = item.get("id")
        if not video_id:
            continue
        stats = item.get("statistics") or {}
        out[video_id] = {
            "views": _count(stats, "viewCount"),
            "likes": _count(stats, "likeCount"),
            "comments": _count(stats, "commentCount"),
        }
    return out


async def agency_today(db: AsyncSession) -> date:
    """Today's date in the office's zone.

    A snapshot taken at 19:00 in Denver happens on the following day in UTC, so
    grouping by the server's date would file two consecutive evening readings
    under one bucket and leave the day between them empty.
    """
    from datetime import datetime

    name = (
        await db.execute(select(AgentSettings.timezone).limit(1))
    ).scalar_one_or_none()
    zone = (name or "").strip() or DEFAULT_TZ
    try:
        return datetime.now(ZoneInfo(zone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now(ZoneInfo(DEFAULT_TZ)).date()


async def record_snapshot(
    db: AsyncSession,
    *,
    org_id: int,
    publication_id: int,
    captured_on: date,
    source: str,
    values: dict[str, Any],
) -> None:
    """Today's snapshot for one publication, written or refined.

    `org_id` is passed **explicitly**. This is a Core insert, not an ORM one, so
    the `before_flush` listener that stamps `org_id` on everything else never
    runs — and under `eko_app` a row without it is refused by the RLS `WITH
    CHECK`, which surfaces as a permission error nowhere near the cause.

    `ON CONFLICT` and not a read-then-write: two ticks overlapping (a restart
    during a tick, say) would otherwise race and one would raise on the unique
    constraint.
    """
    statement = (
        pg_insert(ContentMetric)
        .values(
            org_id=org_id,
            publication_id=publication_id,
            captured_on=captured_on,
            source=source,
            **values,
        )
        .on_conflict_do_update(
            constraint="uq_content_metrics_pub_day",
            set_={**values, "source": source},
        )
    )
    await db.execute(statement)


async def snapshot_youtube(db: AsyncSession, *, today: date | None = None) -> int:
    """Read every published YouTube video of this org and record today's counts.

    Returns how many publications got a reading, so a caller (and a test) can
    tell "nothing to read" from "read nothing".

    Publications with no `external_url` are skipped in silence: Buffer only
    started reporting the address in a recent version, so the older posts have
    none and never will. They are a gap in the past, not a fault in the present.
    """
    settings = get_settings()
    key = (settings.YOUTUBE_DATA_API_KEY or "").strip()
    if not key:
        log.info("YouTube metrics: no API key configured; nothing read")
        return 0

    org_id = get_org_id()
    if org_id is None:
        log.warning("YouTube metrics ran with no org in context; nothing read")
        return 0

    rows = (
        await db.execute(
            select(ContentPublication.id, ContentPublication.external_url).where(
                ContentPublication.platform == PublicationPlatform.YOUTUBE,
                ContentPublication.status == PublicationStatus.PUBLISHED,
                ContentPublication.external_url.is_not(None),
            )
        )
    ).all()

    by_video: dict[str, list[int]] = {}
    for publication_id, url in rows:
        video_id = youtube_video_id(url)
        if video_id is None:
            log.info("YouTube metrics: unreadable address %r", url)
            continue
        # A list and not a single id: the same video re-posted would otherwise
        # have one of its publications silently lose its reading.
        by_video.setdefault(video_id, []).append(publication_id)

    if not by_video:
        return 0

    day = today or await agency_today(db)
    ids = list(by_video)
    written = 0
    for start in range(0, len(ids), BATCH):
        chunk = ids[start : start + BATCH]
        stats = await fetch_youtube_stats(chunk, key)
        for video_id, counts in stats.items():
            for publication_id in by_video.get(video_id, []):
                await record_snapshot(
                    db,
                    org_id=org_id,
                    publication_id=publication_id,
                    captured_on=day,
                    source="youtube_api",
                    values=counts,
                )
                written += 1
    if written:
        await db.commit()
    return written


async def latest_metrics(
    db: AsyncSession, publication_ids: list[int]
) -> dict[int, ContentMetric]:
    """The newest snapshot of each publication, in one query.

    One query and not one per row: the console lists every piece with its three
    publications, so the per-row version is thirty round trips to draw one page.
    """
    if not publication_ids:
        return {}
    rows = (
        await db.execute(
            select(ContentMetric)
            .where(ContentMetric.publication_id.in_(publication_ids))
            .order_by(
                ContentMetric.publication_id,
                ContentMetric.captured_on.desc(),
            )
        )
    ).scalars().all()
    out: dict[int, ContentMetric] = {}
    for row in rows:
        out.setdefault(row.publication_id, row)
    return out

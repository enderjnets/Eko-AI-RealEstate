"""Handing an approved video to YouTube, TikTok and Instagram, through Buffer.

Shape of the thing, and why each part is the way it is.

**Buffer, not three APIs.** One integrator, one token, three channels already
connected. The alternative is YouTube OAuth with its own Google Cloud project,
Meta Graph and TikTok's content API — three approvals, three refresh-token
lifetimes to babysit, for the same three posts.

**Claim, then record — per PUBLICATION, not per piece.** A piece is three
platforms. The row in `content_publications` is written and committed BEFORE
the outbound call, so a crash between the call and the recording cannot be
mistaken for "never attempted" and retried into a second public post. The
UNIQUE `(piece_id, platform)` is what makes that claim real: a retry, a second
worker and a double click all arrive as the same insert, and the database is
the only participant that sees all three. A row left in PUBLISHING is therefore
never retried automatically — it surfaces in the console for a person, because
the honest options are "post again" and "check the platform", and only one of
those is safe to guess.

**The gate is consulted here, at the moment of publishing.** `ensure_publishable`
re-reads the piece under a lock: approval is a fact about the text that existed
when the button was pressed, and text can change afterwards.

**The organization guard.** Before anything goes out, the publisher asks Buffer
which channels the token's organization has and refuses unless the configured
ids are exactly among them. This is not paranoia — it is the exact failure the
pipeline next door shipped: a hard-coded credential path published a video, in
public, on the wrong brand's channel, while every test stayed green because
they asserted what the config *declared* rather than what the code *used*.

**A 200 is not a success.** Buffer answers GraphQL: errors arrive inside a 200
as a `MutationError` in `data.createPost`. The parser below treats those as
failures, which the reference implementation in the neighbouring project
learned the hard way.

**Never `thumbnailUrl`.** Buffer rejects a video asset carrying one and
discards the whole post. That broke TikTok publishing for three days over
there. The platforms derive their own thumbnails.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from datetime import date as date_cls
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AgentSettings,
    ContentKind,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.services.content_studio import (
    NotPublishable,
    advance,
    ensure_publishable,
    not_our_rail,
)
from app.services.tenant_context import get_org_id
from app.services.timezones import resolve_zone

log = logging.getLogger(__name__)

BUFFER_API_URL = "https://api.buffer.com"
_TIMEOUT_SECONDS = 30.0

# Variables rather than string interpolation: a caption carries quotes,
# newlines and emoji, and escaping them into a query by hand is how a post goes
# out mangled or not at all.
_CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
""".strip()

# One post's state, asked for by id. Read-only: it never creates anything, which
# is why it lives on this side of the approval gate without an exemption — the
# sweep in `test_content_gate_is_absolute.py` skips this module for its own
# helpers, and `publish_approved` is what calls the reconciler, not
# `publish_piece`.
_POST_STATE = """{ status sentAt externalLink error { message } }"""

# Buffer's own labels, read out of the schema by introspection rather than
# guessed: PostStatus is draft | error | needs_approval | scheduled | sending |
# sent. Only two of those are answers; the rest mean "ask again later", and a
# scheduled post spends minutes in `sending` on its way out.
_BUFFER_SENT = "sent"
_BUFFER_ERROR = "error"

_CHANNELS = """
query Channels($input: ChannelsInput!) {
  channels(input: $input) { id service isDisconnected isLocked }
}
""".strip()


class QuotaReached(Exception):
    """Buffer said 429. Not a content failure — nothing is marked FAILED, the
    tick simply stops and the untouched platforms are claimed next time."""


class BufferRefused(Exception):
    """Buffer rejected this post. A fact about this publication, recorded on
    its row so a person can read it."""


def configured_channels() -> dict[PublicationPlatform, str]:
    """The platforms this installation is set up to publish to.

    A platform with no channel id is simply not one of them — an agency that
    only wants TikTok configures TikTok, and the piece closes when the
    platforms that exist have all answered.
    """
    s = get_settings()
    pairs = {
        PublicationPlatform.YOUTUBE: (s.BUFFER_CHANNEL_YOUTUBE or "").strip(),
        PublicationPlatform.TIKTOK: (s.BUFFER_CHANNEL_TIKTOK or "").strip(),
        PublicationPlatform.INSTAGRAM: (s.BUFFER_CHANNEL_INSTAGRAM or "").strip(),
    }
    return {platform: cid for platform, cid in pairs.items() if cid}


def undeliverable_reason() -> str | None:
    """Why no post could ever go out, or None if publishing is usable.

    Asked before any network call, so it is free. "This attempt failed" and "no
    attempt can succeed" deserve opposite responses: the first is retried on
    the next tick, the second produces identical log lines forever until a
    person edits `.env`.
    """
    s = get_settings()
    if not configured_channels():
        return "no BUFFER_CHANNEL_* is set"
    if not (s.CONTENT_PUBLIC_BASE_URL or "").strip():
        return "CONTENT_PUBLIC_BASE_URL is unset, so Buffer has nowhere to fetch the video from"
    if s.BUFFER_SIMULATED:
        return None
    if not (s.BUFFER_ACCESS_TOKEN or "").strip():
        return "BUFFER_ACCESS_TOKEN is unset"
    if not (s.BUFFER_ORG_ID or "").strip():
        return "BUFFER_ORG_ID is unset, and without it the channel ids cannot be verified"
    return None


def public_media_url(piece_id: int) -> str:
    base = (get_settings().CONTENT_PUBLIC_BASE_URL or "").strip().rstrip("/")
    return f"{base}/api/v1/public/content/{piece_id}/media"


# YouTube will not take a video without a category. 26 is "Howto & Style",
# which is what a channel that explains how pricing and selling work actually
# is; the alternative default, 22 "People & Blogs", says nothing and is the
# reason so much of that category is never recommended to anybody.
YOUTUBE_CATEGORY_ID = "26"
# YouTube truncates past 100 characters and TikTok past 90. The hook is written
# to be read in a second, so this cuts almost nothing — but it cuts it here
# rather than letting a platform do it mid-word.
_TITLE_MAX = {PublicationPlatform.YOUTUBE: 100, PublicationPlatform.TIKTOK: 90}


def _title_for(platform: PublicationPlatform, title: str, text: str) -> str:
    """A headline for the platforms that demand one."""
    chosen = (title or text.split("\n", 1)[0]).strip()
    limit = _TITLE_MAX[platform]
    return chosen if len(chosen) <= limit else chosen[: limit - 1].rstrip() + "…"


def build_post_input(
    channel_id: str,
    platform: PublicationPlatform,
    text: str,
    video_url: str,
    ai_generated: bool,
    title: str = "",
    due_at: datetime | None = None,
) -> dict[str, Any]:
    """The `CreatePostInput` for one platform.

    **With `due_at`, the post is custom-scheduled; without it, `shareNow`.**

    An earlier version of this docstring defended `shareNow` on the grounds
    that "a queued post is fetched later, and later is exactly when a piece may
    have been edited out of APPROVED". That reasoning no longer holds, and it
    is worth saying why rather than deleting it. A scheduled row is SCHEDULED,
    which `_close_piece` does not treat as terminal, so the piece stays in
    PUBLISHING — and `_ALLOWED` in `content_studio.py` has no edge from
    PUBLISHING back to NEEDS_APPROVAL. The state machine, not the posting mode,
    is what keeps the video Buffer will fetch and the video a person approved
    the same video. `edit_piece` refuses a PUBLISHING piece for the same
    reason.

    What `shareNow` really bought was an answer to "when?" that nobody had to
    compute — and that answer was "in the next fifteen minutes, all of them at
    once", which is what this whole version exists to stop.

    **Every platform here has required metadata, and the first real attempt is
    what said so.** A version of this function sent metadata to TikTok only,
    reasoning that anything else was an unverified shape. That was the right
    instinct and the wrong conclusion: Buffer refused all three posts, and its
    refusals named exactly what was missing — YouTube "require a title… require
    a category", Instagram "require a type (post, story, or reel)". The field
    names and the enum values below were then read out of Buffer's own schema
    by introspection, not guessed.

    `isAiGenerated` is derived from what the piece is, never hard-coded: a clip
    Natalia filmed in front of a house is not AI-generated, and declaring it so
    would be a false statement on the agency's own channel.
    """
    inp: dict[str, Any] = {
        "channelId": channel_id,
        "text": text,
        "schedulingType": "automatic",
        "mode": "customScheduled" if due_at is not None else "shareNow",
        # Explicit, though Buffer defaults it: the schema marks `needsApproval`
        # non-null, and if that default were ever `true` the post would sit in
        # Buffer's own approval queue while `createPost` still handed us an id.
        # We would record PUBLISHED for something nobody had published. The
        # approval gate that matters already happened in this system.
        "needsApproval": False,
        # No thumbnailUrl. Buffer rejects the whole post if one is present.
        "assets": [{"video": {"url": video_url}}],
    }
    if due_at is not None:
        # UTC, with the offset spelled out. Buffer's `dueAt` is a DateTime and
        # a naive string would be read in whatever zone Buffer felt like.
        inp["dueAt"] = due_at.astimezone(UTC).isoformat()
    ai = bool(ai_generated)
    if platform is PublicationPlatform.TIKTOK:
        inp["metadata"] = {
            "tiktok": {
                "isAiGenerated": ai,
                "title": _title_for(platform, title, text),
            }
        }
    elif platform is PublicationPlatform.YOUTUBE:
        inp["metadata"] = {
            "youtube": {
                "title": _title_for(platform, title, text),
                "categoryId": YOUTUBE_CATEGORY_ID,
                "isAiGenerated": ai,
            }
        }
    elif platform is PublicationPlatform.INSTAGRAM:
        # A vertical video under 90 seconds is a reel; posting it as a feed
        # post would put a portrait video in a square frame. `shouldShareToFeed`
        # is required by the schema and true is the point of publishing at all.
        inp["metadata"] = {
            "instagram": {
                "type": "reel",
                "shouldShareToFeed": True,
                "isAiGenerated": ai,
            }
        }
    return inp


def parse_create_post(payload: dict[str, Any]) -> str:
    """The post id, or raise with what Buffer said.

    GraphQL puts application errors inside a 200 response, so "the request
    succeeded" and "the post was created" are different questions and only the
    second one matters here.
    """
    if not isinstance(payload, dict):
        raise BufferRefused("Buffer did not answer JSON")

    errors = payload.get("errors")
    if errors:
        messages = "; ".join(
            e.get("message", "?") for e in errors if isinstance(e, dict)
        )
        raise BufferRefused(messages or "unnamed GraphQL error")

    created = (payload.get("data") or {}).get("createPost")
    if not isinstance(created, dict):
        raise BufferRefused("response carried no data.createPost")

    kind = created.get("__typename")
    if kind == "PostActionSuccess":
        post_id = (created.get("post") or {}).get("id")
        if not post_id:
            # Accepted with no handle is not success: the id is what finds the
            # post again, and without it nothing can tell a retry from a
            # duplicate.
            raise BufferRefused("Buffer reported success without a post id")
        return str(post_id)

    message = created.get("message")
    raise BufferRefused(f"[{kind}] {message}" if message else f"unexpected reply: {kind}")


async def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            BUFFER_API_URL,
            json={"query": query, "variables": variables},
            headers={
                "Authorization": f"Bearer {s.BUFFER_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code == 429:
        # Retry-After is the truth. The body names the window that ran out
        # ("15m"/"24h"/"30d"), which is not the same question.
        raise QuotaReached(f"Buffer quota reached; retry-after={resp.headers.get('Retry-After')}")
    if resp.status_code >= 400:
        raise BufferRefused(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def verify_organization() -> None:
    """Refuse to publish unless the configured channels are this org's.

    The whole guard, and the reason it is a network call rather than a string
    comparison: a channel id that *looks* right and belongs to somebody else's
    Buffer organization posts a real video on a real stranger's account.
    """
    s = get_settings()
    payload = await _graphql(_CHANNELS, {"input": {"organizationId": s.BUFFER_ORG_ID}})
    if payload.get("errors"):
        messages = "; ".join(
            e.get("message", "?") for e in payload["errors"] if isinstance(e, dict)
        )
        raise BufferRefused(f"could not read the organization's channels: {messages}")

    channels = (payload.get("data") or {}).get("channels") or []
    healthy = {
        c["id"]
        for c in channels
        if isinstance(c, dict) and c.get("id") and not c.get("isDisconnected")
    }
    missing = {
        platform.value: cid
        for platform, cid in configured_channels().items()
        if cid not in healthy
    }
    if missing:
        raise BufferRefused(
            "these configured channels are not connected channels of "
            f"BUFFER_ORG_ID: {missing}"
        )


async def _send(
    piece: ContentPiece,
    platform: PublicationPlatform,
    channel_id: str,
    due_at: datetime | None = None,
) -> str:
    """One post. Returns the platform's id for it.

    With `due_at` the post is handed to Buffer for that instant; without it,
    it goes now. Both paths are simulated identically when BUFFER_SIMULATED.
    """
    text = (piece.caption or piece.hook or "").strip()
    video_url = public_media_url(piece.id)
    payload_in = build_post_input(
        channel_id=channel_id,
        platform=platform,
        text=text,
        video_url=video_url,
        ai_generated=piece.kind is ContentKind.GENERATED,
        title=(piece.hook or "").strip(),
        due_at=due_at,
    )

    if get_settings().BUFFER_SIMULATED:
        log.info(
            "Buffer SIMULATED post piece=%s platform=%s url=%s due=%s text=%r",
            piece.id, platform.value, video_url,
            due_at.isoformat() if due_at else "now", text[:120],
        )
        return f"simulated-{platform.value}-{piece.id}"

    return parse_create_post(await _graphql(_CREATE_POST, {"input": payload_in}))



# ─── The queue ──────────────────────────────────────────────────────────────
#
# One slot a day per channel, in the agency's local time. The owner's rule, in
# his words: "se publican 1 por bloque de mejor horario, nunca dos a la vez".
#
# The schedule lives here rather than in Buffer because Buffer has no mutation
# for a channel's posting schedule — measured by introspecting its mutation
# type: fourteen mutations, none of them about scheduling. What Buffer does
# accept is `mode: customScheduled` with a `dueAt`, so the rule can live in
# code, where a test can hold it to account.


def _slot_for(platform: PublicationPlatform) -> time:
    """The local wall-clock time this channel posts at. Validated at startup."""
    s = get_settings()
    raw = {
        PublicationPlatform.YOUTUBE: s.CONTENT_SLOT_YOUTUBE,
        PublicationPlatform.INSTAGRAM: s.CONTENT_SLOT_INSTAGRAM,
        PublicationPlatform.TIKTOK: s.CONTENT_SLOT_TIKTOK,
    }[platform]
    hour, minute = raw.split(":")
    return time(int(hour), int(minute))


async def agency_zone(db: AsyncSession) -> ZoneInfo | None:
    """The agency's own timezone, or None when it is unusable.

    None is not a detail to shrug at: a date in the wrong zone is worse than no
    date, because it looks right. Callers refuse to schedule rather than guess.
    """
    row = (await db.execute(select(AgentSettings))).scalars().first()
    return resolve_zone(row.timezone if row else None)


def _local_day_bounds(day: date_cls, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """The UTC instants that bracket one LOCAL day.

    Computed by combining a local date with local midnight and converting,
    never by adding 24 hours to a UTC instant. Denver's 20:30 slot is 02:30 UTC
    the *next* day, so a UTC-day comparison would put a Thursday evening post
    and a Friday evening post on the same "day" half the year and on different
    ones the other half. It also keeps the two days either side of a DST change
    twenty-three and twenty-five hours long, which is what they are.
    """
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


#: A row holding a slot. PENDING is deliberately absent — it means a quota
#: pause released the claim and nothing is booked.
_HOLDS_A_SLOT = (
    PublicationStatus.SCHEDULED,
    PublicationStatus.PUBLISHING,
    PublicationStatus.PUBLISHED,
)


async def _day_is_taken(
    db: AsyncSession, platform: PublicationPlatform, day: date_cls, zone: ZoneInfo
) -> bool:
    """Does this channel already have something on this local day?

    Two ways it can, and the second one is the half that is easy to forget:
    a row **scheduled** into that day, or a row **already published** in it.
    Without the second, the first piece queued on a day when something went out
    with `shareNow` would be given that same evening — which is exactly the
    state production was left in on 3-sep, with all three channels published
    and nothing scheduled anywhere.
    """
    start, end = _local_day_bounds(day, zone)
    taken = (
        await db.execute(
            select(func.count())
            .select_from(ContentPublication)
            .where(
                ContentPublication.platform == platform,
                or_(
                    and_(
                        ContentPublication.scheduled_at >= start,
                        ContentPublication.scheduled_at < end,
                        ContentPublication.status.in_(_HOLDS_A_SLOT),
                    ),
                    and_(
                        ContentPublication.published_at >= start,
                        ContentPublication.published_at < end,
                    ),
                ),
            )
        )
    ).scalar_one()
    return taken > 0


async def next_free_slot(
    db: AsyncSession,
    platform: PublicationPlatform,
    zone: ZoneInfo,
    now: datetime,
) -> datetime:
    """The first local day whose slot this channel has not spent yet.

    Returns UTC, which is what the column stores and what Buffer wants.
    """
    slot = _slot_for(platform)
    lead = timedelta(minutes=get_settings().CONTENT_SCHEDULE_LEAD_MINUTES)

    day = now.astimezone(zone).date()
    # Too close to be useful: Buffer fetches the video when the post goes out,
    # and a fetch that starts after the hour has passed is a post that misses
    # it. Tomorrow's slot is late; today's missed slot is never.
    if datetime.combine(day, slot, tzinfo=zone) < now + lead:
        day += timedelta(days=1)

    # A day at a time, in local days. The bound is not arithmetic caution —
    # every iteration is a query, and a bug that made every day look taken
    # would otherwise loop until the request timed out.
    for _ in range(370):
        if not await _day_is_taken(db, platform, day, zone):
            return datetime.combine(day, slot, tzinfo=zone).astimezone(UTC)
        day += timedelta(days=1)
    raise RuntimeError(
        f"no free {platform.value} slot within a year of {now.isoformat()}"
    )


async def _claimed_today(db: AsyncSession) -> int:
    """Pieces claimed today, not posts.

    A piece is three platforms; counting posts would let one video spend three
    days of budget.
    """
    midnight = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return (
        await db.execute(
            select(func.count(func.distinct(ContentPublication.piece_id))).where(
                ContentPublication.created_at >= midnight
            )
        )
    ).scalar_one()


async def _close_piece(db: AsyncSession, piece: ContentPiece) -> None:
    """Move a piece out of PUBLISHING once every configured platform answered.

    A row still in PUBLISHING blocks the close on purpose: that state means a
    human has to look, and closing over it would erase the question.
    """
    wanted = set(configured_channels())
    rows = (
        (
            await db.execute(
                select(ContentPublication).where(
                    ContentPublication.piece_id == piece.id
                )
            )
        )
        .scalars()
        .all()
    )
    terminal = {
        row.platform: row.status
        for row in rows
        if row.status in (PublicationStatus.PUBLISHED, PublicationStatus.FAILED)
    }
    if not wanted <= set(terminal):
        # Something is still owed. A PUBLISHING row means a person has to look;
        # a PENDING one means a quota pause released it and the next tick will
        # pick it up. Closing over either would erase a question nobody
        # answered.
        return

    published = any(s is PublicationStatus.PUBLISHED for s in terminal.values())
    advance(
        piece,
        ContentStatus.PUBLISHED if published else ContentStatus.FAILED,
    )
    await db.commit()


async def publish_piece(db: AsyncSession, piece_id: int) -> None:
    """Publish one approved piece to every configured platform.

    The order is load-bearing: the gate first, then the claim, then the wire.

    `resuming` is what lets a run interrupted by a quota pause finish: the
    piece is already PUBLISHING because this function put it there. Every
    other check runs again regardless.
    """
    piece = await ensure_publishable(db, piece_id, resuming=True)

    # Resolved once, before any claim. A None zone means the agency's timezone
    # is unusable, and a date computed in the wrong zone is worse than no date
    # because it looks right — so nothing is scheduled and the piece waits.
    # `CONTENT_SCHEDULE_ENABLED=false` is the deliberate way back to shareNow.
    zone = await agency_zone(db) if get_settings().CONTENT_SCHEDULE_ENABLED else None
    if get_settings().CONTENT_SCHEDULE_ENABLED and zone is None:
        log.error(
            "Piece %s not scheduled: the agency timezone is unusable, and a "
            "date in the wrong zone is worse than none. Fix it in Settings.",
            piece_id,
        )
        return

    # Whether this is a new attempt or the continuation of one. It decides
    # whether a previous episode's failures are released for another try, and
    # it has to be read BEFORE the status is advanced.
    fresh = piece.status is ContentStatus.APPROVED

    if fresh:
        advance(piece, ContentStatus.PUBLISHING)
        # Committed before any outbound call: the claim has to survive a crash,
        # or a restart would find an APPROVED piece and post it again.
        await db.commit()

    rows = {
        row.platform: row
        for row in (
            (
                await db.execute(
                    select(ContentPublication).where(
                        ContentPublication.piece_id == piece.id
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    # A fresh episode — the piece was APPROVED when this run started, which
    # after a total failure means a person put it back through the queue and
    # approved it again. Their re-approval has to mean something: the rows
    # from the previous attempt are released so those platforms are tried
    # again. Without this a piece that failed everywhere could never be
    # published, because every platform would be "already attempted" forever.
    if fresh:
        for row in rows.values():
            if row.status is PublicationStatus.FAILED:
                row.status = PublicationStatus.PENDING
                row.last_error = None
        if rows:
            await db.commit()

    for platform, channel_id in configured_channels().items():
        existing = rows.get(platform)
        # PUBLISHED is done. SCHEDULED is done too — Buffer already has the
        # post and will publish it; the piece stays in PUBLISHING until then,
        # so this function is called again on every tick in between and a
        # SCHEDULED row left out of this list would be posted a second time,
        # once per tick, for as many days as the queue is deep. PUBLISHING is
        # either in flight or a crash a person has to look at — retrying it
        # blind is how the same video is posted twice. FAILED was attempted in
        # THIS episode and its reason is on the row. Everything else is work
        # still owed.
        if existing is not None and existing.status in (
            PublicationStatus.PUBLISHED,
            PublicationStatus.SCHEDULED,
            PublicationStatus.PUBLISHING,
            PublicationStatus.FAILED,
        ):
            continue

        if existing is not None:
            # Reuse the row rather than insert: `uq_content_publication` makes a
            # second insert for the same pair impossible, and a PENDING row is
            # exactly the claim a quota pause released for this tick to pick up.
            row = existing
            row.status = PublicationStatus.PUBLISHING
            row.last_error = None
        else:
            row = ContentPublication(
                org_id=piece.org_id,
                piece_id=piece.id,
                platform=platform,
                status=PublicationStatus.PUBLISHING,
            )
            db.add(row)
        # The claim, committed before the call. The UNIQUE constraint makes it
        # exclusive; this commit makes it durable.
        await db.commit()

        due_at = (
            await next_free_slot(db, platform, zone, datetime.now(UTC))
            if zone is not None
            else None
        )

        try:
            external_id = await _send(piece, platform, channel_id, due_at)
        except QuotaReached:
            # Not this piece's fault. The claim is rolled back to PENDING so
            # the next tick picks the platform up again rather than reading a
            # quota pause as a post that needs a human.
            row.status = PublicationStatus.PENDING
            await db.commit()
            raise
        except (BufferRefused, httpx.HTTPError) as exc:
            row.status = PublicationStatus.FAILED
            row.last_error = str(exc)[:2000]
            await db.commit()
            log.error(
                "Publishing piece %s to %s failed: %s", piece.id, platform.value, exc
            )
            continue

        row.external_id = external_id
        if due_at is not None:
            # Buffer has it and will publish it then. NOT published: saying so
            # now would put a link in the console that goes nowhere and stop
            # the reconciler ever asking how it went. `published_at` stays
            # empty until it is true.
            row.status = PublicationStatus.SCHEDULED
            row.scheduled_at = due_at
            await db.commit()
            log.info(
                "Scheduled piece %s to %s for %s (%s)",
                piece.id, platform.value, due_at.isoformat(), external_id,
            )
            continue

        row.status = PublicationStatus.PUBLISHED
        row.published_at = datetime.now(UTC)
        await db.commit()
        log.info(
            "Published piece %s to %s (%s)", piece.id, platform.value, external_id
        )

    await _close_piece(db, piece)



async def reconcile_scheduled(db: AsyncSession) -> int:
    """Ask Buffer what happened to the posts whose hour has come.

    Returns how many rows were resolved.

    **Reads, never writes, on Buffer's side.** It is one aliased query for the
    whole batch — six posts in one request is measured, not hoped — and it is
    called from `publish_approved`, not from `publish_piece`, so the ordering
    guarantee that the approval gate precedes the wire is untouched.

    The status labels are Buffer's own, read out of its schema by
    introspection: `sent` and `error` are answers; `draft`, `needs_approval`,
    `scheduled` and `sending` mean ask again later, and a post on its way out
    genuinely sits in `sending` for a while. Nothing is logged per row for
    those — a tick every fifteen minutes would otherwise write a line per
    waiting post forever.
    """
    due = (
        (
            await db.execute(
                select(ContentPublication).where(
                    ContentPublication.status == PublicationStatus.SCHEDULED,
                    ContentPublication.scheduled_at.is_not(None),
                    ContentPublication.scheduled_at <= datetime.now(UTC),
                    ContentPublication.external_id.is_not(None),
                )
                # Deterministic order. Being honest about what this does and
                # does not buy: the aliases below are built from THIS list and
                # read back from it, so the pairing is correct whatever order
                # Postgres returns. I first added this line believing it fixed
                # a mispairing; the mispairing was really the GraphQL envelope
                # being read one level too high, and a mutation test proved the
                # ORDER BY changes no observable behaviour. It stays because
                # the same batch should produce the same query twice — the
                # house rule that every ORDER BY is tie-broken by id — not
                # because anything depends on it.
                .order_by(ContentPublication.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not due:
        return 0

    if get_settings().BUFFER_SIMULATED:
        # No network. A due row is taken to have gone out, which is what makes
        # the whole queue exercisable end to end with nothing leaving the box.
        for row in due:
            row.status = PublicationStatus.PUBLISHED
            row.published_at = row.scheduled_at
        await db.commit()
        await _close_touched(db, due)
        return len(due)

    aliases = {f"p{i}": row for i, row in enumerate(due)}
    query = "query {\n" + "\n".join(
        f'  {alias}: post(input: {{id: "{row.external_id}"}}) {_POST_STATE}'
        for alias, row in aliases.items()
    ) + "\n}"

    try:
        # `_graphql` returns the whole GraphQL envelope, so the aliases live one
        # level down under "data". Reading them from the envelope found nothing
        # for every alias and marked all three posts "no longer exists" —
        # retiring live posts on a successful read. The test that caught it
        # asserts the three labels separately, which is why it could.
        payload = await _graphql(query, {})
    except (BufferRefused, httpx.HTTPError) as exc:
        # Nothing is written. A question we could not ask is not an answer, and
        # marking these FAILED would retire posts that are very likely live.
        log.warning("Could not reconcile %s scheduled posts: %s", len(due), exc)
        return 0

    data = payload.get("data") or {}
    if not data:
        # A 200 with no data at all is a question we did not get an answer to,
        # not an answer of "none of these exist".
        log.warning(
            "Buffer answered with no data for %s scheduled posts: %s",
            len(due), str(payload)[:300],
        )
        return 0

    resolved = 0
    for alias, row in aliases.items():
        post = data.get(alias)
        if post is None:
            # Somebody deleted it in Buffer's own interface, which is today's
            # only way to cancel a queued post. Recording that honestly is what
            # lets the piece close instead of waiting for an hour that will
            # never come.
            row.status = PublicationStatus.FAILED
            row.last_error = "post no longer exists in Buffer"
            resolved += 1
            continue

        status = (post.get("status") or "").lower()
        if status == _BUFFER_SENT:
            row.status = PublicationStatus.PUBLISHED
            row.published_at = _parse_dt(post.get("sentAt")) or datetime.now(UTC)
            # The real address on the platform, which is the only thing in the
            # console a person can actually click.
            row.external_url = post.get("externalLink") or None
            resolved += 1
        elif status == _BUFFER_ERROR or post.get("error"):
            row.status = PublicationStatus.FAILED
            row.last_error = (
                (post.get("error") or {}).get("message") or f"Buffer status {status!r}"
            )[:2000]
            resolved += 1

    if resolved:
        await db.commit()
        await _close_touched(db, due)
    return resolved


async def _close_touched(db: AsyncSession, rows: list[ContentPublication]) -> None:
    """Give every piece the reconciler touched a chance to finish."""
    for piece_id in dict.fromkeys(row.piece_id for row in rows):
        piece = await db.get(ContentPiece, piece_id)
        if piece is not None and piece.status is ContentStatus.PUBLISHING:
            await _close_piece(db, piece)


def _parse_dt(raw: object) -> datetime | None:
    """Buffer's ISO timestamps, or None. A bad one must not lose the row."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def publish_approved(db: AsyncSession) -> int:
    """One tick, for one organization. Returns pieces attempted.

    Runs under `run_for_every_org` like every other worker here, so RLS still
    scopes it to the tenant it was invoked for.
    """
    settings = get_settings()
    if not settings.CONTENT_PUBLISH_ENABLED:
        return 0

    reason = undeliverable_reason()
    if reason is not None:
        log.warning("Publishing is configured but unusable: %s", reason)
        return 0

    # Whose rail is this. The same question the writer and the render queue
    # ask, answered in one place — three copies of it is how they drift apart,
    # and the drift here would post one agency's video to another's channels.
    blocked = await not_our_rail()
    if blocked is not None:
        log.warning("Not publishing: %s", blocked)
        return 0

    # Before anything is queued, find out what already went out. A scheduled
    # post is one Buffer holds, so the only way to learn it published — or
    # failed — is to ask. Done first so a piece whose last platform landed this
    # minute is closed before the tick decides what is still owed.
    await reconcile_scheduled(db)

    claimed = await _claimed_today(db)
    if claimed >= settings.CONTENT_PUBLISH_MAX_PER_DAY:
        return 0

    # Pieces a person approved that have a rendered file, plus pieces already
    # claimed and half-finished (a quota pause leaves those, and they have to
    # be resumed or the piece never closes).
    pending = (
        (
            await db.execute(
                select(ContentPiece)
                .where(
                    ContentPiece.status.in_(
                        (ContentStatus.APPROVED, ContentStatus.PUBLISHING)
                    ),
                    ContentPiece.media_path.is_not(None),
                )
                # "In order" is the order the person approved in, not the
                # order the machine happened to create the rows in. With one
                # slot a day the difference is days of waiting, so it is the
                # owner's rule and not a detail. `id` only breaks ties —
                # `approved_at` is null for a resumed PUBLISHING piece, and
                # nulls go last, which is right: it already has its slot.
                .order_by(ContentPiece.approved_at.asc(), ContentPiece.id.asc())
                .limit(settings.CONTENT_PUBLISH_MAX_PER_DAY - claimed)
            )
        )
        .scalars()
        .all()
    )
    if not pending:
        return 0

    if not settings.BUFFER_SIMULATED:
        # Once per tick, not once per post: the answer cannot change between
        # two posts of the same batch, and it costs a request against the same
        # quota the posts need.
        await verify_organization()

    attempted = 0
    for piece in pending:
        try:
            await publish_piece(db, piece.id)
            attempted += 1
        except QuotaReached as exc:
            log.warning("Stopping this publish tick: %s", exc)
            break
        except NotPublishable as exc:
            # Ordinary: a piece edited back into NEEDS_APPROVAL between the
            # query and the gate. Nothing to fix, nothing to alarm about.
            log.info("Piece %s is not publishable: %s", piece.id, exc)
        except Exception:  # noqa: BLE001 — one piece must not stop the tenant
            log.exception(
                "Publishing piece %s failed unexpectedly (org %s)",
                piece.id,
                get_org_id(),
            )
            await db.rollback()
    return attempted

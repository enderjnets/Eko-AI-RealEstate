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
import re
from datetime import UTC, datetime, time, timedelta
from datetime import date as date_cls
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
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
    ContentSeries,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.services.content_series import contract_for
from app.services.content_studio import (
    NotIdentified,
    NotPublishable,
    advance,
    ensure_publishable,
    not_our_rail,
)
from app.services.content_writer import carries_social_cta, social_action_count
from app.services.publish_followup import (
    caption_carries_link,
    notify_held_without_brokerage,
    notify_held_without_link,
    notify_published,
    notify_slots_full,
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

#: What a post can tell us about how it performed. Asked for separately from
#: `_POST_STATE` because the publisher reads a post to learn whether it went
#: out, and that path runs every fifteen minutes: hanging analytics off it
#: would multiply the payload of the rail that must never be slow.
#:
#: `metrics` is a LIST of `{type, value}`, not an object with fixed fields, and
#: which types arrive depends on the channel — TikTok answered with
#: `totalTimeWatched` and no `saves`, Instagram the reverse. Measured on two
#: real posts on 18-sep-2026, not read off the schema: the enum lists sixteen
#: types and says nothing about which of them a given channel fills in.
_POST_METRICS = """{ status metricsUpdatedAt metrics { type value } }"""

#: Our three columns, and the Buffer metric names that can fill each, **in
#: order of preference**. `likes` is the trap: the enum HAS a `likes` type and
#: neither TikTok nor Instagram returns it — both answer `reactions`. Mapping
#: our column straight onto the same-sounding name would have left `likes` NULL
#: for ever with every layer reporting success; accepting only `reactions`
#: would drop the number the day a channel does send `likes`. So: both, with
#: the one that was actually measured winning if a channel ever sends both.
_METRIC_SOURCES = {
    "views": ("views",),
    "likes": ("reactions", "likes"),
    "comments": ("comments",),
}

# Buffer's own labels, read out of the schema by introspection rather than
# guessed: PostStatus is draft | error | needs_approval | scheduled | sending |
# sent. Only two of those are answers; the rest mean "ask again later", and a
# scheduled post spends minutes in `sending` on its way out.
_BUFFER_SENT = "sent"
_BUFFER_ERROR = "error"
#: Still on its way. A post genuinely sits in `sending` for minutes, and a
#: transient `error` object attached to one of these is not a verdict.
_BUFFER_IN_FLIGHT = frozenset({"draft", "needs_approval", "scheduled", "sending"})
#: Every state this rail knows the name of. Anything else means Buffer changed
#: something under us, which is worth an error rather than a shrug.
_BUFFER_KNOWN_STATES = _BUFFER_IN_FLIGHT | {_BUFFER_SENT, _BUFFER_ERROR}
#: Safe to hand a new `dueAt`. A narrower question than "is this final?", and
#: the answer differs on exactly one state: a post already on its way out must
#: not be rescheduled — Buffer may send it anyway, and our row would then hold
#: a future date for something the channel has already published.
_SAFE_TO_RESCHEDULE = frozenset({"draft", "needs_approval", "scheduled"})

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


def with_platform_utm(
    text: str,
    cta_url: str,
    platform: PublicationPlatform,
    piece_id: int,
    campaign: str,
    medium: str = "social",
) -> str:
    """Normalize and tag the first Denver Home Story link in a caption.

    `medium` exists so the follow-up comment can go through this same router
    instead of assembling a second URL of its own. A comment posted under the
    video and the caption above it must land on the same page — the routing to
    the social hub lives here — while still being countable apart from it. A
    second assembler would have drifted the moment either destination moved.

    The approved text chooses the destination. A root link goes through the
    small social hub; an explicit calculator path or consult fragment stays on
    that destination. Schemeless links become the configured canonical HTTPS
    address, which also makes them clickable where a platform recognizes only
    complete URLs.

    Host matching is exact after removing an optional ``www.``. In particular,
    a domain written inside another URL or a lookalike subdomain is not a site
    link. Existing non-UTM query values and fragments survive; managed UTM
    values are replaced so a re-publish cannot create two competing sources.

    Returns ``text`` byte-for-byte when the CTA is absent or invalid, or no
    matching link appears. Only the first matching link changes.
    """
    found = _first_site_link(text, cta_url)
    if found is None:
        return text
    start, end, parsed, suffix, configured = found
    tagged = _tag_site_link(parsed, configured, platform, piece_id, campaign, medium)
    return text[:start] + tagged + suffix + text[end:]


def link_the_text_chose(
    text: str,
    cta_url: str,
    platform: PublicationPlatform,
    piece_id: int,
    campaign: str,
    medium: str = "social",
) -> str | None:
    """The link the approved text chose, tagged — the URL alone, no text around it.

    The same question `with_platform_utm` answers, asked by somebody who wants
    only the address: the follow-up comment, which must land on the page the
    caption above it points to. Sharing the finder is the point. A caption
    naming `/calculator` and a comment pointing at `/start` is one video sending
    people to two places, and the split is invisible in the report because both
    arrive tagged.

    `None` when the text names no link of ours, which is the caller's cue to
    fall back to the configured address.
    """
    found = _first_site_link(text or "", cta_url)
    if found is None:
        return None
    _start, _end, parsed, _suffix, configured = found
    return _tag_site_link(parsed, configured, platform, piece_id, campaign, medium)


def _tag_site_link(
    parsed: Any,
    configured: Any,
    platform: PublicationPlatform,
    piece_id: int,
    campaign: str,
    medium: str,
) -> str:
    """One found link, rebuilt on the canonical host with our four UTM values."""
    managed = {"utm_source", "utm_medium", "utm_campaign", "utm_content"}
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in managed
    ]
    pairs.extend(
        [
            ("utm_source", getattr(platform, "value", str(platform))),
            ("utm_medium", medium),
            ("utm_campaign", campaign),
            ("utm_content", f"piece-{piece_id}"),
        ]
    )
    path = parsed.path
    if path in ("", "/") and not parsed.fragment:
        path = "/start"
    return urlunsplit(
        (
            configured.scheme or "https",
            configured.netloc,
            path,
            urlencode(pairs),
            parsed.fragment,
        )
    )


def _first_site_link(text: str, cta_url: str) -> tuple[int, int, Any, str, Any] | None:
    """Where our first link sits in `text`, and what it parses to.

    Factored out because two callers need the same answer to "which link did
    the approved text choose": the publisher, which rewrites the caption in
    place, and the comment, which wants the address by itself. Two matchers
    would drift the first time either destination moved — the same reason
    `caption_carries_link` asks this module instead of writing its own regex.

    Returns `(start, end, parsed, trailing_punctuation, configured)`, or `None`
    when there is no CTA configured, the CTA is unusable, or nothing in the
    text is ours.
    """
    configured_text = cta_url.strip()
    if not configured_text:
        return None

    configured = urlsplit(
        configured_text if "://" in configured_text else f"https://{configured_text}"
    )
    configured_host = (configured.hostname or "").lower().rstrip(".")
    if not configured_host or not configured.netloc:
        return None

    base_host = configured_host.removeprefix("www.")
    link_pattern = re.compile(
        r"(?<![\w@./-])(?:"
        r"https?://[^\s<>\"'“”‘’«»]+"
        r"|(?:[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)+"
        r"[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?\.?(?::\d{1,5})?"
        r"(?:[/?#][^\s<>\"'“”‘’«»]*)?(?![\w@-]|\.[\w-])"
        r")",
        re.IGNORECASE,
    )
    for match in link_pattern.finditer(text):
        candidate = match.group(0)
        suffix = ""
        # Sentence punctuation is not part of a URL. Keep a balanced parenthesis
        # or bracket that genuinely belongs to a path, while removing an unmatched
        # closer from Markdown or prose.
        while candidate:
            last = candidate[-1]
            removable = last in ".,;:!?}"
            if last == ")":
                removable = candidate.count(")") > candidate.count("(")
            elif last == "]":
                removable = candidate.count("]") > candidate.count("[")
            if not removable:
                break
            candidate = candidate[:-1]
            suffix = last + suffix

        try:
            parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
            parsed_host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
        except ValueError:
            continue
        if parsed_host != base_host:
            continue
        return match.start(), match.end(), parsed, suffix, configured
    return None


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


# Changing the text of a post Buffer is still holding.
#
# **`editPost` replaces the post, it does not patch it.** Sending `{id, text}`
# and nothing else is accepted by the schema and then refused by the network:
# "Instagram posts require at least one image or video., Instagram posts require
# a type (post, story, or reel)." — the video and the metadata were simply not
# in the input, so they were dropped. `edit_scheduled_text` therefore rebuilds
# the whole input with `build_post_input`, the same function that created the
# post, and changes only the words. Measured on 15-sep-2026, on the first of
# twenty-eight scheduled posts; doing all twenty-eight first would have stripped
# the video from every one of them.
#
# The error branches are the real union, read out of the schema rather than
# guessed. `createPost` above names `MutationError`, which this union does not
# contain — writing the same fragment here fails validation with "Fragment
# cannot be spread here", which is how the shape below was found.
_EDIT_POST = """
mutation EditPost($input: EditPostInput!) {
  editPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id text dueAt status } }
    ... on InvalidInputError { message }
    ... on NotFoundError { message }
    ... on UnauthorizedError { message }
    ... on UnexpectedError { message }
    ... on RestProxyError { message }
    ... on LimitReachedError { message }
  }
}
""".strip()

_READ_POST = """
query ReadPost($input: PostInput!) {
  post(input: $input) { id text dueAt status }
}
""".strip()

# Which `CreatePostInput` keys `EditPostInput` also accepts. Anything else in
# the built input — `channelId`, which a post cannot change — is dropped rather
# than sent, because the schema refuses an unknown field outright and the whole
# edit would fail on a key nobody needed.
_EDITABLE_KEYS = frozenset(
    {"aiAssisted", "assets", "dueAt", "metadata", "mode", "schedulingType", "source", "text"}
)


def parse_edit_post(payload: dict[str, Any]) -> dict[str, Any]:
    """The edited post, or raise with what Buffer said. Mirrors its sibling."""
    if not isinstance(payload, dict):
        raise BufferRefused("Buffer did not answer JSON")

    errors = payload.get("errors")
    if errors:
        messages = "; ".join(e.get("message", "?") for e in errors if isinstance(e, dict))
        raise BufferRefused(messages or "unnamed GraphQL error")

    edited = (payload.get("data") or {}).get("editPost")
    if not isinstance(edited, dict):
        raise BufferRefused("response carried no data.editPost")

    kind = edited.get("__typename")
    if kind == "PostActionSuccess":
        post = edited.get("post")
        if not isinstance(post, dict) or not post.get("id"):
            raise BufferRefused("Buffer reported success without a post")
        return post

    message = edited.get("message")
    raise BufferRefused(f"[{kind}] {message}" if message else f"unexpected reply: {kind}")


async def read_scheduled_post(post_id: str) -> dict[str, Any]:
    """What Buffer currently holds for this post: its text, due date and state.

    Read before every edit rather than reconstructed from our own caption: a
    caption edited by hand after the post was queued would otherwise be silently
    overwritten with what we think we sent.
    """
    payload = await _graphql(_READ_POST, {"input": {"id": post_id}})
    post = (payload.get("data") or {}).get("post")
    if not isinstance(post, dict):
        raise BufferRefused(f"Buffer knows no post {post_id}")
    return post


async def edit_scheduled_text(
    piece: ContentPiece,
    platform: PublicationPlatform,
    post_id: str,
    text: str,
    due_at: datetime | None,
) -> dict[str, Any]:
    """Replace the words of a queued post, keeping everything else it has.

    For a correction to something already handed to Buffer — a brokerage line
    that changed, a figure that went stale — where cancelling and re-queuing
    would lose the slot and the schedule. It does not touch the approval gate,
    because it does not publish: the post was already approved and queued, and
    this changes what it will say.
    """
    channel_id = configured_channels().get(platform)
    if not channel_id:
        raise BufferRefused(f"no channel configured for {platform.value}")

    built = build_post_input(
        channel_id=channel_id,
        platform=platform,
        text=text,
        video_url=public_media_url(piece.id),
        ai_generated=piece.kind is ContentKind.GENERATED,
        title=(piece.hook or "").strip(),
        due_at=due_at,
    )
    payload = {k: v for k, v in built.items() if k in _EDITABLE_KEYS}
    payload["id"] = post_id
    return parse_edit_post(await _graphql(_EDIT_POST, {"input": payload}))


# What Buffer will not let us go below before we stop asking. Two, not zero:
# `reconcile_scheduled` runs at the top of every tick and a rail that spends
# its last request posting cannot afterwards ask how the post went.
_QUOTA_FLOOR = 2

# How long the brake may hold, whatever Buffer says. The daily window refills
# thirteen hours out, and a rejected request costs no quota — so holding for
# the full `Retry-After` buys nothing and risks the opposite: one wrong number
# from Buffer, or a reset that lands earlier than advertised, and this rail is
# dead in process memory until the container restarts. An hour of quiet is
# what the brake is actually for; past that, ask again and be refused cheaply.
_QUOTA_BRAKE_MAX_SECONDS = 3600

# And how long it holds when Buffer refuses without saying for how long — no
# readable `Retry-After`, no readable `ratelimit`. One tick of this worker,
# which is also the shortest window Buffer publishes.
_QUOTA_BRAKE_FALLBACK_SECONDS = 900

# Buffer counts per API client, not per endpoint, so this is deliberately
# module state rather than per-call: every caller in this file draws on the
# same two windows — a hundred requests per fifteen minutes and two hundred
# and fifty per day.
_quota_remaining: int | None = None
_quota_refills_at: float = 0.0


def slots_are_full(message: str) -> bool:
    """Whether Buffer refused because that channel's queue is full.

    Told apart from every other refusal because the answer is different in
    kind. A caption Instagram will not accept is about the piece and will be
    refused again tomorrow; ten scheduled posts is about the calendar and
    stops being true the moment one of them goes out.
    """
    return "scheduled posts limit reached" in (message or "").lower()


def parse_rate_limit(header: str | None) -> tuple[int | None, int | None]:
    """What is left in the tightest window, read from Buffer's `ratelimit` header.

    There are **two** windows, not one, and they arrive in a single header
    separated by a comma — measured off a real 429 on 16-sep-2026:

        "100-in-15min"; r=98; t=146, "250-in-1day"; r=0; t=47729

    `r` is what remains and `t` the seconds until that policy refills. The
    daily one is the one that ran out that day, and the one this returns: the
    window that binds is the window with the least left, together with **its
    own** `t` — pairing a spent quota with the other policy's refill is how a
    thirteen-hour wall gets read as two minutes. On a tie the longer `t` wins,
    for the same reason.

    Anything that does not parse returns `(None, None)` on purpose — an
    unreadable header is not news that the quota is spent, and reading it as
    zero would stop the rail over a string.
    """
    if not header:
        return None, None
    policies: list[tuple[int | None, int | None]] = []
    for policy in header.split(","):
        found: dict[str, int] = {}
        for part in policy.split(";"):
            key, _, raw = part.partition("=")
            # The header's own grammar allows space around the `=`. Buffer does
            # not use it today; reading it costs one `strip` and not reading it
            # would drop the field silently, which looks exactly like a header
            # that carries no remainder at all.
            name = key.strip()
            if name in ("r", "t"):
                try:
                    found[name] = int(raw)
                except ValueError:
                    return None, None
        policies.append((found.get("r"), found.get("t")))
    if not policies:
        return None, None
    # A policy that does not state what is left cannot be the one that binds;
    # with none of them stating it there is no brake to apply either way, and
    # the first `t` is kept so a header carrying only a refill still answers.
    binding = [(r, t) for r, t in policies if r is not None]
    if not binding:
        return None, policies[0][1]
    return min(binding, key=lambda rt: (rt[0], -(rt[1] if rt[1] is not None else -1)))


def _seconds_or_none(raw: str | None) -> int | None:
    """`Retry-After` as a whole number of seconds, or nothing.

    The header is also allowed to carry an HTTP date. Buffer sends seconds and
    that is what is handled; a date parses as no answer rather than as zero,
    because zero here would mean "ask again immediately".
    """
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def _refused_window(resp: httpx.Response) -> str | None:
    """Which of Buffer's windows the refusal was about, from the body.

    Names the policy ("24h", "15m") for the log line only. It is not the wait —
    `Retry-After` is — and the distinction is the whole reason the daily window
    went unnoticed on 16-sep: a body saying `24h` was read as a description of
    a fifteen-minute rail.
    """
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return None
    for error in errors:
        if not isinstance(error, dict):
            continue
        extensions = error.get("extensions")
        if not isinstance(extensions, dict):
            continue
        window = extensions.get("window")
        if isinstance(window, str) and window:
            # Server-supplied text on its way into a log line: capped and
            # flattened, like every other borrowed string in this file. A
            # newline here would forge a log record.
            return " ".join(window.split())[:40]
    return None


async def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """One request, with the quota read before it is spent rather than after.

    Reacting to 429 alone means every ceiling is discovered by hitting it, and
    the request that hits it is a real post that then has to be picked up
    again. Buffer states what is left on every response; this stops one short
    of the edge instead.

    There is deliberately no sleep-and-retry here, so there is no jitter
    either: the docs warn that an exact `Retry-After` makes every client
    return in the same instant, but this rail does not return — it raises
    `QuotaReached`, the tick ends, and the scheduler brings the next one round
    later. Jitter on a path that never waits would be decoration.
    """
    global _quota_remaining, _quota_refills_at

    if (
        _quota_remaining is not None
        and _quota_remaining <= _QUOTA_FLOOR
        and monotonic() < _quota_refills_at
    ):
        raise QuotaReached(
            f"only {_quota_remaining} Buffer requests left in this window; "
            f"stopping {int(_quota_refills_at - monotonic())}s short of the refill"
        )

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
    remaining, refills_in = parse_rate_limit(resp.headers.get("ratelimit"))
    if remaining is not None:
        _quota_remaining = remaining
        # Clamped at both ends. Above, so one bad number cannot park the rail
        # for thirteen hours; below, because a refill already in the past is
        # the brake disarmed, and `t` is a number Buffer chooses, not us.
        _quota_refills_at = monotonic() + max(
            0, min(refills_in or 0, _QUOTA_BRAKE_MAX_SECONDS)
        )

    if resp.status_code == 429:
        # Retry-After is the truth, and it **overrides** whatever the header
        # said a line above: they can disagree, and this is the one Buffer
        # commits to. The body names the window that ran out ("15m"/"24h"),
        # which is a different question and belongs in the message, not in the
        # timing. A rejected request costs no quota, so `_quota_remaining` is
        # set to zero not to account for this call but so the *next* tick
        # stops at the check above without sending anything at all — which is
        # what was missing on 16-sep, when every tick for fourteen hours spent
        # a request to be told the same thing.
        retry_after = _seconds_or_none(resp.headers.get("Retry-After"))
        _quota_remaining = 0
        if retry_after is not None:
            _quota_refills_at = monotonic() + min(retry_after, _QUOTA_BRAKE_MAX_SECONDS)
        else:
            # A refusal this rail cannot time. Without a floor the brake is
            # armed on one side only — `_quota_remaining` is zero but the
            # refill stays in the past — and the pre-check needs both, so
            # every tick would go back out to be refused again: the exact
            # 16-sep behaviour. `Retry-After` can legitimately arrive as an
            # HTTP date, and a proxy in front of Buffer sends neither header.
            # Fifteen minutes is the shortest window Buffer publishes and one
            # tick of this worker, so being wrong costs a single skipped tick.
            #
            # Assigned, not `max`ed with what the header left here. The header's
            # `t` says when that policy refills, which is not how long this
            # refusal lasts — and a 429 that is not about the quota at all (a
            # proxy in front of Buffer, say) would otherwise inherit the daily
            # window's hour and stop the rail for every agency at once, where
            # before the change it cost one tick. With no timing from Buffer,
            # the only honest answer is the shortest one.
            _quota_refills_at = monotonic() + _QUOTA_BRAKE_FALLBACK_SECONDS
        window = _refused_window(resp)
        raise QuotaReached(
            f"Buffer quota reached{f' on its {window} window' if window else ''}; "
            f"retry-after={(resp.headers.get('Retry-After') or '')[:40] or 'unstated'}"
        )
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
    # Per platform, and therefore here rather than in the writer: the caption is
    # written once and posted three times, and the whole point is that the three
    # links differ.
    settings = get_settings()
    text = with_platform_utm(
        text,
        settings.CONTENT_CTA_URL,
        platform,
        piece.id,
        settings.CONTENT_UTM_CAMPAIGN,
    )
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
# One or more slots a day per channel, in the agency's local time, hours apart.
# The owner's rule holds and is the reason the hours are declared rather than
# derived: "se publican 1 por bloque de mejor horario, nunca dos a la vez" —
# two slots are two blocks, never the same instant.
#
# The schedule lives here rather than in Buffer because Buffer has no mutation
# for a channel's posting schedule — measured by introspecting its mutation
# type: fourteen mutations, none of them about scheduling. What Buffer does
# accept is `mode: customScheduled` with a `dueAt`, so the rule can live in
# code, where a test can hold it to account.


def _slots_for(platform: PublicationPlatform) -> list[time]:
    """The local wall-clock times this channel posts at, earliest first.

    Always at least one. `Settings._valid_clock_time` has already refused an
    unsorted or duplicated list at startup, so this can trust the order rather
    than re-sorting: sorting here would hide a misconfiguration that the
    validator exists to surface.
    """
    s = get_settings()
    raw = {
        PublicationPlatform.YOUTUBE: s.CONTENT_SLOT_YOUTUBE,
        PublicationPlatform.INSTAGRAM: s.CONTENT_SLOT_INSTAGRAM,
        PublicationPlatform.TIKTOK: s.CONTENT_SLOT_TIKTOK,
    }[platform]
    slots = []
    for chunk in raw.split(","):
        hour, minute = chunk.strip().split(":")
        slots.append(time(int(hour), int(minute)))
    return slots


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


async def _free_slots(
    db: AsyncSession, platform: PublicationPlatform, day: date_cls, zone: ZoneInfo
) -> list[time]:
    """Which of this channel's slots this local day still has, earliest first.

    Not a count. Counting and then indexing gives the wrong answer the moment
    the spent slot is not the first one: with 11:30 free and 18:30 booked,
    "one of two taken" would hand out 18:30 again. A slot is spent when a row
    holding it sits at *that instant*, so the answer is a set difference.

    Two ways a day loses capacity, and the second one is the half that is easy
    to forget:

    * A row **scheduled** at one of the slots — that slot, and only that one.
    * A row **already published** in the day that never held a slot (a
      `shareNow` post, or one scheduled on some other day). It occupies no
      particular hour, so it spends the earliest slot still free. Without this,
      the first piece queued on a day when something already went out would be
      given that same evening — the state production was left in on 3-sep,
      with all three channels published and nothing scheduled anywhere. Under
      the old one-slot rule such a row closed the whole day; with two slots
      closing the day would throw away capacity that exists.
    """
    start, end = _local_day_bounds(day, zone)
    rows = (
        await db.execute(
            select(
                ContentPublication.scheduled_at,
                ContentPublication.published_at,
                ContentPublication.status,
            ).where(
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
    ).all()

    def key(moment: datetime) -> datetime:
        # Compare on the instant, normalised: the stored value and the one
        # computed here are both ours and minute-precise, but a stray
        # microsecond would silently free a slot that is taken.
        return moment.astimezone(UTC).replace(microsecond=0)

    occupied: set[datetime] = set()
    slotless = 0
    for scheduled_at, published_at, status in rows:
        holds = (
            scheduled_at is not None
            and start <= scheduled_at < end
            and status in _HOLDS_A_SLOT
        )
        if holds:
            occupied.add(key(scheduled_at))
        elif published_at is not None and start <= published_at < end:
            slotless += 1

    free = [
        slot
        for slot in _slots_for(platform)
        if key(datetime.combine(day, slot, tzinfo=zone)) not in occupied
    ]
    # The slotless rows eat from the front, which is the conservative end: it
    # never hands out an hour earlier than the capacity that is actually left.
    return free[slotless:]


def _from_when(piece: ContentPiece, zone: ZoneInfo) -> datetime:
    """When to start looking for a slot: the piece's own date, or now.

    Approval order was the only calendar this rail had, and that made two
    unrelated things the same decision: "this is fit to publish" and "this goes
    out before that one". Approving eighteen autumn pieces from the top of a
    panel that lists newest first published the season backwards — the piece for
    late October second, the one for mid September last. It happened twice in
    one night, and neither time did anything warn.

    A piece with `publish_window_start` says when it is *about*. Looking from
    that date instead of from now makes the two decisions separate again: the
    owner approves whenever, and the calendar comes from the piece.

    Never earlier than now — a window that has already opened does not mean
    "publish in the past", it means "as soon as there is a slot". And a piece
    with no window (the calculator ones are permanent) behaves exactly as
    before, which is why they need no window at all.
    """
    now = datetime.now(UTC)
    start = piece.publish_window_start
    if start is None:
        return now
    # The window is a local date; the search wants an instant. Midnight local,
    # so `next_free_slot` finds that day's first free slot rather than skipping
    # to the next day.
    opens = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    return max(now, opens)


async def next_free_slot(
    db: AsyncSession,
    platform: PublicationPlatform,
    zone: ZoneInfo,
    now: datetime,
) -> datetime:
    """The first slot, on the first local day, this channel has not spent yet.

    Returns UTC, which is what the column stores and what Buffer wants.
    """
    lead = timedelta(minutes=get_settings().CONTENT_SCHEDULE_LEAD_MINUTES)
    day = now.astimezone(zone).date()

    # A day at a time, in local days. The bound is not arithmetic caution —
    # every iteration is a query, and a bug that made every day look taken
    # would otherwise loop until the request timed out.
    for _ in range(370):
        for slot in await _free_slots(db, platform, day, zone):
            when = datetime.combine(day, slot, tzinfo=zone)
            # Too close to be useful: Buffer fetches the video when the post
            # goes out, and a fetch that starts after the hour has passed is a
            # post that misses it. The lead is applied PER SLOT, not per day:
            # with the morning slot already gone, this evening is still a
            # better answer than tomorrow morning.
            if when >= now + lead:
                return when.astimezone(UTC)
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

    # Here rather than beside the per-platform commits above: three posts are
    # one video to the person who has to go and paste the comment, and this is
    # the only place that runs once per piece. Buffer posts videos and cannot
    # write comments, so that step stays human — but it arrives finished, with
    # this piece's own tag already in the link, rather than as something to
    # remember. After the commit, so a notice can never be the reason a close
    # is rolled back.
    if published and contract_for(
        piece.series or ContentSeries.CONVERSION
    ).requires_site_link:
        await notify_published(
            piece.id,
            piece.hook or "",
            get_settings().CONTENT_CTA_URL,
            caption=piece.caption or piece.hook or "",
        )


async def publish_piece(db: AsyncSession, piece_id: int) -> None:
    """Publish one approved piece to every configured platform.

    The order is load-bearing: the gate first, then the claim, then the wire.

    `resuming` is what lets a run interrupted by a quota pause finish: the
    piece is already PUBLISHING because this function put it there. Every
    other check runs again regardless.
    """
    piece = await ensure_publishable(db, piece_id, resuming=True)

    # The second half of the gate, and the reason it is here rather than in
    # `ensure_publishable`: that function lives in `content_studio`, which this
    # module imports, and the matcher that answers the question lives here. A
    # caption with no link publishes a video with no way back to the page —
    # measured in September 2026 as 3,833 views and one visit. Announced rather
    # than only logged, because `publish_approved` treats `NotPublishable` as
    # ordinary and a piece held in silence is held forever.
    series = piece.series or ContentSeries.CONVERSION
    contract = contract_for(series)
    copy = piece.caption or piece.hook or ""
    cta_url = (get_settings().CONTENT_CTA_URL or "").strip()
    carries_site_link = (
        caption_carries_link(copy, cta_url)
        if contract.requires_site_link
        else bool(cta_url) and caption_carries_link(copy, cta_url)
    )
    if contract.requires_site_link and not carries_site_link:
        await notify_held_without_link(piece.id, piece.hook or "")
        raise NotPublishable(
            f"piece {piece_id} has no link to the site in its caption, and a "
            "video nobody can click out of is the one thing this channel exists "
            "to avoid"
        )
    if not contract.requires_site_link and carries_site_link:
        raise NotPublishable(
            f"piece {piece_id} belongs to {series.value} but carries a site link; "
            "this line is approved for one social action only"
        )
    if not contract.requires_site_link and (
        not carries_social_cta(copy, series) or social_action_count(copy) != 1
    ):
        raise NotPublishable(
            f"piece {piece_id} belongs to {series.value} but it does not carry "
            "exactly one social call to action"
        )

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
            # What this row already said, captured before the claim wipes it.
            # A platform that was already waiting on a full Buffer queue must
            # not ring the owner's phone again on every fifteen-minute tick.
            was_pending_before = existing.status is PublicationStatus.PENDING
            previous_error = existing.last_error
            row.status = PublicationStatus.PUBLISHING
            row.last_error = None
        else:
            was_pending_before = False
            previous_error = None
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
            await next_free_slot(db, platform, zone, _from_when(piece, zone))
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
            if slots_are_full(str(exc)):
                # Only on the way in. The tick comes round every fifteen
                # minutes and a notice per attempt is noise nobody reads,
                # which ends up being the same as no notice at all.
                already_waiting = (
                    was_pending_before and slots_are_full(previous_error or "")
                )
                # Not this piece's fault, and FAILED here is a death
                # sentence: nothing retries a failed row unless a person
                # approves the whole piece again, and the per-platform arrival
                # of this refusal means a piece can lose one channel and keep
                # the others, then close as published having gone out on one.
                # That is exactly what happened to 33, 34 and 36 on 15-sep and
                # to one channel each of 37 and 38. PENDING is the answer a
                # quota pause already gets: still owed, try again next tick.
                row.status = PublicationStatus.PENDING
                row.last_error = str(exc)[:2000]
                await db.commit()
                log.warning(
                    "Piece %s: the %s queue at Buffer is full, leaving the "
                    "platform pending rather than failed: %s",
                    piece.id, platform.value, exc,
                )
                if not already_waiting:
                    await notify_slots_full(piece.id, piece.hook or "", platform.value)
                continue
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



async def _post_states(
    rows: list[ContentPublication], what: str, selection: str = _POST_STATE
) -> list[tuple[str, ContentPublication, dict[str, Any] | None, dict[str, Any] | None]] | None:
    """One aliased read for a whole batch: `(alias, row, post, error)` per row.

    `None` means the question could not be asked at all — a distinction the
    callers depend on, because "no answer" and "the answer is no" lead to
    opposite writes.
    """
    if not rows:
        # Both callers check first, so this is belt and braces — but an empty
        # batch builds `query () {\n\n}`, which Buffer rejects, and a third
        # caller would find that out in production rather than here.
        return []
    # Ids travel as GraphQL VARIABLES, never interpolated into the query. Two
    # reasons, both measured rather than imagined. A quote in one id used to
    # invalidate the whole batch string, Buffer answered 400, and every other
    # row in that batch went unreconciled on every tick from then on — a
    # permanent, silent stall behind one bad value. And an id carrying
    # `") { id } evil: organization(input: { id: "` appended a second field to
    # our own query. These ids come from Buffer's own answers, so the attacker
    # would have to be Buffer or somebody between us — but a parameterised
    # query costs nothing and closes both.
    aliases = {f"p{i}": row for i, row in enumerate(rows)}
    query = (
        "query ("
        + ", ".join(f"${alias}: PostId!" for alias in aliases)
        + ") {\n"
        + "\n".join(
            f"  {alias}: post(input: {{id: ${alias}}}) {selection}"
            for alias in aliases
        )
        + "\n}"
    )
    variables = {alias: row.external_id for alias, row in aliases.items()}

    try:
        # `_graphql` returns the whole GraphQL envelope, so the aliases live one
        # level down under "data". Reading them from the envelope found nothing
        # for every alias and marked all three posts "no longer exists" —
        # retiring live posts on a successful read. The test that caught it
        # asserts the three labels separately, which is why it could.
        payload = await _graphql(query, variables)
    except (BufferRefused, httpx.HTTPError) as exc:
        # Nothing is written. A question we could not ask is not an answer, and
        # marking these FAILED would retire posts that are very likely live.
        log.warning("Could not reconcile %s %s: %s", len(rows), what, exc)
        return None

    # A 200 carrying `errors` is not a verdict on every post in it. GraphQL
    # answers 200 and puts application errors in the body — the same thing
    # `parse_create_post` already knows about writes — and each entry names the
    # alias it belongs to in its `path`. Read as a blanket failure it marked a
    # LIVE post "no longer exists", the piece closed FAILED, FAILED is the one
    # status that offers a person Retry, and a re-approved piece re-sends its
    # failed rows: a transient read error ended in a second public post.
    #
    # **Measured against the real API, because the shape decides the code.**
    # Asking for one real id and one well-formed id that does not exist:
    #
    #   {"errors":[{"message":"Post not found for id: 0000…",
    #               "path":["p1"],"extensions":{"code":"NOT_FOUND"}}],
    #    "data":null}
    #
    # Two things follow, and both contradict what this was first written to do.
    # Buffer does NOT return a clean `null` for a post somebody deleted — it
    # returns an error — so the "alias is null means gone" branch was
    # unreachable. And one bad id nulls `data` for the WHOLE batch, so a single
    # deleted post would have stalled every other row on every tick for ever.
    #
    # So: errors are matched to their alias by `path`. NOT_FOUND is a real
    # answer about that one post; anything else is a read that failed. The rows
    # we could not read keep their status and come back on the next tick — by
    # which time the NOT_FOUND ones are recorded and out of the batch.
    by_alias: dict[str, dict[str, Any]] = {}
    for err in payload.get("errors") or []:
        path = err.get("path") or []
        if path and isinstance(path[0], str):
            by_alias[path[0]] = err

    data = payload.get("data") or {}
    if not data and not by_alias:
        # No answers and nothing to explain why: a question we did not get an
        # answer to, not an answer of "none of these exist".
        log.warning(
            "Buffer answered with no data for %s %s: %s",
            len(rows), what, str(payload)[:300],
        )
        return None

    return [
        (alias, row, data.get(alias), by_alias.get(alias))
        for alias, row in aliases.items()
    ]


def parse_post_metrics(post: dict[str, Any] | None) -> tuple[dict[str, int], datetime | None]:
    """One post's numbers and the moment Buffer read them.

    Returns `({column: value}, read_at)`. An empty dict means the post carried
    no metric we store — which is a fact, not a failure: a post published
    minutes ago has none yet.

    Everything here is defensive on purpose. These values cross a vendor
    boundary, `value` arrives as a float for the time metrics (`4.49` seconds
    watched) and as a whole number for counts, and a single malformed entry
    must cost that entry rather than the whole batch: the caller writes every
    other post in the same pass.
    """
    if not isinstance(post, dict):
        return {}, None

    # Read every entry first, resolve columns after. Doing it the other way
    # round makes the answer depend on the ORDER Buffer happens to list its
    # metrics in, which is not something it promises.
    seen: dict[str, int] = {}
    entries = post.get("metrics")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("type") or "").strip()
            if not name:
                continue
            try:
                # `int(float(...))` rather than `int(...)`. The measured
                # reason is narrow: Buffer sends floats on this field —
                # `averageTimeWatched` came back as 4.49 — and `int()` already
                # handles those. What the extra `float()` buys is the case
                # nobody has seen, a count serialised as the STRING "94.0",
                # where `int()` raises. Kept because it costs nothing; not
                # claimed as observed, and no test pretends to prove it.
                #
                # Bool is excluded above because `True` is an int in Python and
                # would otherwise be stored as one view. That one IS tested.
                raw = entry.get("value")
                if isinstance(raw, bool) or raw is None:
                    continue
                seen[name] = int(float(raw))
            except (TypeError, ValueError, OverflowError):
                log.info("Buffer metric %r has an unreadable value", name)

    values: dict[str, int] = {}
    for column, names in _METRIC_SOURCES.items():
        for name in names:
            if name in seen:
                values[column] = seen[name]
                break

    read_at = _moment_utc(post.get("metricsUpdatedAt"))
    return values, read_at


def _moment_utc(raw: Any) -> datetime | None:
    """Buffer's ISO timestamp, or None. Its `Z` suffix needs replacing."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def read_post_metrics(
    rows: list[ContentPublication],
) -> list[tuple[ContentPublication, dict[str, int], datetime | None]] | None:
    """The numbers for a batch of published posts, or `None` if we could not ask.

    `None` and `[]` are different answers and the caller depends on it: nothing
    is written when the question never reached Buffer.
    """
    answers = await _post_states(rows, "post metrics", selection=_POST_METRICS)
    if answers is None:
        return None

    out: list[tuple[ContentPublication, dict[str, int], datetime | None]] = []
    for _alias, row, post, error in answers:
        if error is not None:
            # Per alias, exactly like the publisher's reader: one id Buffer
            # cannot find must not discard the numbers of the other five.
            log.info(
                "Buffer has no metrics for publication %s: %s",
                row.id, str(error.get("message"))[:120],
            )
            continue
        values, read_at = parse_post_metrics(post)
        if values:
            out.append((row, values, read_at))
    return out


_LOST_IN_BUFFER = "post no longer exists in Buffer"


def _buffer_lost_it(err: dict[str, Any]) -> bool:
    code = str((err.get("extensions") or {}).get("code") or "").upper()
    message = str(err.get("message") or "")
    return code == "NOT_FOUND" or "not found" in message.lower()


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

    answers = await _post_states(due, "scheduled posts")
    if answers is None:
        return 0

    resolved = 0
    unknown: list[tuple[int, str, str]] = []
    unread: list[str] = []
    for alias, row, post, err in answers:
        if err is not None:
            code = str((err.get("extensions") or {}).get("code") or "").upper()
            message = str(err.get("message") or "")
            if _buffer_lost_it(err):
                # Somebody deleted it in Buffer's own interface, which is
                # today's only way to cancel a queued post. Recording that
                # honestly is what lets the piece close instead of waiting for
                # an hour that will never come.
                row.status = PublicationStatus.FAILED
                row.last_error = _LOST_IN_BUFFER
                resolved += 1
            else:
                # Rate limits, timeouts, anything else: a question we could not
                # ask about THIS post. It keeps its status and is asked again.
                unread.append(f"{alias}={code or message[:60]}")
            continue

        if post is None:
            # No answer and no error naming it — `data` was nulled wholesale by
            # a sibling's error. Silence is not a verdict.
            unread.append(f"{alias}=no answer")
            continue

        status = (post.get("status") or "").lower()
        if status == _BUFFER_SENT:
            row.status = PublicationStatus.PUBLISHED
            row.published_at = _parse_dt(post.get("sentAt")) or datetime.now(UTC)
            # The real address on the platform, which is the only thing in the
            # console a person can actually click.
            row.external_url = post.get("externalLink") or None
            resolved += 1
        elif status == _BUFFER_ERROR or (
            post.get("error") and status not in _BUFFER_IN_FLIGHT
        ):
            row.status = PublicationStatus.FAILED
            row.last_error = (
                (post.get("error") or {}).get("message") or f"Buffer status {status!r}"
            )[:2000]
            resolved += 1
        elif status not in _BUFFER_IN_FLIGHT:
            # Not `sent`, not `error`, and not one of the states we know mean
            # "still on its way". Nothing is written — inventing a verdict from
            # a label we do not understand is how a live post gets retired —
            # but it is said out loud, because the silent alternative is a
            # piece stuck in PUBLISHING for ever while every tick asks again
            # and nobody is told.
            unknown.append((row.piece_id, row.platform.value, status))

    if unread:
        log.warning(
            "Buffer could not answer for %s scheduled post(s) this tick; they "
            "keep their status and are asked again: %s",
            len(unread), unread[:10],
        )

    if unknown:
        log.error(
            "Buffer reported %s scheduled post(s) in a state this code does "
            "not know, so they cannot be closed: %s. Somebody has to look.",
            len(unknown), unknown[:10],
        )

    if resolved:
        await db.commit()
        await _close_touched(db, due)
    return resolved


async def forget_deleted_future(db: AsyncSession) -> int:
    """Find the queued posts somebody deleted in Buffer before their hour.

    `reconcile_scheduled` asks only about posts whose hour has come, so a post
    deleted twelve days ahead stayed SCHEDULED for twelve days and the writer
    read its day as taken the whole time. This pass asks about the future ones,
    once a day, and writes only on NOT_FOUND: `scheduled` is just the queue,
    and anything else, or no answer, waits for the post's own hour.
    """
    future = (
        (
            await db.execute(
                select(ContentPublication)
                .where(
                    ContentPublication.status == PublicationStatus.SCHEDULED,
                    ContentPublication.scheduled_at > datetime.now(UTC),
                    ContentPublication.external_id.is_not(None),
                )
                .order_by(ContentPublication.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not future or get_settings().BUFFER_SIMULATED:
        return 0

    answers = await _post_states(list(future), "future scheduled posts")
    if answers is None:
        return 0

    lost = 0
    for _alias, row, _post, err in answers:
        if err is not None and _buffer_lost_it(err):
            row.status = PublicationStatus.FAILED
            row.last_error = _LOST_IN_BUFFER
            lost += 1
    if lost:
        await db.commit()
        log.info(
            "%s future post(s) were deleted in Buffer's interface; their days "
            "are free again", lost,
        )
        await _close_touched(db, list(future))
    return lost


async def _close_touched(db: AsyncSession, rows: list[ContentPublication]) -> None:
    """Give every piece the reconciler touched a chance to finish."""
    for piece_id in dict.fromkeys(row.piece_id for row in rows):
        piece = await db.get(ContentPiece, piece_id)
        if piece is not None and piece.status is ContentStatus.PUBLISHING:
            await _close_piece(db, piece)


_BACKFILL_BATCH = 20

# A row Buffer never answers for would otherwise cost one request every tick
# for ever, and a real backlog behind it would never get its turn. Anything
# older than this keeps whatever it has; nothing is lost, it just is not
# chased automatically.
_BACKFILL_LOOKBACK = timedelta(days=60)


async def backfill_links(db: AsyncSession) -> int:
    """Give a published post the address Buffer never told us about.

    Posts sent through the immediate path were never asked for `externalLink`,
    and the reconciler only revisits SCHEDULED rows — so those posts are live
    with nothing to click in the console, and the YouTube view counter, which
    finds its video id in that address, skips them for ever.

    Writes `external_url` and nothing else. A post that already went out is not
    up for re-judgement here: no status, no `published_at`, no `last_error`,
    and no piece is closed. In particular a NOT_FOUND is not a verdict — the
    reconciler may retire a SCHEDULED post on it, but Buffer forgetting a post
    that is already public says nothing about the post.
    """
    if get_settings().BUFFER_SIMULATED:
        return 0

    missing = (
        (
            await db.execute(
                select(ContentPublication)
                .where(
                    ContentPublication.status == PublicationStatus.PUBLISHED,
                    ContentPublication.external_url.is_(None),
                    ContentPublication.external_id.is_not(None),
                    ContentPublication.published_at
                    >= datetime.now(UTC) - _BACKFILL_LOOKBACK,
                )
                .order_by(ContentPublication.id.asc())
                .limit(_BACKFILL_BATCH)
            )
        )
        .scalars()
        .all()
    )
    if not missing:
        return 0

    answers = await _post_states(list(missing), "published posts without a link")
    if answers is None:
        return 0

    linked = 0
    for _alias, row, post, err in answers:
        if err is not None or post is None:
            continue
        if (post.get("status") or "").lower() != _BUFFER_SENT:
            continue
        link = post.get("externalLink")
        if link:
            row.external_url = link
            linked += 1

    if linked:
        await db.commit()
        log.info("Recovered %s publication link(s) from Buffer", linked)
    return linked


# How many drifted posts one tick moves. Each move is two Buffer requests — the
# post is read before it is edited, so a caption corrected by hand is not
# overwritten — and the whole rail draws on the same two windows, a hundred
# per fifteen minutes and two hundred and fifty a day.
# Small on purpose: six drifted posts are back inside their windows within half
# an hour, and the tick that moves them can still afford to ask how the posts
# that were due this morning went.
_REALIGN_BATCH = 4


def _days_outside_window(
    day: date_cls, opens: date_cls, closes: date_cls | None
) -> int:
    """How far outside its window a date falls, in days. Zero means inside.

    The measure `realign_windows` moves by. "Inside or not at all" reads like
    the stricter rule and is in fact the weaker one: `next_free_slot` never
    answers before the window opens, so that rule can only ever refuse a move
    to a date *past* the close — and a post sitting ten days before its window
    is further out than one sitting a day after it.
    """
    if day < opens:
        return (opens - day).days
    if closes is not None and day > closes:
        return (day - closes).days
    return 0


async def realign_windows(db: AsyncSession) -> int:
    """Move a queued post that no longer falls inside its piece's window.

    Returns how many were moved.

    `_from_when` decides a piece's date **once**, when the row is created, and
    until now nothing ever looked again. A window written or corrected after
    the post was queued therefore changed nothing at all: on 16-sep-2026 pieces
    42 and 44 sat on the 18th and the 19th across all three channels, ten and
    sixteen days before their own windows opened, while piece 24 — whose window
    opened on the 19th and closed on the 30th — could not get a slot on YouTube
    or TikTok, because those ten were already spent. The autumn pieces are the
    ones with windows precisely because they perish; the ones sitting in their
    week were the permanent ones.

    The dates handed out here are `_from_when` and `next_free_slot`, the same
    two the creating path uses, so a post moved by this lands exactly where it
    would have landed had the window been there from the start.

    **A window that has already closed is left alone.** There is nowhere inside
    it to move to, and dragging the post to the next free slot would be
    inventing a date the piece never asked for. It stays where it is, the
    reconciler publishes it, and a person can decide whether it should have
    gone out at all — which is a judgement, not a schedule.

    Buffer's side is an `editPost` on `dueAt`, not a cancel and re-queue:
    cancelling is only possible in Buffer's own interface, and a re-queue would
    hand the slot to whatever asked next.
    """
    if get_settings().BUFFER_SIMULATED:
        return 0

    zone = await agency_zone(db)
    if zone is None:
        # Same rule as the creating path: a date computed in the wrong zone is
        # worse than no date, because it looks right.
        return 0

    now = datetime.now(UTC)
    today = now.astimezone(zone).date()

    queued = (
        await db.execute(
            select(ContentPublication, ContentPiece)
            .join(ContentPiece, ContentPiece.id == ContentPublication.piece_id)
            .where(
                ContentPublication.status == PublicationStatus.SCHEDULED,
                ContentPublication.scheduled_at.is_not(None),
                # Only what is still ahead. A post whose hour has passed is the
                # reconciler's business, and moving it would be rewriting
                # history rather than the queue.
                ContentPublication.scheduled_at > now,
                ContentPublication.external_id.is_not(None),
                ContentPiece.publish_window_start.is_not(None),
            )
            .order_by(ContentPublication.id.asc())
        )
    ).all()

    drifted: list[tuple[ContentPublication, ContentPiece]] = []
    for row, piece in queued:
        start = piece.publish_window_start
        end = piece.publish_window_end
        if start is None:  # pragma: no cover - the query already said otherwise
            continue
        if end is not None and end < today:
            continue
        # The stored instant is UTC; the window is a local date. Comparing them
        # in the agency's zone is the whole reason `agency_zone` is read above:
        # a post at 18:30 on the 27th in Denver is the 28th in UTC, and off by
        # one day is exactly the error this function exists to correct.
        assert row.scheduled_at is not None
        local = row.scheduled_at.astimezone(zone).date()
        if local < start or (end is not None and local > end):
            drifted.append((row, piece))

    if not drifted:
        return 0

    moved = 0
    for row, piece in drifted[:_REALIGN_BATCH]:
        post_id = row.external_id or ""
        due_at = await next_free_slot(db, row.platform, zone, _from_when(piece, zone))
        if due_at == row.scheduled_at:
            # The only free slot inside the window is the one it already holds.
            continue

        # A move has to be an improvement, and `next_free_slot` cannot promise
        # one: it walks forward until it finds a free slot and has no upper
        # bound of its own — `_from_when` says where to start, nothing says
        # where to stop — so on a window whose every slot is spent it answers
        # with a date past the close.
        #
        # Without this the post walked. `_free_slots` counts the row's own slot
        # as taken, so the date this handed out last tick is occupied by this
        # very post on the next one, the window is still full, and the answer is
        # one slot further along. Every fifteen minutes, two Buffer requests a
        # time, for as long as the window stayed full — a post drifting away
        # from its window by the machinery meant to bring it back.
        #
        # Measured in days outside the window rather than "inside or not at
        # all": a post ten days early is further out than one a day late, and
        # the move that trades the first for the second is the one the 16-sep
        # incident needed. It also frees the early date for the perishable
        # piece that was waiting for it.
        assert piece.publish_window_start is not None  # the query said so
        local_new = due_at.astimezone(zone).date()
        local_old = row.scheduled_at.astimezone(zone).date()
        if _days_outside_window(
            local_new, piece.publish_window_start, piece.publish_window_end
        ) >= _days_outside_window(
            local_old, piece.publish_window_start, piece.publish_window_end
        ):
            log.warning(
                "Piece %s: no free %s slot closer to its window %s-%s than %s; "
                "leaving it there",
                piece.id, row.platform.value,
                piece.publish_window_start, piece.publish_window_end,
                row.scheduled_at.isoformat() if row.scheduled_at else "?",
            )
            continue

        try:
            current = await read_scheduled_post(post_id)
            # Buffer's ten are a count of scheduled posts and only drop when one
            # is SENT, so a post can go out between the query above and this
            # line. Editing `dueAt` on something already sent — or that Buffer
            # closed with an error — would be rewriting history, and our row
            # would then disagree with what the channel actually published. The
            # reconciler reads it on the next tick and closes it properly.
            state = (current.get("status") or "").lower()
            if state not in _SAFE_TO_RESCHEDULE:
                # A state we know is terminal is ordinary news: the reconciler
                # owns that row. A state we do not recognise at all is not —
                # same call as `reconcile_scheduled` makes, and for the same
                # reason: if Buffer renamed something, every row here stops
                # moving and nothing else would say so.
                if state in _BUFFER_KNOWN_STATES:
                    log.info(
                        "Piece %s: the %s post is %s in Buffer, not moving it",
                        piece.id, row.platform.value, state,
                    )
                else:
                    log.error(
                        "Piece %s: Buffer reports the %s post as %r, which this "
                        "rail does not recognise; not moving it. Somebody has to look.",
                        piece.id, row.platform.value, state or "",
                    )
                continue
            await edit_scheduled_text(
                piece,
                row.platform,
                post_id,
                str(current.get("text") or ""),
                due_at,
            )
        except QuotaReached:
            # Out of requests. The rest keep their dates and this runs again in
            # fifteen minutes; nothing here is urgent to the minute.
            break
        except (BufferRefused, httpx.HTTPError) as exc:
            log.warning(
                "Piece %s: could not move the %s post back inside its window "
                "(%s to %s): %s",
                piece.id, row.platform.value,
                row.scheduled_at, due_at, exc,
            )
            continue

        was = row.scheduled_at
        row.scheduled_at = due_at
        # Committed per row, so the next iteration's `next_free_slot` can see
        # the slot this one just vacated and the one it just took.
        await db.commit()
        moved += 1
        log.info(
            "Piece %s: moved the %s post from %s into its window %s-%s, now %s",
            piece.id, row.platform.value,
            was.isoformat() if was else "?",
            piece.publish_window_start, piece.publish_window_end,
            due_at.isoformat(),
        )

    return moved


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

    # A spent quota is a budget, not a fault of this tenant's data. Until this
    # was caught, `QuotaReached` from the reconcile or the backfill below rose
    # to `run_for_every_org`, which logs "org 1 failed during a sweep" with a
    # traceback — every fifteen minutes, for the fourteen hours of 16-sep,
    # saying "this organization is broken" about a rail that was merely
    # waiting for the clock. One warning and an empty tick is the truth.
    #
    # `realign_windows` is inside for symmetry, not because it can raise: it
    # already stops on its own quota (see its `break`). The org is named
    # because the quota is per API client, not per tenant — every agency in
    # the sweep brakes on the same tick, and N identical lines with no
    # discriminator is worse than the one count this replaced.
    try:
        # Before anything is queued, find out what already went out. A scheduled
        # post is one Buffer holds, so the only way to learn it published — or
        # failed — is to ask. Done first so a piece whose last platform landed
        # this minute is closed before the tick decides what is still owed.
        await reconcile_scheduled(db)

        # And what went out before the queue existed, which nothing else revisits.
        await backfill_links(db)

        # Before anything new claims a slot, and deliberately before the daily
        # cap is read: the day the post was sitting on becomes free in OUR
        # calendar, so the piece that day belongs to can take it as soon as
        # there is room.
        #
        # "As soon as there is room" is the honest half. Buffer's ten are a
        # count of scheduled posts, not of days — a post moved from the 18th to
        # the 28th is still one of the ten, and that count only drops when a
        # post is SENT. So this frees a date, never a Buffer slot, and on a full
        # queue the piece that date belongs to still waits for a send to drain one.
        await realign_windows(db)
    except QuotaReached as exc:
        log.warning("Buffer quota reached (org %s); skipping this tick: %s", get_org_id(), exc)
        return 0

    claimed = await _claimed_today(db)
    if claimed >= settings.CONTENT_PUBLISH_MAX_PER_DAY:
        return 0

    # A date, not an instant: the horizon is counted in days and a few hours
    # either side of midnight cannot change which side of ten days a window
    # falls on, so the agency's zone is not worth a query here.
    horizon = datetime.now(UTC).date() + timedelta(
        days=settings.CONTENT_SCHEDULE_HORIZON_DAYS
    )

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
                    # Buffer holds ten scheduled posts per channel and no
                    # more. A piece whose window opens in six weeks does not
                    # need one of those ten today; spending them that far out
                    # is what filled Instagram to 26 October and then refused
                    # everything behind it. Held here it costs nothing. A
                    # piece with no window is permanent, and permanent means
                    # now — the calculator pieces are the reason that branch
                    # exists and they must not be caught by this.
                    or_(
                        ContentPiece.publish_window_start.is_(None),
                        ContentPiece.publish_window_start <= horizon,
                    ),
                    # Buffer-owned rows are reconciled above, not new work.
                    # Filter before LIMIT or a scheduled backlog starves approvals.
                    or_(
                        *(
                            or_(
                                ~ContentPiece.publications.any(
                                    ContentPublication.platform == platform
                                ),
                                ContentPiece.publications.any(
                                    and_(
                                        ContentPublication.platform == platform,
                                        or_(
                                            ContentPublication.status == PublicationStatus.PENDING,
                                            and_(
                                                ContentPiece.status == ContentStatus.APPROVED,
                                                ContentPublication.status == PublicationStatus.FAILED,
                                            ),
                                        ),
                                    )
                                ),
                            )
                            for platform in configured_channels()
                        )
                    ),
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
        # quota the posts need. Which is why it needs the same guard as the
        # three steps above — it is a Buffer call on the far side of them, and
        # on a tick with nothing to reconcile it is the *first* one.
        try:
            await verify_organization()
        except QuotaReached as exc:
            log.warning(
                "Buffer quota reached (org %s); skipping this tick: %s", get_org_id(), exc
            )
            return 0

    attempted = 0
    for piece in pending:
        try:
            await publish_piece(db, piece.id)
            attempted += 1
        except QuotaReached as exc:
            log.warning("Stopping this publish tick: %s", exc)
            break
        except NotIdentified as exc:
            # NOT ordinary, and the distinction is the whole reason this kind
            # exists: a piece whose caption names no brokerage will be picked
            # up and put back every fifteen minutes for ever, because nothing
            # about it changes on its own. The twin refusal — no link in the
            # caption — is announced a few hundred lines up for exactly this
            # reason, and the sentence there is "a piece held in silence is
            # held forever".
            log.warning("Piece %s names no brokerage, so it is held: %s", piece.id, exc)
            await notify_held_without_brokerage(piece.id, piece.hook or "")
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

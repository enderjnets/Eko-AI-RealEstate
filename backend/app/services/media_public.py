"""The one address a video can be fetched from without a session.

Buffer does not accept bytes. It takes a URL and downloads from it **when the
post goes out** — which, for anything that sits in a queue, is hours or days
after the post was created — and its documentation says not to use signed or
expiring links. So the shape this repo would reach for first, an HMAC link with
a TTL, is the one shape that cannot work: the signature would have expired by
the time Buffer arrived, and the failure would look like a broken video rather
than a broken link.

`api/v1/content.py` opens with the rule this bends: *media is served by a route,
not by static files; an unlisted URL is not access control.* That rule stands,
and this route obeys it — the gate simply is not the address. **The gate is the
piece's status.** Only a piece a person APPROVED (or one already on its way out,
or already out) resolves here; a DRAFT, a REJECTED, a piece that does not exist
and a path that stopped looking like ours all get the same 404. Guessing the
address of an approved video gets you a video a licensed agent decided to
publish to the whole internet; guessing the address of unapproved footage gets
you nothing.

Everything else stays as it was: the authenticated `/api/v1/content/{id}/media`
route is still how the dashboard plays a clip, and it is still scoped by RLS.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.models import ContentPiece, ContentStatus

log = logging.getLogger(__name__)

# Read size for a ranged response. Big enough that a 20 MB video is a few
# hundred iterations, small enough that the single worker never holds a video
# in memory.
CHUNK = 64 * 1024

# The states in which a video is, or is about to be, public anyway.
# PUBLISHING is here because Buffer fetches after the post was created, and
# PUBLISHED because a platform may re-fetch; without them a video would vanish
# mid-publication.
FETCHABLE = frozenset(
    {ContentStatus.APPROVED, ContentStatus.PUBLISHING, ContentStatus.PUBLISHED}
)

# Our own names, and nothing else. Same expression as the authenticated route:
# the stored value is a hex uuid we wrote, but it is about to be joined to a
# filesystem path.
_OUR_NAME = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{2,5}")


async def resolve_public_media(piece_id: int) -> Path | None:
    """The file this piece may be fetched as, or None — never a reason.

    One return value for every refusal on purpose. Telling a stranger apart
    "no such piece" from "that piece is not approved yet" hands them a way to
    enumerate an agency's unpublished work.

    Reads on the bypass engine because a public request carries no organization
    and RLS is default-deny: with the normal session this would find nothing,
    for every piece, forever. The status check above is what stands in for the
    tenant boundary here — and it is stricter, because it is a fact about
    whether a person decided this video should be public at all.
    """
    async with get_bypass_session_factory()() as db:
        piece = (
            await db.execute(
                select(ContentPiece).where(ContentPiece.id == piece_id)
            )
        ).scalar_one_or_none()

        if piece is None or piece.status not in FETCHABLE or not piece.media_path:
            return None
        if not _OUR_NAME.fullmatch(piece.media_path):
            log.error(
                "piece %s has a media_path that is not one of our names (%r); "
                "refusing to serve it",
                piece_id,
                piece.media_path,
            )
            return None

    path = Path(get_settings().CONTENT_MEDIA_DIR) / piece.media_path
    return path if path.is_file() else None


# ── Range requests ───────────────────────────────────────────────────────
# Starlette 0.38's `FileResponse` ignores `Range` and answers 200 with the
# whole body. Most clients cope, but "most" is not a property to bet a
# publication on: media fetchers routinely ask for a byte range, and the
# failure when one insists is a video that looks broken hours after the post
# was created — the hardest kind of bug to trace back to here.
#
# Deliberately only the single-range form, which is the only one media clients
# send. A multi-range request gets the whole file: a server is always allowed
# to ignore `Range`, and building a multipart/byteranges body would be more
# code for a case that does not occur.
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """`(first, last)` inclusive for a satisfiable single range, else None.

    None means "serve the whole file", which is a legal answer to any Range
    request. An unsatisfiable range raises instead: the route answers 416,
    because handing back bytes nobody asked for lets a client believe it got
    what it wanted.
    """
    if not header or size <= 0:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        return None

    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        # `bytes=-N`: the last N bytes.
        length = int(end_text)
        if length == 0:
            raise ValueError("unsatisfiable")
        return max(0, size - length), size - 1

    first = int(start_text)
    if first >= size:
        raise ValueError("unsatisfiable")
    last = int(end_text) if end_text else size - 1
    if last < first:
        raise ValueError("unsatisfiable")
    return first, min(last, size - 1)


async def read_range(path: Path, first: int, last: int) -> AsyncIterator[bytes]:
    """Stream `[first, last]` inclusive, a chunk at a time."""
    import anyio

    remaining = last - first + 1
    async with await anyio.open_file(path, "rb") as handle:
        await handle.seek(first)
        while remaining > 0:
            chunk = await handle.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

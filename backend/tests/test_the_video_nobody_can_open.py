"""A post that went out and is no longer visible says so.

The owner set pieces 52-56 — the "Renting at $X a month" series — to private on
15-sep-2026 because their figures did not reproduce. The rows kept reading
`published` with a live `external_url`, so the count said twenty-three
published where five could not be opened by anybody, and the follow-up comment
pointed at a page from a video nobody can watch.

**The system already knew, six times a day, and threw it away.** The docstring
of `fetch_youtube_stats` has said so since it was written: "a video that was
deleted or made private comes back as a 200 with an empty `items`". The metrics
loop visits every published video every six hours, received that answer forty
times, and recorded it as "no data" rather than as the fact it is.

`status` stays PUBLISHED. It is true, it is about the past, and rewriting it
would lose that these five were public for three days carrying a wrong number.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.content import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    PublicationPlatform,
    PublicationStatus,
)
from app.services import video_metrics
from app.services.tenant_context import org_scope

ORG = 1
TODAY = date(2026, 9, 15)

SEEN = "aaaaaaaaaaa"
HIDDEN = "bbbbbbbbbbb"


async def _seed(piece_id: int, videos: dict[str, int | None]) -> dict[str, int]:
    """One piece, one YouTube publication per video id. Returns their row ids."""
    ids: dict[str, int] = {}
    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPiece(
                id=piece_id,
                org_id=ORG,
                kind=ContentKind.GENERATED,
                language=ContentLanguage.EN,
                hook="whatever it said",
                status="published",
            )
        )
        await db.flush()
        for n, (video_id, withdrawn) in enumerate(videos.items()):
            row = ContentPublication(
                org_id=ORG,
                piece_id=piece_id,
                # The unique constraint is (piece_id, platform), so several
                # YouTube rows need several pieces — or several platforms with
                # a YouTube address, which is what this does. The reader keys
                # off `platform == YOUTUBE`, so only the first is visited;
                # hence one video per piece in these tests.
                platform=list(PublicationPlatform)[n],
                status=PublicationStatus.PUBLISHED,
                external_url=f"https://www.youtube.com/shorts/{video_id}",
                published_at=datetime.now(UTC),
                withdrawn_at=datetime.now(UTC) if withdrawn else None,
            )
            db.add(row)
            await db.flush()
            ids[video_id] = row.id
        await db.commit()
    return ids


async def _row(publication_id: int) -> tuple[str, datetime | None, str | None]:
    async with get_bypass_session_factory()() as db:
        result = (
            await db.execute(
                select(
                    ContentPublication.status,
                    ContentPublication.withdrawn_at,
                    ContentPublication.withdrawn_reason,
                ).where(ContentPublication.id == publication_id)
            )
        ).one()
        status = result[0]
        return (status.value if hasattr(status, "value") else str(status), result[1], result[2])


async def _cleanup(piece_ids: list[int]) -> None:
    async with get_bypass_session_factory()() as db:
        for pid in piece_ids:
            piece = await db.get(ContentPiece, pid)
            if piece is not None:
                await db.delete(piece)
        await db.commit()


def _answers(**by_id: dict[str, int | None]):
    """A stubbed YouTube that answers for some ids and not others."""

    async def fake(ids: list[str], key: str) -> dict[str, dict[str, int | None]]:
        return {k: v for k, v in by_id.items() if k in ids}

    return fake


@pytest.mark.asyncio
async def test_an_id_the_answer_skips_is_marked_not_visible(monkeypatch):
    piece_id = 991_001
    ids = await _seed(piece_id, {SEEN: None})
    hidden_piece = 991_002
    hidden = await _seed(hidden_piece, {HIDDEN: None})

    monkeypatch.setattr(video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "k", False)
    monkeypatch.setattr(
        video_metrics,
        "fetch_youtube_stats",
        _answers(**{SEEN: {"views": 416, "likes": 1, "comments": 1}}),
    )
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                written = await video_metrics.snapshot_youtube(db, today=TODAY)

        # The one that answered got its reading, exactly as before.
        assert written == 1
        assert await _row(ids[SEEN]) == ("published", None, None)

        # The one that did not is not a gap in a chart — it is a video nobody
        # can open, and `status` stays `published` because it was.
        status, withdrawn_at, reason = await _row(hidden[HIDDEN])
        assert status == "published"
        assert withdrawn_at is not None
        assert reason == "not visible on the platform"
    finally:
        await _cleanup([piece_id, hidden_piece])


@pytest.mark.asyncio
async def test_a_failed_call_withdraws_nothing(monkeypatch):
    """The error this must never make.

    An empty answer is what a spent quota, an unreachable host and a key
    restricted to HTTP referrers all return. Marking the whole catalogue
    withdrawn because a key expired would be far worse than the problem being
    fixed — and it would look, from the console, exactly like the platform had
    removed everything.
    """
    piece_id = 991_003
    ids = await _seed(piece_id, {SEEN: None})
    monkeypatch.setattr(video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "k", False)
    monkeypatch.setattr(video_metrics, "fetch_youtube_stats", _answers())
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_youtube(db, today=TODAY) == 0
        assert await _row(ids[SEEN]) == ("published", None, None)
    finally:
        await _cleanup([piece_id])


@pytest.mark.asyncio
async def test_a_video_made_public_again_stops_being_withdrawn(monkeypatch):
    """Otherwise the flag is a one-way door, and the first time somebody
    unhides a piece the count stays wrong in the other direction."""
    piece_id = 991_004
    ids = await _seed(piece_id, {SEEN: 1})  # already marked withdrawn
    monkeypatch.setattr(video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "k", False)
    monkeypatch.setattr(
        video_metrics,
        "fetch_youtube_stats",
        _answers(**{SEEN: {"views": 10, "likes": None, "comments": None}}),
    )
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_youtube(db, today=TODAY) == 1
        assert await _row(ids[SEEN]) == ("published", None, None)
    finally:
        await _cleanup([piece_id])


@pytest.mark.asyncio
async def test_withdrawing_is_not_repeated_every_six_hours(monkeypatch):
    """The stamp is when we first could not see it, not when we last looked.

    Rewriting it on every tick would turn "hidden since the 15th" into "hidden
    since four minutes ago", which is the one question the column exists to
    answer.
    """
    # Two of them, and that is not incidental: the batch has to come back with
    # SOMETHING for an absence to mean anything, which is the same property
    # `test_a_failed_call_withdraws_nothing` guards from the other side.
    visible_piece, hidden_piece = 991_005, 991_006
    seen = await _seed(visible_piece, {SEEN: None})
    hidden = await _seed(hidden_piece, {HIDDEN: None})
    monkeypatch.setattr(video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "k", False)
    monkeypatch.setattr(
        video_metrics,
        "fetch_youtube_stats",
        _answers(**{SEEN: {"views": 1, "likes": None, "comments": None}}),
    )
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await video_metrics.snapshot_youtube(db, today=TODAY)
        _, first, _ = await _row(hidden[HIDDEN])
        assert first is not None
        assert await _row(seen[SEEN]) == ("published", None, None)

        with org_scope(ORG):
            async with get_session_factory()() as db:
                await video_metrics.snapshot_youtube(db, today=TODAY)
        _, second, _ = await _row(hidden[HIDDEN])
        assert second == first
    finally:
        await _cleanup([visible_piece, hidden_piece])

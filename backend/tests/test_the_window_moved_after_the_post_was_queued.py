"""A queued post whose window says it belongs on another day.

Measured in production on 16-sep-2026. `_from_when` decides a piece's date once,
at the moment the row is created, and until this nothing ever looked again — so
a `publish_window_start` written or corrected after the post reached Buffer
changed nothing at all.

What that left on the calendar:

* pieces **42 and 44** held the 18th and the 19th of September on all three
  channels, **ten and sixteen days before their own windows opened** (28-sep and
  5-oct). Both are calculator pieces: permanent, good any week;
* piece **24** — a fall-colour piece whose window opened on the 19th and closed
  on the 30th — had a slot on Instagram alone. YouTube and TikTok refused it
  with `LimitReachedError`, because those ten slots were spent. Piece 25,
  Guanella Pass, lost YouTube the same way.

The pieces with windows are the ones that perish; the ones sitting in their week
were the ones that never expire. That inversion is the whole bug, and it is not
about the horizon guard — `CONTENT_SCHEDULE_HORIZON_DAYS` decides what may be
queued *today* and did its job. This is about what happens to a row afterwards.

Three properties:

* a queued post before or after its window is moved to a slot **inside** it,
  using the same two functions the creating path uses;
* a window that has **already closed** is left alone: there is nowhere inside it
  to go, and the next free slot would be a date the piece never asked for;
* a piece with **no window** is never touched at all. The calculator pieces are
  permanent on purpose, and permanent means now.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.services.buffer_publisher import BufferRefused, realign_windows
from app.services.tenant_context import org_scope

ORG = 1

YT = "6a8f371eccaf649a67208cd0"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _publishing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "BUFFER_SIMULATED", False, raising=False)
    monkeypatch.setattr(s, "BUFFER_ACCESS_TOKEN", "tok", raising=False)
    monkeypatch.setattr(s, "BUFFER_ORG_ID", "org-1", raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_YOUTUBE", YT, raising=False)
    monkeypatch.setattr(s, "CONTENT_ORG_ID", ORG, raising=False)
    monkeypatch.setattr(
        s, "CONTENT_PUBLIC_BASE_URL", "https://panel.example.com", raising=False
    )


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _queued(
    *,
    opens: date | None,
    closes: date | None,
    scheduled_at: datetime,
    status: PublicationStatus = PublicationStatus.SCHEDULED,
) -> tuple[int, int]:
    """One piece with one YouTube post already in Buffer's queue."""
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHING,
            hook="Kenosha Pass belongs on your fall-drive shortlist.",
            script="Aspens turn from the top down.",
            caption="Aspens turn from the top down. denverhomestory.com/fall",
            media_path="a" * 32 + ".mp4",
            approved_by="office",
            publish_window_start=opens,
            publish_window_end=closes,
        )
        db.add(piece)
        await db.flush()
        row = ContentPublication(
            org_id=ORG,
            piece_id=piece.id,
            platform=PublicationPlatform.YOUTUBE,
            status=status,
            external_id="post-1",
            scheduled_at=scheduled_at,
        )
        db.add(row)
        await db.commit()
        return piece.id, row.id


async def _scheduled_at(row_id: int) -> datetime | None:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT scheduled_at FROM content_publications WHERE id=:i"),
                {"i": row_id},
            )
        ).scalar_one()


async def _run() -> int:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            return await realign_windows(db)


def _buffer_that_answers() -> tuple[AsyncMock, AsyncMock]:
    """Buffer's two calls: read the post, then edit it. Both patched."""
    read = AsyncMock(return_value={"id": "post-1", "text": "as queued", "status": "scheduled"})
    edit = AsyncMock(return_value={"id": "post-1"})
    return read, edit


# ───────────────────────── the post that is too early ──────────────────────


@pytest.mark.asyncio
async def test_a_post_queued_before_its_window_is_moved_into_it(
    database_url: str,
) -> None:
    """Pieces 42 and 44, stated as a test: ten days early, on three channels."""
    await _cleanup()
    try:
        opens = date.today() + timedelta(days=10)
        early = datetime.now(UTC) + timedelta(days=2)
        _piece_id, row_id = await _queued(
            opens=opens, closes=opens + timedelta(days=6), scheduled_at=early
        )

        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 1

        assert edit.called, "Buffer was never asked to move the post"
        moved = await _scheduled_at(row_id)
        assert moved is not None and moved != early, "the row kept its old date"
        assert moved.date() >= opens, (
            f"moved to {moved.date()}, still before the window opened on {opens}"
        )
        # And what Buffer was told matches what we recorded. A row that says one
        # thing while the post says another is the failure this whole file is
        # about, one layer down.
        assert edit.await_args is not None
        assert edit.await_args.args[-1] == moved
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_post_keeps_the_words_buffer_currently_holds(
    database_url: str,
) -> None:
    """The caption is read from Buffer, never rebuilt from our own row.

    A caption corrected by hand after the post was queued would otherwise be
    silently overwritten by a function whose entire job is to change a date.
    """
    await _cleanup()
    try:
        opens = date.today() + timedelta(days=10)
        _piece_id, _row_id = await _queued(
            opens=opens,
            closes=opens + timedelta(days=6),
            scheduled_at=datetime.now(UTC) + timedelta(days=2),
        )

        read = AsyncMock(
            return_value={"id": "post-1", "text": "edited by hand", "status": "scheduled"}
        )
        edit = AsyncMock(return_value={"id": "post-1"})
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                await _run()

        assert edit.await_args is not None
        assert "edited by hand" in edit.await_args.args, (
            "the move rewrote the post with our own caption instead of keeping "
            "the words Buffer actually holds"
        )
    finally:
        await _cleanup()


# ──────────────────────── the posts that must be left alone ────────────────


@pytest.mark.asyncio
async def test_a_post_already_inside_its_window_is_not_touched(
    database_url: str,
) -> None:
    """Otherwise the tick would rewrite the whole queue every fifteen minutes."""
    await _cleanup()
    try:
        opens = date.today()
        inside = datetime.now(UTC) + timedelta(days=2)
        await _queued(opens=opens, closes=opens + timedelta(days=20), scheduled_at=inside)

        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0
        assert not edit.called
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_with_no_window_is_never_moved(database_url: str) -> None:
    """The calculator pieces. Permanent means now, and now is wherever it sits."""
    await _cleanup()
    try:
        await _queued(
            opens=None,
            closes=None,
            scheduled_at=datetime.now(UTC) + timedelta(days=40),
        )

        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0
        assert not edit.called
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_window_that_has_already_closed_is_left_where_it_is(
    database_url: str,
) -> None:
    """There is nowhere inside it to move to.

    Dragging the post to the next free slot would invent a date the piece never
    asked for. It stays, the reconciler publishes it, and whether it should have
    gone out at all is a judgement for a person — not a schedule.
    """
    await _cleanup()
    try:
        closed = date.today() - timedelta(days=3)
        late = datetime.now(UTC) + timedelta(days=2)
        _piece_id, row_id = await _queued(
            opens=closed - timedelta(days=7), closes=closed, scheduled_at=late
        )

        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0
        assert not edit.called
        assert await _scheduled_at(row_id) == late
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_post_whose_hour_has_passed_is_the_reconcilers_business(
    database_url: str,
) -> None:
    """Moving it would be rewriting history rather than the queue: Buffer may
    already have sent it, and this tick has not yet asked."""
    await _cleanup()
    try:
        opens = date.today() + timedelta(days=10)
        gone = datetime.now(UTC) - timedelta(hours=2)
        _piece_id, row_id = await _queued(
            opens=opens, closes=opens + timedelta(days=6), scheduled_at=gone
        )

        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0
        assert not edit.called
        assert await _scheduled_at(row_id) == gone
    finally:
        await _cleanup()


# ─────────────────────────── when Buffer says no ───────────────────────────


@pytest.mark.asyncio
async def test_a_refusal_leaves_the_row_saying_what_buffer_still_holds(
    database_url: str,
) -> None:
    """The row must never claim a date the post does not have.

    A silent drift here is worse than the bug being fixed: the calendar in the
    console would be right and the queue at Buffer wrong, and nothing would ever
    disagree out loud.
    """
    await _cleanup()
    try:
        opens = date.today() + timedelta(days=10)
        early = datetime.now(UTC) + timedelta(days=2)
        _piece_id, row_id = await _queued(
            opens=opens, closes=opens + timedelta(days=6), scheduled_at=early
        )

        read, _ = _buffer_that_answers()
        edit = AsyncMock(side_effect=BufferRefused("[NotFoundError] no such post"))
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0

        assert await _scheduled_at(row_id) == early, (
            "the row moved although Buffer refused the edit"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_nothing_is_asked_of_buffer_when_it_is_simulated(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole queue is exercisable end to end with nothing leaving the box."""
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", True, raising=False)
    await _cleanup()
    try:
        opens = date.today() + timedelta(days=10)
        await _queued(
            opens=opens,
            closes=opens + timedelta(days=6),
            scheduled_at=datetime.now(UTC) + timedelta(days=2),
        )
        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0
        assert not read.called and not edit.called
    finally:
        await _cleanup()

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

import logging
import os
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

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
from app.services.buffer_publisher import (
    BufferRefused,
    publish_approved,
    realign_windows,
)
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


# ──────────────────── the window with nowhere left inside it ───────────────


async def _occupy(when: datetime) -> None:
    """Another piece already holding a YouTube slot at that instant."""
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHING,
            hook="Someone else was here first.",
            script="This one holds the slot.",
            caption="This one holds the slot. denverhomestory.com",
            media_path="b" * 32 + ".mp4",
            approved_by="office",
        )
        db.add(piece)
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.YOUTUBE,
                status=PublicationStatus.SCHEDULED,
                external_id="post-held",
                scheduled_at=when,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_a_post_far_outside_a_full_window_still_moves_closer(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Piece 42 of the 16-sep incident, as a test.

    Ten days before its own window, on a window whose every slot is spent. A
    rule of "inside the window or nowhere" leaves it exactly there: published
    ten days early, and still holding the date the perishable piece was waiting
    for. The day after the window closes is not inside it either, but it is
    nine days closer — and it frees the early slot, which is half of what this
    function is for.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_SLOT_YOUTUBE", "17:30", raising=False)
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        only_day = datetime.now(zone).date() + timedelta(days=3)
        await _occupy(
            datetime.combine(only_day, time(17, 30), tzinfo=zone).astimezone(UTC)
        )
        _, row_id = await _queued(
            opens=only_day,
            closes=only_day,
            scheduled_at=datetime.combine(
                only_day + timedelta(days=9), time(17, 30), tzinfo=zone
            ).astimezone(UTC),
        )

        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 1

        assert edit.called, "a post nine days further out was left where it was"
        landed = await _scheduled_at(row_id)
        assert landed is not None
        assert landed.astimezone(zone).date() == only_day + timedelta(days=1)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_post_already_as_close_as_it_can_get_is_left_alone(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The guard itself, and the walk it ends.

    `next_free_slot` has no upper bound, and `_free_slots` counts this row's own
    slot as taken — so the date handed out last tick is occupied by this very
    post on the next one, and the answer is one slot further along. Every
    fifteen minutes, two Buffer requests at a time, a post drifting away from
    its window by the machinery meant to bring it back.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_SLOT_YOUTUBE", "17:30", raising=False)
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        only_day = datetime.now(zone).date() + timedelta(days=3)
        await _occupy(
            datetime.combine(only_day, time(17, 30), tzinfo=zone).astimezone(UTC)
        )
        # Already the best any slot can do: the day after a one-day window whose
        # own slot is spent. The next free one is the day after that, further out.
        _, row_id = await _queued(
            opens=only_day,
            closes=only_day,
            scheduled_at=datetime.combine(
                only_day + timedelta(days=1), time(17, 30), tzinfo=zone
            ).astimezone(UTC),
        )
        before = await _scheduled_at(row_id)

        caplog.set_level(logging.DEBUG, logger="app.services.buffer_publisher")
        read, edit = _buffer_that_answers()
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0

        assert not edit.called, "the post was walked one slot further from its window"
        assert await _scheduled_at(row_id) == before
        assert any(
            "no free" in r.getMessage() and "closer to its window" in r.getMessage()
            for r in caplog.records
        ), [r.getMessage() for r in caplog.records]
    finally:
        await _cleanup()


# ─────────────────── the post Buffer has already let go ────────────────────


@pytest.mark.asyncio
async def test_a_post_buffer_already_sent_is_not_moved(database_url: str) -> None:
    """Buffer's ten only drop when a post is SENT, so one can go out between
    the query that found it drifted and the edit. Editing `dueAt` on something
    already published rewrites history, and our row would then disagree with
    what the channel actually shows. The reconciler closes it properly."""
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        opens = datetime.now(zone).date() + timedelta(days=2)
        _, row_id = await _queued(
            opens=opens,
            closes=opens + timedelta(days=8),
            scheduled_at=datetime.now(UTC) + timedelta(days=20),
        )
        before = await _scheduled_at(row_id)

        read = AsyncMock(
            return_value={"id": "post-1", "text": "as queued", "status": "sent"}
        )
        edit = AsyncMock(return_value={"id": "post-1"})
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0

        assert read.called, "the post's state was never asked for"
        assert not edit.called, "a post Buffer had already sent was edited"
        assert await _scheduled_at(row_id) == before
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_post_buffer_closed_with_an_error_is_not_moved(
    database_url: str,
) -> None:
    """The other half of the same rule: `sent` is not the only state that is
    not in flight, and a post Buffer failed is the reconciler's to close."""
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        opens = datetime.now(zone).date() + timedelta(days=2)
        _, row_id = await _queued(
            opens=opens,
            closes=opens + timedelta(days=8),
            scheduled_at=datetime.now(UTC) + timedelta(days=20),
        )
        read = AsyncMock(
            return_value={"id": "post-1", "text": "as queued", "status": "error"}
        )
        edit = AsyncMock(return_value={"id": "post-1"})
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0
        assert not edit.called
    finally:
        await _cleanup()


# ────────────────────────── and the tick calls it ──────────────────────────


@pytest.mark.asyncio
async def test_the_tick_realigns_before_claiming(database_url: str) -> None:
    """The wiring. A correct `realign_windows` that nothing calls is a
    function, not a fix — and the tick is the only caller it has."""
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        opens = datetime.now(zone).date() + timedelta(days=2)
        await _queued(
            opens=opens,
            closes=opens + timedelta(days=8),
            scheduled_at=datetime.now(UTC) + timedelta(days=20),
        )
        read, edit = _buffer_that_answers()
        s = get_settings()
        with patch.object(s, "CONTENT_PUBLISH_ENABLED", True):
            with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
                with patch(
                    "app.services.buffer_publisher.edit_scheduled_text", new=edit
                ):
                    with patch(
                        "app.services.buffer_publisher.verify_organization",
                        new=AsyncMock(),
                    ):
                        with patch(
                            "app.services.buffer_publisher._send",
                            new=AsyncMock(return_value="post-new"),
                        ):
                            with org_scope(ORG):
                                async with get_session_factory()() as db:
                                    await publish_approved(db)

        assert read.called, "the tick never asked Buffer what it held"
        assert edit.called, "the tick never moved the drifted post"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_post_buffer_is_sending_right_now_is_not_moved(
    database_url: str,
) -> None:
    """The state the reconciler's question and this one answer differently.

    `sending` means "ask again later" when the question is whether the post
    landed. It means "do not touch" when the question is whether it is safe to
    hand it a new date: Buffer may complete the send anyway, and our row would
    then hold a future date for something the channel has already published —
    the piece stuck in PUBLISHING, the panel with no link, and the slot it
    moved to spending real capacity on a post that will never use it.
    """
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        opens = datetime.now(zone).date() + timedelta(days=2)
        _, row_id = await _queued(
            opens=opens,
            closes=opens + timedelta(days=8),
            scheduled_at=datetime.now(UTC) + timedelta(days=20),
        )
        before = await _scheduled_at(row_id)

        read = AsyncMock(
            return_value={"id": "post-1", "text": "as queued", "status": "sending"}
        )
        edit = AsyncMock(return_value={"id": "post-1"})
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0

        assert not edit.called, "a post on its way out was given a new date"
        assert await _scheduled_at(row_id) == before
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_state_buffer_invented_is_loud(
    database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A name this rail does not know is not a row to skip quietly. If Buffer
    renames a state, every row stops moving — the safe direction, but nothing
    else in the system would say so, and the same call is already made a few
    hundred lines up for the same reason."""
    await _cleanup()
    try:
        zone = ZoneInfo("America/Denver")
        opens = datetime.now(zone).date() + timedelta(days=2)
        await _queued(
            opens=opens,
            closes=opens + timedelta(days=8),
            scheduled_at=datetime.now(UTC) + timedelta(days=20),
        )
        caplog.set_level(logging.DEBUG, logger="app.services.buffer_publisher")
        read = AsyncMock(
            return_value={"id": "post-1", "text": "as queued", "status": "parked"}
        )
        edit = AsyncMock(return_value={"id": "post-1"})
        with patch("app.services.buffer_publisher.read_scheduled_post", new=read):
            with patch("app.services.buffer_publisher.edit_scheduled_text", new=edit):
                assert await _run() == 0

        assert not edit.called
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, [r.getMessage() for r in caplog.records]
        assert "parked" in errors[0].getMessage()
    finally:
        await _cleanup()

"""The day a piece goes out, set from the console.

Asked for on 11-oct-2026. Cheesman Park (piece 124) was made for Halloween and
approved on the 11th; the publisher took it on the next tick and queued it for
that same evening, because nothing in the console could say "not before the
29th". The publisher already honoured `publish_window_start` — `_from_when`,
the horizon filter, `realign_windows` — but only the writer ever set it. The
way round it was to edit the caption so the approval fell off, and when that
came too late, to delete three posts in Buffer by hand.

A date is not content, so it has its own route rather than a field on PATCH:

* it never costs the approval: nothing the person approved has changed;
* it works on a queued piece, because `realign_windows` moves the posts Buffer
  still holds (the last test in `test_the_window_moved_after_the_post_was_queued`);
* it refuses what it cannot honour — a day already gone, a day past the
  window's close, a published piece — rather than storing a date nothing will
  act on.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import ContentKind, ContentLanguage, ContentPiece, ContentStatus

ORG = 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — content API tests need live Postgres")
    return url


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


def _in(days: int) -> date:
    # Two days either side of "today" at the least, so a run near midnight
    # cannot land on the other side of the agency's date.
    return date.today() + timedelta(days=days)


async def _seeded(
    status: ContentStatus,
    *,
    opens: date | None = None,
    closes: date | None = None,
    alerted: bool = False,
) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=status,
            hook="Cheesman Park sits on a former cemetery.",
            media_path="b" * 32 + ".mp4",
            approved_by="office@example.com",
            approved_at=datetime.now(UTC),
            publish_window_start=opens,
            publish_window_end=closes,
            window_alerted_at=datetime.now(UTC) if alerted else None,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _stored(piece_id: int) -> ContentPiece:
    async with get_bypass_session_factory()() as db:
        piece = await db.get(ContentPiece, piece_id)
        assert piece is not None
        return piece


async def _put(piece_id: int, value: date | None):
    async with _client() as client:
        return await client.put(
            f"/api/v1/content/{piece_id}/publish-date",
            json={"publish_date": value.isoformat() if value else None},
        )


@pytest.mark.asyncio
async def test_a_date_on_an_approved_piece_keeps_the_approval(
    database_url: str,
) -> None:
    """Piece 124, the way it should have gone: approve, set the 29th, done."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.APPROVED)
        resp = await _put(piece_id, _in(18))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "approved"
        assert body["publish_window_start"] == _in(18).isoformat()
        assert body["approved_by"] == "office@example.com"

        stored = await _stored(piece_id)
        assert stored.publish_window_start == _in(18)
        assert stored.approved_at is not None, "a date cost the approval"

        # And the listing the console reads carries it, or the card cannot
        # say why an approved piece has no posts yet.
        async with _client() as client:
            listed = await client.get("/api/v1/content")
        assert listed.status_code == 200
        mine = [p for p in listed.json() if p["id"] == piece_id]
        assert mine and mine[0]["publish_window_start"] == _in(18).isoformat()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_queued_piece_takes_a_date_and_stays_queued(
    database_url: str,
) -> None:
    """PATCH refuses PUBLISHING; this route must not. It is where a date helps
    most: the posts Buffer holds are moved by `realign_windows`."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.PUBLISHING)
        resp = await _put(piece_id, _in(18))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "publishing"
        assert (await _stored(piece_id)).publish_window_start == _in(18)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_failed_piece_takes_a_date_before_it_is_retried(
    database_url: str,
) -> None:
    """The way back for a piece whose posts were deleted in Buffer: date it,
    Retry, approve — and it waits for its day instead of going out that night."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.FAILED)
        resp = await _put(piece_id, _in(18))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "failed"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_published_piece_is_refused(database_url: str) -> None:
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.PUBLISHED)
        resp = await _put(piece_id, _in(18))
        assert resp.status_code == 409
        assert (await _stored(piece_id)).publish_window_start is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_day_already_gone_is_refused(database_url: str) -> None:
    """`_from_when` would read it as "now": a date that does nothing is worse
    than a refusal, because the card would show it."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.APPROVED)
        resp = await _put(piece_id, _in(-2))
        assert resp.status_code == 422
        assert (await _stored(piece_id)).publish_window_start is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_more_than_a_year_out_is_refused(database_url: str) -> None:
    """`next_free_slot` stops looking after 370 days."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.APPROVED)
        resp = await _put(piece_id, _in(400))
        assert resp.status_code == 422
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_day_past_the_window_close_is_refused(database_url: str) -> None:
    """A fall piece's window has an end. Moving the start past it would leave
    `realign_windows` with nowhere inside to put the post; the close is named
    so the person knows what to pick instead."""
    await _cleanup()
    try:
        piece_id = await _seeded(
            ContentStatus.APPROVED, opens=_in(3), closes=_in(6)
        )
        resp = await _put(piece_id, _in(9))
        assert resp.status_code == 422
        assert _in(6).isoformat() in resp.text
        assert (await _stored(piece_id)).publish_window_start == _in(3)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_new_date_clears_the_old_alert(database_url: str) -> None:
    """`window_alerted_at` stops the alert repeating. Left set, a re-dated
    piece would never be announced for its new window."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.NEEDS_APPROVAL, opens=_in(3), alerted=True)
        resp = await _put(piece_id, _in(18))
        assert resp.status_code == 200, resp.text
        assert (await _stored(piece_id)).window_alerted_at is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_same_date_again_keeps_the_alert(database_url: str) -> None:
    """Saving without changing anything is not a new window."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.NEEDS_APPROVAL, opens=_in(3), alerted=True)
        resp = await _put(piece_id, _in(3))
        assert resp.status_code == 200, resp.text
        assert (await _stored(piece_id)).window_alerted_at is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_null_clears_the_date(database_url: str) -> None:
    """No date means what it always meant: the next free slot."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.APPROVED, opens=_in(5))
        resp = await _put(piece_id, None)
        assert resp.status_code == 200, resp.text
        assert resp.json()["publish_window_start"] is None
        assert (await _stored(piece_id)).publish_window_start is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_saving_a_window_that_already_opened_is_not_refused(
    database_url: str,
) -> None:
    """The card shows the date the piece has. A fall piece whose window opened
    two days ago, saved again unchanged, is not a request for the past."""
    await _cleanup()
    try:
        piece_id = await _seeded(ContentStatus.APPROVED, opens=_in(-2), closes=_in(6))
        resp = await _put(piece_id, _in(-2))
        assert resp.status_code == 200, resp.text
        assert (await _stored(piece_id)).publish_window_start == _in(-2)
    finally:
        await _cleanup()

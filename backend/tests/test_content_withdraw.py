"""Withdraw: take a piece off the calendar without a correction bringing it back.

Reject is not that. Every rejection is read by the correction sweep, which
rewrites and re-renders the piece and puts it back in front of a person — the
right answer to "this video has a defect", the wrong one to "we no longer want
this video". And a queued piece (PUBLISHING) cannot be rejected at all.

On 23-sep-2026 three repeated rent pieces (41, 43, 45) had to come off the
October calendar. 41 was APPROVED, so Reject would have paid for a rewrite of
it; 43 and 45 were PUBLISHING with posts that had never reached Buffer, so
Reject answered 409 and the publisher would have sent them on 6-oct.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    ContentRejection,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — content API tests need live Postgres")
    return url


@pytest.fixture(autouse=True)
async def _clean(database_url: str):
    yield
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _piece(
    status: ContentStatus,
    rows: tuple[tuple[PublicationStatus, str | None], ...] = (),
) -> int:
    platforms = (
        PublicationPlatform.TIKTOK,
        PublicationPlatform.INSTAGRAM,
        PublicationPlatform.YOUTUBE,
    )
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=1,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=status,
            hook="$3,000 a month in rent — buys up to a $408,000 Denver home.",
            caption="Run your own numbers at denverhomestory.com/calculator",
            media_path="piece.mp4",
        )
        db.add(piece)
        await db.flush()
        for platform, (row_status, external_id) in zip(platforms, rows, strict=False):
            db.add(
                ContentPublication(
                    org_id=1,
                    piece_id=piece.id,
                    platform=platform,
                    status=row_status,
                    external_id=external_id,
                    last_error="[LimitReachedError] Scheduled posts limit reached.",
                )
            )
        await db.commit()
        return piece.id


async def _state(piece_id: int) -> tuple[str, list[tuple[str, str | None]], int]:
    async with get_bypass_session_factory()() as db:
        status = (
            await db.execute(
                text("SELECT status FROM content_pieces WHERE id=:i"), {"i": piece_id}
            )
        ).scalar_one()
        rows = (
            await db.execute(
                select(ContentPublication.status, ContentPublication.last_error)
                .where(ContentPublication.piece_id == piece_id)
                .order_by(ContentPublication.id)
            )
        ).all()
        rejections = len(
            (
                await db.execute(
                    select(ContentRejection.id).where(
                        ContentRejection.piece_id == piece_id
                    )
                )
            ).all()
        )
    return status, [(s.value, e) for s, e in rows], rejections


_NEVER_SENT = ((PublicationStatus.PENDING, None),) * 3


@pytest.mark.asyncio
async def test_an_approved_piece_is_withdrawn_without_a_correction() -> None:
    piece_id = await _piece(ContentStatus.APPROVED)
    async with _client() as client:
        res = await client.post(f"/api/v1/content/{piece_id}/withdraw")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"
    assert res.json()["rejected_reason"].startswith("Withdrawn")
    status, _, rejections = await _state(piece_id)
    assert status == "rejected"
    # No ContentRejection row, so the correction sweep has nothing to read:
    # no rewrite, no render, nothing back in the queue.
    assert rejections == 0


@pytest.mark.asyncio
async def test_a_queued_piece_whose_posts_never_reached_buffer_is_withdrawn() -> None:
    piece_id = await _piece(ContentStatus.PUBLISHING, _NEVER_SENT)
    async with _client() as client:
        res = await client.post(f"/api/v1/content/{piece_id}/withdraw")
    assert res.status_code == 200, res.text
    status, rows, rejections = await _state(piece_id)
    assert status == "rejected"
    assert rejections == 0
    # Closed, with the reason on each row: nothing is owed to any platform.
    assert [s for s, _ in rows] == ["failed"] * 3
    assert all(e and e.startswith("withdrawn") for _, e in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "held",
    [
        (PublicationStatus.SCHEDULED, "buffer-post-1"),
        (PublicationStatus.PUBLISHING, None),
        (PublicationStatus.PUBLISHED, "buffer-post-1"),
        # PENDING but Buffer knows it: not provably "never sent".
        (PublicationStatus.PENDING, "buffer-post-1"),
    ],
)
async def test_a_post_buffer_already_has_refuses_the_withdrawal(held) -> None:
    """Buffer would still post it. Only deleting it there stops that."""
    piece_id = await _piece(
        ContentStatus.PUBLISHING,
        ((PublicationStatus.PENDING, None), held, (PublicationStatus.PENDING, None)),
    )
    before = await _state(piece_id)
    async with _client() as client:
        res = await client.post(f"/api/v1/content/{piece_id}/withdraw")
    assert res.status_code == 409, res.text
    assert "Buffer" in res.json()["detail"]
    assert await _state(piece_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ContentStatus.PUBLISHED, ContentStatus.FAILED])
async def test_a_finished_piece_cannot_be_withdrawn(status) -> None:
    piece_id = await _piece(status)
    async with _client() as client:
        res = await client.post(f"/api/v1/content/{piece_id}/withdraw")
    assert res.status_code == 409, res.text
    assert (await _state(piece_id))[0] == status.value


@pytest.mark.asyncio
async def test_reject_still_refuses_a_queued_piece() -> None:
    """The new edge from PUBLISHING is Withdraw's, guarded; Reject keeps its 409."""
    piece_id = await _piece(ContentStatus.PUBLISHING, _NEVER_SENT)
    async with _client() as client:
        res = await client.post(
            f"/api/v1/content/{piece_id}/reject", json={"reason": "not needed"}
        )
    assert res.status_code == 409, res.text
    assert (await _state(piece_id))[0] == "publishing"


@pytest.mark.asyncio
async def test_the_publisher_will_not_send_a_withdrawn_piece() -> None:
    from app.services.content_studio import NotPublishable, ensure_publishable

    piece_id = await _piece(ContentStatus.PUBLISHING, _NEVER_SENT)
    async with _client() as client:
        assert (await client.post(f"/api/v1/content/{piece_id}/withdraw")).is_success
    async with get_bypass_session_factory()() as db:
        with pytest.raises(NotPublishable):
            await ensure_publishable(db, piece_id, resuming=True)

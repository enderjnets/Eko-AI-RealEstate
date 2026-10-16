"""A published piece is sent to the platforms it never reached — within a week.

Piece 136 (the ski legend), 15-oct-2026: `CONTENT_GENERATED_PLATFORMS=instagram`
dropped its YouTube and TikTok rows, both waiting on full Buffer queues, and
closed it on Instagram alone. The setting was emptied again within the hour,
but a PUBLISHED piece was never selected again, so YouTube and TikTok were lost
for good. See `_COMPLETE_LOOKBACK` in `buffer_publisher`.

What is held here:

* a piece out on one platform in the last week, with no row on another it goes
  to, is posted there on the next tick — and only there: the post already out
  is not sent again, and the piece stays PUBLISHED;
* older than the lookback, it is left alone: a channel connected later must not
  pull a backlog of old videos onto it;
* FAILED is a verdict: a refusal on a published piece is not sent again;
* a piece whose window has closed is left alone, as `realign_windows` does;
* a platform the setting does not send the piece to stays unsent.

PUBLISHED itself stays terminal: `test_published_is_terminal` in
`test_content_gate_is_absolute.py` is untouched.
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
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.services.buffer_publisher import publish_approved
from app.services.tenant_context import org_scope

ORG = 1
YT = "6a8f371eccaf649a67208cd0"
TT = "6a8f37efccaf649a6720a2a9"
IG = "6a8f36edccaf649a6720882a"
BROKERAGE = "Engel & Völkers"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "CONTENT_PUBLISH_ENABLED", True, raising=False)
    monkeypatch.setattr(s, "CONTENT_PUBLISH_MAX_PER_DAY", 8, raising=False)
    monkeypatch.setattr(s, "BUFFER_SIMULATED", False, raising=False)
    monkeypatch.setattr(s, "BUFFER_ACCESS_TOKEN", "tok", raising=False)
    monkeypatch.setattr(s, "BUFFER_ORG_ID", "org-1", raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_YOUTUBE", YT, raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_TIKTOK", TT, raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_INSTAGRAM", IG, raising=False)
    monkeypatch.setattr(s, "CONTENT_ORG_ID", ORG, raising=False)
    monkeypatch.setattr(s, "CONTENT_PUBLIC_BASE_URL", "https://panel.example.com", raising=False)
    # The immediate path: a sent post is PUBLISHED at once, so the close runs
    # in the same tick — which is where a completed piece must not be advanced.
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_ENABLED", False, raising=False)
    monkeypatch.setattr(s, "CONTENT_CTA_URL", "", raising=False)
    # Production since 15-oct-2026 13:32 MDT: every platform.
    monkeypatch.setattr(s, "CONTENT_GENERATED_PLATFORMS", "", raising=False)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _brokerage() -> None:
    """The caption gate refuses a piece whose line differs from the agency's,
    and another test may have changed it or never created the row."""
    async with get_bypass_session_factory()() as db:
        row = (await db.execute(text("SELECT id FROM agent_settings WHERE org_id=1"))).first()
        if row is None:
            db.add(AgentSettings(org_id=ORG, brokerage_line=BROKERAGE))
        else:
            await db.execute(
                text("UPDATE agent_settings SET brokerage_line=:v WHERE org_id=1"),
                {"v": BROKERAGE},
            )
        await db.commit()


async def _piece(
    status: ContentStatus = ContentStatus.APPROVED, *, window_end: date | None = None
) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            # How an uploaded legend is stored, and the case that was lost.
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=status,
            hook="They say Arapahoe Basin is the highest ski area in North America.",
            script="What the records say.",
            caption=f"What the records say. denverhomestory.com\n\n{BROKERAGE}",
            media_path="a" * 32 + ".mp4",
            approved_by="office",
            approved_at=datetime.now(UTC) - timedelta(days=2),
            publish_window_end=window_end,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _row(
    piece_id: int, platform: PublicationPlatform, status: PublicationStatus, **kw
) -> None:
    async with get_bypass_session_factory()() as db:
        db.add(ContentPublication(org_id=ORG, piece_id=piece_id, platform=platform, status=status, **kw))
        await db.commit()


async def _published_on_instagram(*, days_ago: float, window_end: date | None = None) -> int:
    piece = await _piece(ContentStatus.PUBLISHED, window_end=window_end)
    await _row(
        piece, PublicationPlatform.INSTAGRAM, PublicationStatus.PUBLISHED,
        external_id="ig-1", published_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    return piece


async def _state(piece_id: int) -> tuple[str, dict[str, str]]:
    async with get_bypass_session_factory()() as db:
        status = (
            await db.execute(text("SELECT status FROM content_pieces WHERE id=:p"), {"p": piece_id})
        ).scalar_one()
        rows = (
            await db.execute(
                text("SELECT platform, status FROM content_publications WHERE piece_id=:p"),
                {"p": piece_id},
            )
        ).all()
        return status, {platform: s for platform, s in rows}


async def _tick(send: AsyncMock) -> set[tuple[int, PublicationPlatform]]:
    """One tick with the wire stubbed. The reads ahead of the selection
    (reconcile, links, windows) are Buffer calls with nothing to do here."""
    with (
        patch("app.services.buffer_publisher.verify_organization", new=AsyncMock()),
        patch("app.services.buffer_publisher.reconcile_scheduled", new=AsyncMock(return_value=0)),
        patch("app.services.buffer_publisher.backfill_links", new=AsyncMock(return_value=0)),
        patch("app.services.buffer_publisher.realign_windows", new=AsyncMock(return_value=0)),
        patch("app.services.buffer_publisher._send", new=send),
    ):
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_approved(db)
    return {(c.args[0].id, c.args[1]) for c in send.await_args_list}


@pytest.mark.asyncio
async def test_the_platforms_it_never_reached_are_posted_and_only_those(database_url: str) -> None:
    await _cleanup()
    await _brokerage()
    try:
        piece = await _published_on_instagram(days_ago=1)
        sent = await _tick(AsyncMock(return_value="post-1"))

        assert sent == {(piece, PublicationPlatform.YOUTUBE), (piece, PublicationPlatform.TIKTOK)}, (
            "Instagram already has it: sending it there again would be a second public post"
        )
        status, rows = await _state(piece)
        assert rows == {"instagram": "published", "youtube": "published", "tiktok": "published"}
        assert status == ContentStatus.PUBLISHED.value, "PUBLISHED is terminal; the piece never moved"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_older_than_a_week_it_is_left_alone(database_url: str) -> None:
    await _cleanup()
    await _brokerage()
    try:
        old = await _published_on_instagram(days_ago=10)
        legend = await _piece()
        sent = await _tick(AsyncMock(return_value="post-1"))

        assert (legend, PublicationPlatform.YOUTUBE) in sent, "the tick did not run at all"
        assert not any(pid == old for pid, _ in sent)
        assert (await _state(old))[1] == {"instagram": "published"}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_refusal_is_a_verdict_and_is_not_sent_again(database_url: str) -> None:
    await _cleanup()
    await _brokerage()
    try:
        piece = await _published_on_instagram(days_ago=1)
        await _row(piece, PublicationPlatform.YOUTUBE, PublicationStatus.PUBLISHED,
                   external_id="yt-1", published_at=datetime.now(UTC))
        await _row(piece, PublicationPlatform.TIKTOK, PublicationStatus.FAILED,
                   last_error="[InvalidInputError] the video was refused")
        legend = await _piece()
        sent = await _tick(AsyncMock(return_value="post-1"))

        assert (legend, PublicationPlatform.YOUTUBE) in sent, "the tick did not run at all"
        assert not any(pid == piece for pid, _ in sent)
        assert (await _state(piece))[1]["tiktok"] == "failed"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_window_that_has_closed_is_left_alone(database_url: str) -> None:
    await _cleanup()
    await _brokerage()
    try:
        perished = await _published_on_instagram(
            days_ago=1, window_end=date.today() - timedelta(days=2)
        )
        legend = await _piece()
        sent = await _tick(AsyncMock(return_value="post-1"))

        assert (legend, PublicationPlatform.YOUTUBE) in sent, "the tick did not run at all"
        assert not any(pid == perished for pid, _ in sent)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_platform_the_setting_does_not_send_it_to_stays_unsent(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With `instagram` set, a generated piece is not owed YouTube or TikTok:
    nothing was lost, and nothing is completed."""
    monkeypatch.setattr(get_settings(), "CONTENT_GENERATED_PLATFORMS", "instagram", raising=False)
    await _cleanup()
    await _brokerage()
    try:
        piece = await _published_on_instagram(days_ago=1)
        other = await _piece()
        sent = await _tick(AsyncMock(return_value="post-1"))

        assert (other, PublicationPlatform.INSTAGRAM) in sent, "the tick did not run at all"
        assert not any(pid == piece for pid, _ in sent)
    finally:
        await _cleanup()

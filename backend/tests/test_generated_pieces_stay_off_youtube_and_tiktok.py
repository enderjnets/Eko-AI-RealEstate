"""Generated pieces only where `CONTENT_GENERATED_PLATFORMS` says; legends everywhere.

Measured on 15-oct-2026, the owner's yes the same day. Denver Home Story's
generated pieces (the template ones: autumn, calculators) drew 5 to 200 views
on YouTube against ~1,000 for the 3D legends he uploads, and they held places
in Buffer's ten per channel while a legend approved for that day waited on
YouTube and TikTok (piece 136). Production sets `instagram`.

What is held here:

* a generated piece goes only to the platforms listed; an uploaded one
  (RECORDED) goes everywhere, whatever the setting says;
* empty — the default — changes nothing, for every other install;
* a typo fails at startup, not on every tick of a loop nobody watches;
* a generated piece already in flight with a YouTube row left PENDING by a full
  queue is released and closes, instead of sitting in PUBLISHING for good;
* a post Buffer already holds is left alone, and keeps the piece open (its
  media URL is served while the piece is PUBLISHING);
* YouTube's category follows `CONTENT_YOUTUBE_CATEGORY_ID`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
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
    build_post_input,
    channels_for,
    publish_approved,
)
from app.services.tenant_context import org_scope

ORG = 1
YT = "6a8f371eccaf649a67208cd0"
TT = "6a8f37efccaf649a6720a2a9"
IG = "6a8f36edccaf649a6720882a"


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
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_ENABLED", False, raising=False)
    monkeypatch.setattr(s, "CONTENT_CTA_URL", "", raising=False)
    monkeypatch.setattr(s, "CONTENT_GENERATED_PLATFORMS", "instagram", raising=False)


def _transient(kind: ContentKind) -> ContentPiece:
    return ContentPiece(org_id=ORG, kind=kind, language=ContentLanguage.EN)


# ─────────────────────────────── no database ───────────────────────────────


def test_a_generated_piece_goes_only_where_the_setting_says() -> None:
    assert channels_for(_transient(ContentKind.GENERATED)) == {PublicationPlatform.INSTAGRAM: IG}


def test_an_uploaded_legend_goes_everywhere_whatever_the_setting() -> None:
    assert set(channels_for(_transient(ContentKind.RECORDED))) == set(PublicationPlatform)


def test_empty_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default, so every other install publishes exactly as before."""
    monkeypatch.setattr(get_settings(), "CONTENT_GENERATED_PLATFORMS", "", raising=False)
    assert set(channels_for(_transient(ContentKind.GENERATED))) == set(PublicationPlatform)


def test_a_mistyped_platform_fails_at_startup() -> None:
    s = get_settings()
    with pytest.raises(ValidationError):
        type(s).model_validate({**s.model_dump(), "CONTENT_GENERATED_PLATFORMS": "instagran"})
    ok = type(s).model_validate({**s.model_dump(), "CONTENT_GENERATED_PLATFORMS": "Instagram, tiktok"})
    assert ok.CONTENT_GENERATED_PLATFORMS == "Instagram, tiktok"


def test_youtubes_category_follows_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    built = build_post_input(YT, PublicationPlatform.YOUTUBE, "b", "u", False, title="t")
    assert built["metadata"]["youtube"]["categoryId"] == "26"
    monkeypatch.setattr(get_settings(), "CONTENT_YOUTUBE_CATEGORY_ID", "19", raising=False)
    built = build_post_input(YT, PublicationPlatform.YOUTUBE, "b", "u", False, title="t")
    assert built["metadata"]["youtube"]["categoryId"] == "19"


# ───────────────────────────── against the database ────────────────────────


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


async def _cleanup() -> None:
    """As in test_the_queue_does_not_outrun_buffer.py: the brokerage line is
    reset too, because the caption gate refuses a piece whose line differs from
    the agency's and another test may have changed it."""
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.execute(
            text("UPDATE agent_settings SET brokerage_line='Engel & Völkers' WHERE org_id=1")
        )
        await db.commit()


async def _piece(kind: ContentKind, status: ContentStatus = ContentStatus.APPROVED) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=kind,
            language=ContentLanguage.EN,
            status=status,
            hook="What a Denver home is worth today.",
            script="Three numbers decide the price.",
            caption="Three numbers decide the price. denverhomestory.com\n\nEngel & Völkers",
            media_path="a" * 32 + ".mp4",
            approved_by="office",
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _row(piece_id: int, platform: PublicationPlatform, status: PublicationStatus, **kw) -> None:
    async with get_bypass_session_factory()() as db:
        db.add(ContentPublication(org_id=ORG, piece_id=piece_id, platform=platform, status=status, **kw))
        await db.commit()


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


async def _tick(send: AsyncMock) -> None:
    with patch("app.services.buffer_publisher.verify_organization", new=AsyncMock()):
        with patch("app.services.buffer_publisher._send", new=send):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    await publish_approved(db)


@pytest.mark.asyncio
async def test_a_generated_piece_is_sent_to_instagram_only(database_url: str) -> None:
    await _cleanup()
    try:
        generated = await _piece(ContentKind.GENERATED)
        legend = await _piece(ContentKind.RECORDED)
        send = AsyncMock(return_value="post-1")
        await _tick(send)

        platforms = {(c.args[0].id, c.args[1]) for c in send.await_args_list}
        assert platforms == {
            (generated, PublicationPlatform.INSTAGRAM),
            (legend, PublicationPlatform.YOUTUBE),
            (legend, PublicationPlatform.TIKTOK),
            (legend, PublicationPlatform.INSTAGRAM),
        }
        status, rows = await _state(generated)
        assert rows == {"instagram": "published"}
        assert status == ContentStatus.PUBLISHED.value, "the piece must close on its one platform"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_youtube_row_left_pending_by_a_full_queue_is_released(database_url: str) -> None:
    """The pieces in flight on the day the setting is turned on."""
    await _cleanup()
    try:
        piece = await _piece(ContentKind.GENERATED, ContentStatus.PUBLISHING)
        await _row(piece, PublicationPlatform.INSTAGRAM, PublicationStatus.PUBLISHED,
                   external_id="ig-1", published_at=datetime.now(UTC))
        await _row(piece, PublicationPlatform.YOUTUBE, PublicationStatus.PENDING,
                   last_error="[LimitReachedError] Scheduled posts limit reached.")
        await _row(piece, PublicationPlatform.TIKTOK, PublicationStatus.PENDING)
        legend = await _piece(ContentKind.RECORDED)
        send = AsyncMock(return_value="post-1")
        await _tick(send)

        sent = {(c.args[0].id, c.args[1]) for c in send.await_args_list}
        assert (legend, PublicationPlatform.YOUTUBE) in sent, "the tick did not run at all"
        assert not any(pid == piece for pid, _ in sent), "nothing is owed to YouTube or TikTok any more"
        status, rows = await _state(piece)
        assert rows == {"instagram": "published"}
        assert status == ContentStatus.PUBLISHED.value
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_post_buffer_already_holds_keeps_the_piece_open(database_url: str) -> None:
    """Booked before the change: it goes out as booked, and until then the piece
    stays in PUBLISHING so its video is still served to Buffer."""
    await _cleanup()
    try:
        piece = await _piece(ContentKind.GENERATED, ContentStatus.PUBLISHING)
        await _row(piece, PublicationPlatform.INSTAGRAM, PublicationStatus.PUBLISHED,
                   external_id="ig-1", published_at=datetime.now(UTC))
        await _row(piece, PublicationPlatform.YOUTUBE, PublicationStatus.SCHEDULED,
                   external_id="yt-1", scheduled_at=datetime.now(UTC) + timedelta(days=3))
        legend = await _piece(ContentKind.RECORDED)
        send = AsyncMock(return_value="post-1")
        await _tick(send)

        sent = {(c.args[0].id, c.args[1]) for c in send.await_args_list}
        assert (legend, PublicationPlatform.YOUTUBE) in sent, "the tick did not run at all"
        assert not any(pid == piece for pid, _ in sent)
        status, rows = await _state(piece)
        assert rows == {"instagram": "published", "youtube": "scheduled"}
        assert status == ContentStatus.PUBLISHING.value
    finally:
        await _cleanup()

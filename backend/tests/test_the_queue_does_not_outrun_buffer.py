"""Buffer's ten slots per channel, and what happens when the queue fills them.

Measured in production on 15-sep-2026, not imagined. The publisher had booked
Instagram out to 26 October — ten scheduled posts, Buffer's whole allowance for
a channel — and everything behind them was refused with `LimitReachedError`.
The refusal arrives per platform, so a full queue did not stop the rail; it
shredded it:

* pieces 33, 34 and 36 were refused on all three channels, went to FAILED, and
  FAILED transitions only to DRAFT — three approved pieces dead until a person
  noticed, and nothing told anybody;
* piece 37 got into Instagram and lost YouTube and TikTok, 38 lost YouTube.
  Both will close as published having gone out on fewer channels than they were
  approved for, because a FAILED row is only retried when somebody re-approves
  the whole piece.

Three properties are held here, and they are one idea from three sides: **the
rail must not spend what it does not have.**

* A window six weeks out does not take a slot today. That is the cause, and
  `CONTENT_SCHEDULE_HORIZON_DAYS` is the whole fix — the rest is damage
  control.
* A full queue is a fact about the calendar, not about the piece, so it leaves
  the platform PENDING the way a quota pause does, and the next tick tries
  again. It must never be FAILED.
* The request quota is read from the header Buffer already sends, and the rail
  stops one short of the edge rather than discovering it with a real post.

The parser returns `(None, None)` rather than zeros for anything it cannot
read, and that is tested on purpose: an unreadable header is not news that the
quota is spent, and treating it as spent would stop publishing over a string.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
    PublicationStatus,
)
from app.services import buffer_publisher
from app.services.buffer_publisher import (
    BufferRefused,
    QuotaReached,
    parse_rate_limit,
    publish_approved,
    slots_are_full,
)
from app.services.tenant_context import org_scope

ORG = 1

YT = "6a8f371eccaf649a67208cd0"
TT = "6a8f37efccaf649a6720a2a9"
IG = "6a8f36edccaf649a6720882a"

#: Buffer's own words, copied off `content_publications.last_error` in
#: production rather than paraphrased. The match is on this string.
FULL = "[LimitReachedError] Scheduled posts limit reached. You have 10 scheduled posts out of 10 allowed."


# ─────────────────────────────── the header ────────────────────────────────


def test_the_real_header_is_read() -> None:
    """Exactly as Buffer sends it: `"100-in-15min"; r=98; t=897`."""
    assert parse_rate_limit('"100-in-15min"; r=98; t=897') == (98, 897)


def test_a_missing_header_is_not_an_empty_quota() -> None:
    """The distinction the rail depends on. `None` means "no news"; zero would
    mean "stop", and a response without the header is not a refusal."""
    assert parse_rate_limit(None) == (None, None)
    assert parse_rate_limit("") == (None, None)


def test_an_unreadable_header_is_not_an_empty_quota_either() -> None:
    assert parse_rate_limit('"100-in-15min"; r=lots; t=897') == (None, None)
    assert parse_rate_limit("something else entirely") == (None, None)


def test_a_header_with_only_a_remainder_still_answers() -> None:
    """Buffer is not promised to send both halves, and the remainder alone is
    the half that decides whether to stop."""
    assert parse_rate_limit('"100-in-15min"; r=3') == (3, None)


# ──────────────────────────── the proactive brake ──────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota() -> Any:
    """Module state, so it must not leak between tests — or between a test and
    the rest of the suite, which is how one exhausted-quota test would stop
    every publisher test that ran after it."""
    buffer_publisher._quota_remaining = None
    buffer_publisher._quota_refills_at = 0.0
    yield
    buffer_publisher._quota_remaining = None
    buffer_publisher._quota_refills_at = 0.0


@pytest.mark.asyncio
async def test_the_rail_stops_before_the_last_requests_are_spent() -> None:
    """No HTTP call at all: the point is not to discover the ceiling."""
    buffer_publisher._quota_remaining = 1
    buffer_publisher._quota_refills_at = buffer_publisher.monotonic() + 600

    with patch("app.services.buffer_publisher.httpx.AsyncClient") as client:
        with pytest.raises(QuotaReached, match="1 Buffer requests left"):
            await buffer_publisher._graphql("query {}", {})
    assert not client.called, "the brake sent the request it was meant to withhold"


@pytest.mark.asyncio
async def test_the_brake_lifts_once_the_window_has_refilled() -> None:
    """A spent window is spent for fifteen minutes, not forever. Holding past
    the refill would be a rail that stops itself permanently."""
    buffer_publisher._quota_remaining = 0
    buffer_publisher._quota_refills_at = buffer_publisher.monotonic() - 1

    sent: list[str] = []

    class _Resp:
        status_code = 200
        headers = {"ratelimit": '"100-in-15min"; r=99; t=900'}

        def json(self) -> dict:
            return {"data": {"ok": True}}

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> _Resp:
            sent.append(url)
            return _Resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        assert await buffer_publisher._graphql("query {}", {}) == {"data": {"ok": True}}
    assert sent, "the brake held past its own refill"
    assert buffer_publisher._quota_remaining == 99


# ───────────────────────── a full queue is not a failure ───────────────────


def test_buffers_own_words_are_recognised() -> None:
    assert slots_are_full(FULL)


def test_the_match_survives_the_casing_buffer_chooses() -> None:
    assert slots_are_full("SCHEDULED POSTS LIMIT REACHED")


def test_an_ordinary_refusal_is_not_mistaken_for_a_full_queue() -> None:
    """The one that must stay FAILED: a caption the platform will refuse again
    tomorrow is about the piece, and leaving it pending would retry it forever."""
    assert not slots_are_full(
        "[InvalidInputError] Instagram posts require at least one image or video."
    )
    assert not slots_are_full("")


# ──────────────────────────── against the database ─────────────────────────


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _publishing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        s, "CONTENT_PUBLIC_BASE_URL", "https://panel.example.com", raising=False
    )
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_ENABLED", False, raising=False)
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_HORIZON_DAYS", 10, raising=False)
    monkeypatch.setattr(s, "CONTENT_CTA_URL", "", raising=False)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.execute(
            text(
                "UPDATE agent_settings SET brokerage_line='Engel & Völkers' "
                "WHERE org_id=1"
            )
        )
        await db.commit()


async def _piece(window: date | None) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.APPROVED,
            hook="What a Denver home is worth today.",
            script="Three numbers decide the price.",
            caption="Three numbers decide the price. denverhomestory.com",
            media_path="a" * 32 + ".mp4",
            approved_by="office",
            publish_window_start=window,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _rows(piece_id: int) -> list[tuple]:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text(
                    "SELECT platform, status, last_error FROM content_publications "
                    "WHERE piece_id=:p ORDER BY platform"
                ),
                {"p": piece_id},
            )
        ).all()


@pytest.mark.asyncio
async def test_a_full_buffer_queue_leaves_the_platform_pending_not_failed(
    database_url: str,
) -> None:
    """The bug that killed three approved pieces, stated as a test.

    FAILED is terminal for a platform — `publish_piece` only releases failed
    rows when a person approves the piece again — so recording a full calendar
    as a content failure loses the piece for good.
    """
    await _cleanup()
    try:
        piece_id = await _piece(None)
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(side_effect=BufferRefused(FULL)),
            ):
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        rows = await _rows(piece_id)
        assert rows, "no publication row was created at all"
        for platform, status, last_error in rows:
            assert status == PublicationStatus.PENDING.value, (
                f"{platform} was recorded as {status}; FAILED here is the death "
                "sentence this test exists to prevent"
            )
            assert "limit reached" in (last_error or "").lower(), (
                "the reason was dropped, so nobody can tell a full queue from "
                "a piece nobody ever tried"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_window_beyond_the_horizon_does_not_take_a_slot_today(
    database_url: str,
) -> None:
    """The cause, not the symptom. Six weeks out is what filled Instagram."""
    await _cleanup()
    try:
        far = await _piece(date.today() + timedelta(days=42))
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(return_value="post-1"),
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        assert not send.called, "a piece six weeks out was handed to Buffer today"
        assert not await _rows(far), "it even claimed a row"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_window_inside_the_horizon_goes_out(database_url: str) -> None:
    """The other half: a horizon that held everything would be a rail that
    never publishes, and would pass the test above just as well."""
    await _cleanup()
    try:
        near = await _piece(date.today() + timedelta(days=2))
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(return_value="post-1"),
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        assert send.called, "a piece due in two days was held back"
        assert await _rows(near)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_with_no_window_is_never_held_by_the_horizon(
    database_url: str,
) -> None:
    """The calculator pieces are permanent and carry no window at all. A
    horizon that caught them would silently stop the only evergreen content
    the channel has."""
    await _cleanup()
    try:
        evergreen = await _piece(None)
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(return_value="post-1"),
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        assert send.called, "a permanent piece was held by a calendar it has no place on"
        assert await _rows(evergreen)
    finally:
        await _cleanup()

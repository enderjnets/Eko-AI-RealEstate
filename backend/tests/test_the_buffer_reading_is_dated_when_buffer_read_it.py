"""The pass that writes Buffer's TikTok and Instagram counts into the scorecard.

The parsing lives in `test_buffer_says_when_it_read_the_number`. This file is
about the one decision the owner made on 18-sep-2026, which is **which day the
number is filed under**.

Asked "if Buffer and a typed number collide on the same day, which wins?" he
said Buffer. That left a second question his answer could not cover: Buffer
refreshes these about once a day, so its answer at noon is a reading it took
the evening before. Filing that under today would say "today: 94" about a count
nobody read today — a correct number in the wrong frame, which is a mistake
this codebase has shipped before. Asked again, he chose to date the reading by
the moment Buffer actually read it.

That has a consequence worth pinning down in a test, because it reverses the
first answer in practice: a number typed today SURVIVES, since Buffer's lands
on an earlier day. Both readings exist, each with its own date and its own
`source`, and the panel shows the newest with both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentMetric,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.services import video_metrics
from app.services.tenant_context import org_scope

ORG = 1
HOOK = "buffer metrics fixture"
POST_ID = "6a991f49b09943182d3b1d20"

#: 21:24 UTC on the 17th. In Denver that is 15:24 on the SAME day — and the
#: point of the test is that the row says the 17th, not the day it ran.
READ_AT = datetime(2026, 9, 17, 21, 24, 2, tzinfo=UTC)


@pytest.fixture
def database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def live_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard that stops a dev install reading the real API is not what is
    under test here, so it is switched off deliberately and visibly."""
    settings = get_settings()
    monkeypatch.setattr(settings, "BUFFER_SIMULATED", False, raising=False)
    monkeypatch.setattr(settings, "BUFFER_ACCESS_TOKEN", "test-token", raising=False)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces WHERE hook = :h"), {"h": HOOK})
        await db.commit()


async def _seed(platform: PublicationPlatform = PublicationPlatform.TIKTOK) -> int:
    """One published post carrying the id Buffer knows it by."""
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook=HOOK,
        )
        db.add(piece)
        await db.flush()
        publication = ContentPublication(
            org_id=ORG,
            piece_id=piece.id,
            platform=platform,
            status=PublicationStatus.PUBLISHED,
            published_at=datetime.now(UTC),
            external_id=POST_ID,
        )
        db.add(publication)
        await db.commit()
        return publication.id


async def _rows(publication_id: int) -> list[ContentMetric]:
    async with get_bypass_session_factory()() as db:
        found = await db.execute(
            select(ContentMetric)
            .where(ContentMetric.publication_id == publication_id)
            .order_by(ContentMetric.captured_on)
        )
        return list(found.scalars())


async def _office_zone() -> ZoneInfo:
    async with get_bypass_session_factory()() as db:
        name = (await db.execute(select(AgentSettings.timezone).limit(1))).scalar_one_or_none()
    return ZoneInfo((name or "").strip() or "America/Denver")


def _answer(values: dict, read_at: datetime | None):
    async def fake(rows):
        return [(row, dict(values), read_at) for row in rows]

    return fake


async def _run(monkeypatch: pytest.MonkeyPatch, values: dict, read_at: datetime | None) -> int:
    monkeypatch.setattr(video_metrics, "read_post_metrics", _answer(values, read_at))
    with org_scope(ORG):
        async with get_session_factory()() as db:
            return await video_metrics.snapshot_buffer(db)


@pytest.mark.asyncio
async def test_the_row_carries_the_day_buffer_read_it_not_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision, asserted against the clock rather than against itself.

    Mutation: swap `read_at.astimezone(zone).date()` for `await agency_today(db)`
    and this goes red — which is the whole reason it is written this way round.
    """
    await _cleanup()
    publication_id = await _seed()
    try:
        written = await _run(monkeypatch, {"views": 94, "likes": 0, "comments": 0}, READ_AT)
        assert written == 1

        rows = await _rows(publication_id)
        assert len(rows) == 1
        expected = READ_AT.astimezone(await _office_zone()).date()
        assert rows[0].captured_on == expected
        assert rows[0].captured_on != datetime.now(await _office_zone()).date(), (
            "the reading was filed under today, which is the mistake this change exists to fix"
        )
        assert rows[0].views == 94
        assert rows[0].source == "buffer_api"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_number_typed_today_survives_the_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consequence of the owner's second answer, said out loud.

    His first answer was "Buffer wins on a collision". It still does — but
    because the two readings land on different days, there is no collision, and
    the one he typed today stays. If that ever stops being true this test says
    so instead of a scorecard quietly losing his correction.
    """
    await _cleanup()
    publication_id = await _seed()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                today = await video_metrics.agency_today(db)
                await video_metrics.record_snapshot(
                    db,
                    org_id=ORG,
                    publication_id=publication_id,
                    captured_on=today,
                    source="manual",
                    values={"views": 120},
                )
                await db.commit()

        await _run(monkeypatch, {"views": 94}, READ_AT)

        rows = await _rows(publication_id)
        by_day = {row.captured_on: row for row in rows}
        assert len(rows) == 2, f"expected the two readings to coexist, got {rows}"
        assert by_day[today].views == 120
        assert by_day[today].source == "manual"
        assert by_day[READ_AT.astimezone(await _office_zone()).date()].source == "buffer_api"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_reading_with_no_read_time_is_not_written_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a timestamp there is no honest day to file under.

    Stamping it with our clock would be exactly the behaviour the change
    removes, so the row is skipped. Mutation: fall back to `agency_today` and
    this goes red.
    """
    await _cleanup()
    publication_id = await _seed()
    try:
        written = await _run(monkeypatch, {"views": 94}, None)
        assert written == 0
        assert await _rows(publication_id) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_nothing_is_written_when_buffer_could_not_be_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` from the reader means the question never got there.

    "No answer" and "the answer is nothing" lead to opposite writes, which is
    why the reader distinguishes them; this is the caller's half of that.
    """
    await _cleanup()
    publication_id = await _seed()

    async def unreachable(rows):
        return None

    try:
        monkeypatch.setattr(video_metrics, "read_post_metrics", unreachable)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_buffer(db) == 0
        assert await _rows(publication_id) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_simulated_install_never_reaches_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dev install must not read live analytics, and an install with no token
    must not spend a pass a day discovering that with a 401."""
    await _cleanup()
    await _seed()
    asked = False

    async def watcher(rows):
        nonlocal asked
        asked = True
        return []

    try:
        monkeypatch.setattr(video_metrics, "read_post_metrics", watcher)
        monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", True, raising=False)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_buffer(db) == 0
        assert asked is False
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_youtube_is_left_to_its_own_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """YouTube answers us directly and is read every few hours. Letting a daily
    Buffer pass overwrite it would make the one platform we can read properly
    the stalest one in the table."""
    await _cleanup()
    publication_id = await _seed(PublicationPlatform.YOUTUBE)
    try:
        assert await _run(monkeypatch, {"views": 94}, READ_AT) == 0
        assert await _rows(publication_id) == []
    finally:
        await _cleanup()


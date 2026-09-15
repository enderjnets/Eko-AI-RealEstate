"""The visit that was a machine fetching its own link preview.

Measured against production on 15-sep-2026. The landing page had 193 sessions
and every one of them read `traffic_class = 'unknown'`, because the classifier
that runs at ingest only knows three things: the explicit QA marker,
`navigator.webdriver`, and nine user-agent signatures. A network rendering a
link preview announces none of the three — it runs a real browser, executes our
JavaScript, and writes a row indistinguishable from a person's.

What gave them away was the clock. Nine sessions landed between one and
thirty-one seconds after the very publication they were tagged with, in pairs,
from Clonee and Boardman — AWS Ireland and AWS Oregon. On a channel with four
subscribers, nobody watches a video and clicks through in one second.

The rule is deliberately two-handed: near the publication AND having done
nothing at all. Dropping the second half would file the first real viewer of a
fast-travelling post as a machine, and that is the error worth avoiding, since
the whole point of the exercise is to stop lying about how many people came.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import LandingSession
from app.models.content import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    PublicationPlatform,
)
from app.services.landing_analytics import (
    PUBLISH_PREVIEW_SECONDS,
    SETTLED_MINUTES,
    classify_publish_previews,
    is_publish_preview,
)
from app.services.tenant_context import org_scope

ORG = 1


# ── The decision, with no database in the way ────────────────────────────


def test_the_measured_previews_are_caught():
    """One to thirty-one seconds, which is what production actually showed."""
    for gap in (1, 2, 4, 5, 6, 10, 11, 14, 15, 29, 31):
        assert is_publish_preview(gap, event_count=1) is True


def test_a_visit_that_did_something_is_left_alone():
    """The half that keeps this honest.

    Somebody can genuinely be first, and on a small channel the first viewer
    may well arrive in seconds. If they scrolled, clicked or typed, the clock
    stops being evidence and they keep their `unknown`.
    """
    assert is_publish_preview(3, event_count=2) is False
    assert is_publish_preview(3, event_count=9) is False


def test_the_window_has_an_edge_and_it_is_inclusive():
    assert is_publish_preview(PUBLISH_PREVIEW_SECONDS, event_count=1) is True
    assert is_publish_preview(PUBLISH_PREVIEW_SECONDS + 1, event_count=1) is False


def test_arriving_just_before_the_stamp_still_counts():
    """A platform fetches the link when the post is created, which can be
    seconds before we write `published_at` — and one piece goes to three
    channels at slightly different times, so the gap is signed both ways."""
    assert is_publish_preview(-14, event_count=1) is True
    assert is_publish_preview(-52, event_count=1) is True
    assert is_publish_preview(-(PUBLISH_PREVIEW_SECONDS + 1), event_count=1) is False


def test_a_visit_with_no_publication_to_compare_against_is_not_judged():
    """Most sessions carry no `utm_content` at all. Absence of evidence."""
    assert is_publish_preview(None, event_count=1) is False
    assert is_publish_preview(None, event_count=0) is False


def test_an_hour_later_is_not_a_preview():
    """The shape of the false positive this rule must never produce: somebody
    who opens the link an hour after the post and reads nothing. They did
    nothing, so half the rule fits — and they are still a person."""
    assert is_publish_preview(3600, event_count=1) is False


# ── The same rule against the database ───────────────────────────────────


async def _seed_piece_and_publication(piece_id: int, published_at: datetime) -> None:
    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPiece(
                id=piece_id,
                org_id=ORG,
                kind=ContentKind.GENERATED,
                language=ContentLanguage.EN,
                hook="whatever the video said",
                status="approved",
            )
        )
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece_id,
                platform=PublicationPlatform.YOUTUBE,
                status="published",
                published_at=published_at,
            )
        )
        await db.commit()


async def _seed_session(
    key: str,
    first_seen: datetime,
    *,
    utm_content: str | None,
    event_count: int,
    max_scroll: int = 0,
    last_seen: datetime | None = None,
) -> int:
    async with get_bypass_session_factory()() as db:
        row = LandingSession(
            org_id=ORG,
            session_key=key,
            first_seen_at=first_seen,
            last_seen_at=last_seen or first_seen,
            source="youtube",
            utm_content=utm_content,
            event_count=event_count,
            max_scroll_pct=max_scroll,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _class_of(session_id: int) -> tuple[str, str | None]:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                select(
                    LandingSession.traffic_class,
                    LandingSession.traffic_class_reason,
                ).where(LandingSession.id == session_id)
            )
        ).one()
        return row[0], row[1]


async def _cleanup(session_ids: list[int], piece_ids: list[int]) -> None:
    async with get_bypass_session_factory()() as db:
        for sid in session_ids:
            row = await db.get(LandingSession, sid)
            if row is not None:
                await db.delete(row)
        for pid in piece_ids:
            piece = await db.get(ContentPiece, pid)
            if piece is not None:
                await db.delete(piece)
        await db.commit()


@pytest.mark.asyncio
async def test_the_preview_pair_is_marked_and_the_reader_is_not():
    """The production shape, end to end: two machines and one person, all three
    tagged with the same piece, all three arriving within seconds of it."""
    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES + 5)
    piece_id = 990_101
    await _seed_piece_and_publication(piece_id, settled)

    clonee = await _seed_session(
        "prev" + "1" * 28, settled + timedelta(seconds=14),
        utm_content=f"piece-{piece_id}", event_count=1,
    )
    boardman = await _seed_session(
        "prev" + "2" * 28, settled + timedelta(seconds=15),
        utm_content=f"piece-{piece_id}", event_count=1,
    )
    a_person = await _seed_session(
        "prev" + "3" * 28, settled + timedelta(seconds=20),
        utm_content=f"piece-{piece_id}", event_count=9, max_scroll=100,
    )

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                marked = await classify_publish_previews(db)

        assert marked == 2
        assert await _class_of(clonee) == ("automated", "publish_preview")
        assert await _class_of(boardman) == ("automated", "publish_preview")
        # The one that read the page keeps its `unknown`. This is the assertion
        # the rule exists to satisfy; the two above are the easy half.
        assert await _class_of(a_person) == ("unknown", None)
    finally:
        await _cleanup([clonee, boardman, a_person], [piece_id])


@pytest.mark.asyncio
async def test_a_visit_still_in_progress_is_left_for_later():
    """A row seen a minute ago has not finished being a visit yet. Judging it
    now would file every slow reader as a machine — they scroll at minute
    three, and by then the verdict is already written."""
    now = datetime.now(UTC)
    piece_id = 990_102
    await _seed_piece_and_publication(piece_id, now)
    fresh = await _seed_session(
        "prev" + "4" * 28, now + timedelta(seconds=5),
        utm_content=f"piece-{piece_id}", event_count=1,
    )

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_publish_previews(db) == 0
        assert await _class_of(fresh) == ("unknown", None)
    finally:
        await _cleanup([fresh], [piece_id])


@pytest.mark.asyncio
async def test_it_never_overwrites_a_verdict_that_knew_more():
    """`test` was set by somebody holding the QA link. This rule is the weakest
    evidence of the three and must not be the last writer to win."""
    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES + 5)
    piece_id = 990_103
    await _seed_piece_and_publication(piece_id, settled)
    ours = await _seed_session(
        "prev" + "5" * 28, settled + timedelta(seconds=3),
        utm_content=f"piece-{piece_id}", event_count=1,
    )
    async with get_bypass_session_factory()() as db:
        row = await db.get(LandingSession, ours)
        row.traffic_class = "test"
        row.traffic_class_reason = "explicit_qa"
        await db.commit()

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_publish_previews(db) == 0
        assert await _class_of(ours) == ("test", "explicit_qa")
    finally:
        await _cleanup([ours], [piece_id])


@pytest.mark.asyncio
async def test_a_session_counts_once_though_the_piece_went_to_three_channels():
    """The same piece publishes to YouTube, TikTok and Instagram, so one
    session joins three publication rows. Production showed exactly this on
    piece 68: without the DISTINCT the count reads three where the truth is
    one, and the operator is told about traffic that does not exist."""
    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES + 5)
    piece_id = 990_104
    await _seed_piece_and_publication(piece_id, settled)
    async with get_bypass_session_factory()() as db:
        for platform in (PublicationPlatform.TIKTOK, PublicationPlatform.INSTAGRAM):
            db.add(
                ContentPublication(
                    org_id=ORG,
                    piece_id=piece_id,
                    platform=platform,
                    status="published",
                    published_at=settled + timedelta(seconds=40),
                )
            )
        await db.commit()

    only_one = await _seed_session(
        "prev" + "6" * 28, settled + timedelta(seconds=14),
        utm_content=f"piece-{piece_id}", event_count=1,
    )
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_publish_previews(db) == 1
        assert await _class_of(only_one) == ("automated", "publish_preview")
    finally:
        await _cleanup([only_one], [piece_id])


@pytest.mark.asyncio
async def test_an_untagged_visit_is_never_touched():
    """173 of the 193 carried no `utm_content` at all. There is nothing to
    compare them against, and silence is not evidence."""
    settled = datetime.now(UTC) - timedelta(minutes=SETTLED_MINUTES + 5)
    piece_id = 990_105
    await _seed_piece_and_publication(piece_id, settled)
    bare = await _seed_session(
        "prev" + "7" * 28, settled + timedelta(seconds=5),
        utm_content=None, event_count=1,
    )
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await classify_publish_previews(db) == 0
        assert await _class_of(bare) == ("unknown", None)
    finally:
        await _cleanup([bare], [piece_id])

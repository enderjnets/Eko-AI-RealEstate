"""Per-video view counts: what the machine reads, and what a person types.

Two things are worth a test here and one of them is easy to get wrong.

The easy one is parsing: our own published Short is
`https://www.youtube.com/shorts/iUThdDk6zBY`, and a parser that only knew
`watch?v=` would return `None` for every video this agency has ever published
while passing every test written around the shape its author was thinking of.

The hard one is the write. `record_snapshot` is a **Core** insert, so the
`before_flush` listener that stamps `org_id` on everything else never runs. A
row without it is refused by the RLS policy, and the failure surfaces as a
permission error nowhere near the cause — so the org is asserted, not assumed.

No test here reaches the network. `fetch_youtube_stats` is exercised against a
stubbed transport; the one real call to Google is the manual verification in
`PROJECT_STATUS.md`, done once, from the VPS, with the owner's key.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
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

ORG_A = 1
ORG_B = 2

HOOK = "video metrics fixture"
VIDEO = "iUThdDk6zBY"


# --------------------------------------------------------------------------
# Reading an address
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # The shape that matters: everything this agency publishes is a Short.
        ("https://www.youtube.com/shorts/iUThdDk6zBY", VIDEO),
        ("https://www.youtube.com/watch?v=iUThdDk6zBY", VIDEO),
        ("https://www.youtube.com/watch?feature=x&v=iUThdDk6zBY", VIDEO),
        ("https://youtu.be/iUThdDk6zBY", VIDEO),
        ("https://www.youtube.com/embed/iUThdDk6zBY", VIDEO),
        # Not YouTube, and the real values from our own two other networks.
        ("https://tiktok.com/@denverhomestory/video/7681687393027558670", None),
        ("https://www.instagram.com/reel/Dc4rd21FZCy/", None),
        ("", None),
        (None, None),
    ],
)
def test_the_id_is_found_in_every_shape_youtube_uses(
    url: str | None, expected: str | None
) -> None:
    assert video_metrics.youtube_video_id(url) == expected


# --------------------------------------------------------------------------
# Reading the counters
# --------------------------------------------------------------------------


def _client(handler) -> None:
    """Point `fetch_youtube_stats` at a transport instead of the internet."""
    real = httpx.AsyncClient

    class Stub(real):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    return Stub


@pytest.mark.asyncio
async def test_counters_come_back_as_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": VIDEO,
                        # Every one of these is a STRING in YouTube's answer.
                        "statistics": {
                            "viewCount": "1420",
                            "likeCount": "37",
                            "commentCount": "4",
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    out = await video_metrics.fetch_youtube_stats([VIDEO], "AIzaTEST")
    assert out == {VIDEO: {"views": 1420, "likes": 37, "comments": 4}}
    assert seen["part"] == "statistics"
    assert seen["id"] == VIDEO


@pytest.mark.asyncio
async def test_a_hidden_counter_is_none_and_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`likeCount` is absent when a channel hides likes.

    `0` would say nobody liked it. `None` says the platform did not tell us,
    which is the truth and reads differently in a chart.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"items": [{"id": VIDEO, "statistics": {"viewCount": "9"}}]}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    out = await video_metrics.fetch_youtube_stats([VIDEO], "AIzaTEST")
    assert out == {VIDEO: {"views": 9, "likes": None, "comments": None}}


@pytest.mark.asyncio
async def test_a_quota_refusal_is_a_gap_and_never_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """403 is the quota wall, and also what a key restricted to HTTP referrers
    returns to a server. Either way a background loop must keep ticking."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "quotaExceeded"}})

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    assert await video_metrics.fetch_youtube_stats([VIDEO], "AIzaTEST") == {}


@pytest.mark.asyncio
async def test_a_deleted_video_answers_200_with_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not an error: YouTube says 200 and an empty list for an id it does not
    have. "No data for this id" is a fact, not a failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    assert await video_metrics.fetch_youtube_stats([VIDEO], "AIzaTEST") == {}


@pytest.mark.asyncio
async def test_a_network_that_never_answers_is_a_gap_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    assert await video_metrics.fetch_youtube_stats([VIDEO], "AIzaTEST") == {}


@pytest.mark.asyncio
async def test_without_a_key_nothing_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mutation this guards: dropping the empty-key check would send a
    keyless request on every tick for ever, and Google answers 400."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    assert await video_metrics.fetch_youtube_stats([VIDEO], "") == {}
    assert called is False


# --------------------------------------------------------------------------
# Writing a snapshot
# --------------------------------------------------------------------------


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM content_pieces WHERE hook = :h"), {"h": HOOK}
        )
        await db.commit()


async def _seed(org_id: int, url: str | None) -> tuple[int, int]:
    """A published YouTube post of one org. Returns (piece_id, publication_id)."""
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=org_id,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook=HOOK,
        )
        db.add(piece)
        await db.flush()
        publication = ContentPublication(
            org_id=org_id,
            piece_id=piece.id,
            platform=PublicationPlatform.YOUTUBE,
            status=PublicationStatus.PUBLISHED,
            published_at=datetime.now(UTC),
            external_url=url,
        )
        db.add(publication)
        await db.commit()
        return piece.id, publication.id


async def _rows(publication_id: int) -> list[ContentMetric]:
    async with get_bypass_session_factory()() as db:
        found = await db.execute(
            select(ContentMetric)
            .where(ContentMetric.publication_id == publication_id)
            .order_by(ContentMetric.id)
        )
        return list(found.scalars())


@pytest.mark.asyncio
async def test_a_snapshot_carries_the_acting_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one that would fail silently.

    A Core insert skips `_stamp_org_id`, so the org has to be written by hand.
    Mutation: drop `org_id=org_id` from `record_snapshot` and this goes red with
    a NOT NULL violation instead of shipping rows nobody can read.
    """
    await _cleanup()
    _, publication_id = await _seed(ORG_A, f"https://www.youtube.com/shorts/{VIDEO}")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": VIDEO, "statistics": {"viewCount": "12", "likeCount": "2"}}
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    monkeypatch.setattr(
        video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "AIzaTEST"
    )
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_youtube(db) == 1
        rows = await _rows(publication_id)
        assert len(rows) == 1
        assert rows[0].org_id == ORG_A
        assert rows[0].views == 12
        assert rows[0].likes == 2
        assert rows[0].comments is None
        assert rows[0].source == "youtube_api"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_same_day_twice_refines_one_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation the plan named: remove `ON CONFLICT` and the second tick
    raises on the unique constraint instead of updating."""
    await _cleanup()
    _, publication_id = await _seed(ORG_A, f"https://www.youtube.com/shorts/{VIDEO}")
    counts = iter(["10", "31"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": VIDEO, "statistics": {"viewCount": next(counts)}}
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    monkeypatch.setattr(
        video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "AIzaTEST"
    )
    day = date(2026, 9, 5)
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                await video_metrics.snapshot_youtube(db, today=day)
            async with get_session_factory()() as db:
                await video_metrics.snapshot_youtube(db, today=day)
        rows = await _rows(publication_id)
        assert len(rows) == 1, "one reading per day, refined rather than repeated"
        assert rows[0].views == 31, "and it is the newer number"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_two_days_are_two_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Which is the whole reason this is a table and not a column: a video
    still being watched a week later is the signal."""
    await _cleanup()
    _, publication_id = await _seed(ORG_A, f"https://www.youtube.com/shorts/{VIDEO}")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"items": [{"id": VIDEO, "statistics": {"viewCount": "5"}}]}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    monkeypatch.setattr(
        video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "AIzaTEST"
    )
    try:
        with org_scope(ORG_A):
            for day in (date(2026, 9, 4), date(2026, 9, 5)):
                async with get_session_factory()() as db:
                    await video_metrics.snapshot_youtube(db, today=day)
        assert len(await _rows(publication_id)) == 2
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_publication_with_no_address_is_skipped_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buffer only started reporting the address recently, so the older posts
    have none and never will. A gap in the past, not a fault in the present."""
    await _cleanup()
    _, publication_id = await _seed(ORG_A, None)
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    monkeypatch.setattr(
        video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "AIzaTEST"
    )
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_youtube(db) == 0
        assert called is False, "and no quota was spent asking about nothing"
        assert await _rows(publication_id) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_without_a_key_the_tick_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _cleanup()
    _, publication_id = await _seed(ORG_A, f"https://www.youtube.com/shorts/{VIDEO}")
    monkeypatch.setattr(video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "  ")
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_youtube(db) == 0
        assert await _rows(publication_id) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_agency_never_reads_or_writes_anothers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B's tick must not touch A's publication, even though both point at the
    same video id — which is exactly what would happen if the query that finds
    publications were not the RLS-scoped session."""
    await _cleanup()
    _, a_publication = await _seed(ORG_A, f"https://www.youtube.com/shorts/{VIDEO}")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"items": [{"id": VIDEO, "statistics": {"viewCount": "77"}}]}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _client(handler))
    monkeypatch.setattr(
        video_metrics.get_settings(), "YOUTUBE_DATA_API_KEY", "AIzaTEST"
    )
    try:
        with org_scope(ORG_B):
            async with get_session_factory()() as db:
                assert await video_metrics.snapshot_youtube(db) == 0
        assert await _rows(a_publication) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_latest_reading_is_the_newest_day() -> None:
    await _cleanup()
    _, publication_id = await _seed(ORG_A, f"https://www.youtube.com/shorts/{VIDEO}")
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                for day, views in ((date(2026, 9, 3), 5), (date(2026, 9, 4), 40)):
                    await video_metrics.record_snapshot(
                        db,
                        org_id=ORG_A,
                        publication_id=publication_id,
                        captured_on=day,
                        source="manual",
                        values={"views": views, "likes": None, "comments": None},
                    )
                await db.commit()
                newest = await video_metrics.latest_metrics(db, [publication_id])
        assert newest[publication_id].views == 40
        assert newest[publication_id].captured_on == date(2026, 9, 4)
    finally:
        await _cleanup()

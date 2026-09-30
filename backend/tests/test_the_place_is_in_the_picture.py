"""A Decoded piece about a place shows real, approved photos of that place.

On 30-sep-2026 Ender rejected piece 103: a Red Rocks video in which Red Rocks
never appeared. He approved twelve Commons photos the same day (Red Rocks, the
Capitol, Larimer Square). These tests hold three things together: which shot
shows which photo, what the caption says about it, and what the render worker
is told — all three from `place_photos.assign`, so none can disagree.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.main import app
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentSeries,
    ContentStatus,
    RenderJob,
    RenderJobKind,
)
from app.services import place_photos
from app.services.content_growth import DECODED_TOPICS_SINCE, growth_source, growth_topic
from app.services.content_writer import DraftPayload, _with_cta
from app.services.place_photos import (
    PHOTOS,
    assign,
    credit_line,
    photos_for_topic,
    shown_in,
)
from app.services.tenant_context import org_scope

ORG = 1
TOKEN = "test-worker-token-place-photos"
RED_ROCKS = growth_topic(ContentSeries.DENVER_DECODED, 4).key
CAPITOL = growth_topic(ContentSeries.DENVER_DECODED, 0).key
LARIMER = growth_topic(ContentSeries.DENVER_DECODED, 2).key
GOVERNOR = growth_topic(ContentSeries.DENVER_DECODED, 1).key


def test_the_twelve_ender_approved_and_nothing_else() -> None:
    assert [p.id for p in PHOTOS] == [
        "R3", "R9", "R7", "R5", "C8", "C15", "C9", "C3", "L2", "L10", "L7", "L4",
    ]
    assert [p.id for p in photos_for_topic(RED_ROCKS)] == ["R3", "R9", "R7", "R5"]
    assert [p.id for p in photos_for_topic(CAPITOL)] == ["C8", "C15", "C9", "C3"]
    assert [p.id for p in photos_for_topic(LARIMER)] == ["L2", "L10", "L7", "L4"]
    assert photos_for_topic(GOVERNOR) == ()
    assert photos_for_topic(None) == ()


def test_the_topics_are_the_places_the_briefs_name() -> None:
    """The keys are positions in `_DECODED`; if that list is reordered, this
    fails before a Capitol photo lands in a Red Rocks video."""
    briefs = {
        RED_ROCKS: growth_topic(ContentSeries.DENVER_DECODED, 4).brief_en,
        CAPITOL: growth_topic(ContentSeries.DENVER_DECODED, 0).brief_en,
        LARIMER: growth_topic(ContentSeries.DENVER_DECODED, 2).brief_en,
    }
    assert "Red Rocks" in briefs[RED_ROCKS]
    assert "Capitol" in briefs[CAPITOL]
    assert "Larimer" in briefs[LARIMER]


def test_no_share_alike_and_no_file_without_its_fingerprint() -> None:
    for photo in PHOTOS:
        assert "SA" not in photo.license
        assert all(c in "0123456789abcdef" for c in photo.sha1)
        assert "?" not in photo.url
        assert photo.page.startswith("https://commons.wikimedia.org/wiki/File:")


def test_a_licence_we_do_not_use_is_refused() -> None:
    with pytest.raises(ValueError):
        place_photos.PlacePhoto(
            id="X", topic=RED_ROCKS, place="Red Rocks", file="File:x.jpg",
            url="https://upload.wikimedia.org/x.jpg", page="p", sha1="0" * 40,
            width=1, height=1, author="a", license="CC BY-SA 4.0", shows="s",
        )


def test_the_place_opens_and_closes_the_video() -> None:
    photos = photos_for_topic(RED_ROCKS)
    shown = assign(6, photos)
    assert shown[0].id == "R3"
    assert shown[5].id == "R9"
    assert sorted(shown) == [0, 2, 3, 5]
    assert {p.id for p in shown.values()} == {"R3", "R9", "R7", "R5"}


def test_fewer_shots_than_photos_uses_one_per_shot() -> None:
    photos = photos_for_topic(RED_ROCKS)
    assert sorted(assign(3, photos)) == [0, 1, 2]
    assert assign(3, photos)[2].id == "R9"
    assert list(assign(1, photos)) == [0]
    assert assign(0, photos) == {}
    assert assign(6, ()) == {}


def test_every_author_credited_once_with_the_licence() -> None:
    shown = assign(6, photos_for_topic(RED_ROCKS))
    line = credit_line(ContentLanguage.EN, shown)
    assert line == (
        "Photos: Carol M. Highsmith (public domain), Maarten Heerlien (CC BY 2.0), "
        "via Wikimedia Commons (cropped)."
    )
    # The 1941 aerial names nobody, and adds nothing.
    assert "1941" not in line


def _draft(scenes: int = 6, caption: str = "Red Rocks is older than you think.") -> DraftPayload:
    return DraftPayload(
        hook="These rocks are older than the mountains they're sitting in.",
        script="A Denver fact about Red Rocks, told in a few sentences.",
        caption=caption,
        scenes=[
            {"visual_prompt": f"Red Rocks Park sandstone, shot {i}", "on_screen_text": "Red Rocks"}
            for i in range(scenes)
        ],
    )


def test_a_video_with_photos_does_not_say_its_images_are_ai() -> None:
    out = _with_cta(
        _draft(), ContentLanguage.EN, series=ContentSeries.DENVER_DECODED,
        photos=photos_for_topic(RED_ROCKS),
    )
    assert out is not None
    assert "Images are AI-generated." not in out.caption
    assert (
        "The photos of Red Rocks are real; the other images are AI-generated."
        in out.caption
    )
    assert "Maarten Heerlien (CC BY 2.0)" in out.caption


def test_without_photos_the_caption_is_what_it_always_was() -> None:
    plain = _with_cta(_draft(), ContentLanguage.EN, series=ContentSeries.DENVER_DECODED)
    assert plain is not None
    assert plain.caption.endswith("Narrated with a synthetic voice. Images are AI-generated.")
    assert "Photos:" not in plain.caption


def test_a_correction_replaces_the_old_lines_rather_than_adding_to_them() -> None:
    """A correction starts from the caption of the draft it corrects, which
    already carries the old disclosure."""
    before = _with_cta(_draft(), ContentLanguage.EN, series=ContentSeries.DENVER_DECODED)
    assert before is not None
    photos = photos_for_topic(RED_ROCKS)
    once = _with_cta(
        _draft(caption=before.caption), ContentLanguage.EN,
        series=ContentSeries.DENVER_DECODED, photos=photos,
    )
    twice = _with_cta(once, ContentLanguage.EN, series=ContentSeries.DENVER_DECODED, photos=photos)
    assert once is not None and twice is not None
    assert "Images are AI-generated." not in once.caption
    assert once.caption.count("Narrated with a synthetic voice.") == 1
    assert once.caption.count("Photos: ") == 1
    assert twice.caption == once.caption


def test_spanish_says_it_in_spanish() -> None:
    out = _with_cta(
        _draft(caption="Red Rocks es más antigua de lo que crees."),
        ContentLanguage.ES, series=ContentSeries.DENVER_DECODED,
        photos=photos_for_topic(RED_ROCKS),
    )
    assert out is not None
    assert "Las fotos de Red Rocks son reales" in out.caption
    assert "Carol M. Highsmith (dominio público)" in out.caption


# ---- against Postgres: which photos a stored piece gets, and the render input


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — this reads pieces from Postgres")
    return url


@pytest.fixture(autouse=True)
def _this_is_our_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_ORG_ID", ORG, raising=False)


@pytest.fixture
def worker_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "RENDER_WORKER_TOKEN", TOKEN, raising=False)
    return TOKEN


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


def _decoded(created_at: datetime, source: dict | None = None, scenes: int = 6) -> ContentPiece:
    return ContentPiece(
        org_id=ORG,
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        status=ContentStatus.DRAFT,
        series=ContentSeries.DENVER_DECODED,
        created_at=created_at,
        source=source,
        hook="A Denver fact",
        script="A Denver fact, told in a few sentences.",
        caption="A caption.",
        scenes={
            "narration": "A Denver fact, told in a few sentences.",
            "scenes": [
                {"visual_prompt": f"Denver shot {i}", "on_screen_text": "Denver"}
                for i in range(scenes)
            ],
        },
    )


@pytest.mark.asyncio
async def test_a_stored_red_rocks_piece_gets_red_rocks(database_url: str) -> None:
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                piece = _decoded(
                    datetime.now(UTC), growth_source(ContentSeries.DENVER_DECODED, 4)
                )
                governor = _decoded(
                    datetime.now(UTC), growth_source(ContentSeries.DENVER_DECODED, 1)
                )
                db.add_all([piece, governor])
                await db.commit()
                shown = await shown_in(db, piece)
                assert {s: p.id for s, p in shown.items()} == {
                    0: "R3", 2: "R7", 3: "R5", 5: "R9",
                }
                assert await shown_in(db, governor) == {}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_97_and_100_get_their_places_back_from_the_count(database_url: str) -> None:
    """Written before the topic was stored: the Capitol first, Larimer third."""
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                pieces = []
                for hours in (1, 2, 3):
                    piece = _decoded(DECODED_TOPICS_SINCE + timedelta(hours=hours))
                    db.add(piece)
                    await db.commit()
                    pieces.append(piece)
                assert (await shown_in(db, pieces[0]))[0].id == "C8"
                assert await shown_in(db, pieces[1]) == {}
                assert (await shown_in(db, pieces[2]))[0].id == "L2"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_worker_is_told_which_shot_shows_which_file(
    database_url: str, worker_token: str
) -> None:
    try:
        async with get_bypass_session_factory()() as db:
            piece = _decoded(
                datetime.now(UTC), growth_source(ContentSeries.DENVER_DECODED, 4)
            )
            db.add(piece)
            await db.commit()
            job = RenderJob(org_id=ORG, piece_id=piece.id, kind=RenderJobKind.PRODUCE_B)
            db.add(job)
            await db.commit()
            job_id = job.id
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"X-Worker-Token": TOKEN},
        ) as client:
            body = (await client.get(f"/api/v1/internal/render-jobs/{job_id}/input")).json()
        by_id = {p.id: p for p in PHOTOS}
        assert [(p["scene"], p["id"]) for p in body["photos"]] == [
            (0, "R3"), (2, "R7"), (3, "R5"), (5, "R9"),
        ]
        for sent in body["photos"]:
            assert sent["url"] == by_id[sent["id"]].url
            assert sent["sha1"] == by_id[sent["id"]].sha1
        # The shot list still travels whole: a photo replaces a drawing in
        # the engine, not a line of the plan.
        assert len(body["scenes"]["scenes"]) == 6
    finally:
        await _cleanup()

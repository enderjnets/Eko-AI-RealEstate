"""What the writer found stays found, through an edit and through Submit.

The console formed its own opinion of a piece with the Fair Housing filter
alone. The writer makes four more kinds of finding — writing in a shot, a
narration in the wrong language, a shot list an image model cannot read, and a
dollar figure the calculator cannot account for — and every one of them was
erased by `_refresh_violations`, which is called by the edit route AND by the
Submit route. So the refusal cleared itself: press Submit on the draft that was
refused and it advanced, with the findings gone from the row.

Measured on piece 74 on 17-sep-2026: refused for a "monitor" that arrives with
words written on it, sitting in DRAFT, one button away from a paid render of
the shot a person had already refused.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import ContentLanguage, ContentStatus
from app.services.content_studio import text_violations
from app.services.content_writer import (
    DraftPayload,
    Scene,
    _all_violations,
    _scene_plan,
    stored_violations,
)

#: The shot list of piece 74, as the row held it. Shot 4 is the one the writer
#: refused; the rest are the same list and are meant to stay silent.
PLAN_74 = {
    "narration": (
        "Launch sets the first signal, and the early window carries the "
        "traffic. A cut reads as a question. Leverage follows the signal. "
        "Start the conversation at Denver Home Story dot com."
    ),
    "scenes": [
        {
            "visual_prompt": (
                "A clean desk surface with a set of keys and a blank, "
                "unbranded sign frame resting against the wall"
            ),
            "on_screen_text": "Launch sets the first signal",
        },
        {
            "visual_prompt": (
                "A monitor displaying abstract trend lines on a graph, no "
                "labels or numbers visible"
            ),
            "on_screen_text": "Days on market is visible",
        },
    ],
}


def _shots(found: list[dict[str, str]]) -> list[dict[str, str]]:
    return [f for f in found if f.get("category") == "shot"]


def test_a_stored_shot_that_arrives_with_writing_is_still_a_finding() -> None:
    found = stored_violations(
        hook="What the first two weeks tell you.",
        script="Price, traffic, and what a cut says to a buyer.",
        caption="The first two weeks are the market talking back.",
        scenes=PLAN_74,
        language=ContentLanguage.EN,
    )
    assert len(_shots(found)) == 1, found
    assert "shot 2" in _shots(found)[0]["phrase"]

    # And the reason the console lost it: this is the filter it used to run,
    # and it has no opinion about a monitor at all.
    assert text_violations(
        hook="What the first two weeks tell you.",
        script="Price, traffic, and what a cut says to a buyer.",
        caption="The first two weeks are the market talking back.",
        scenes=PLAN_74,
        language=ContentLanguage.EN,
    ) == []


def test_a_row_says_exactly_what_the_draft_said() -> None:
    """The adapter is the claim; this is what makes it one function."""
    draft = DraftPayload(
        hook="What the first two weeks tell you.",
        script="Price, traffic, and what a cut says to a buyer.",
        caption="The first two weeks are the market talking back.",
        scenes=[
            Scene(
                visual_prompt=row["visual_prompt"],
                on_screen_text=row["on_screen_text"],
            )
            for row in PLAN_74["scenes"]
        ],
        narration=PLAN_74["narration"],
    )
    assert stored_violations(
        hook=draft.hook,
        script=draft.script,
        caption=draft.caption,
        scenes=_scene_plan(draft),
        language=ContentLanguage.EN,
    ) == _all_violations(draft, ContentLanguage.EN)


def test_a_row_longer_than_the_model_allows_is_still_checked() -> None:
    """A person types through the console; the model's limits are not theirs.

    The validating constructor refuses a script over 4000 characters, and a
    piece that cannot be CHECKED is worse than one that is long: it would be a
    500 in the face of whoever is trying to fix it.
    """
    found = stored_violations(
        hook="h",
        script="word " * 1200,  # 6000 characters, over DraftPayload's limit
        caption="c",
        scenes=PLAN_74,
        language=ContentLanguage.EN,
    )
    assert len(_shots(found)) == 1, found


def test_a_stored_figure_nobody_can_account_for_is_a_finding() -> None:
    found = stored_violations(
        hook="Sellers in this pocket cleared $38,000 over asking.",
        script="That is what the last quarter looked like here.",
        caption="Numbers from the last quarter.",
        scenes=None,
        language=ContentLanguage.EN,
        check=None,
    )
    assert [f for f in found if f.get("category") == "figure"], found


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these routes need live Postgres")
    return url


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _attach_plan(piece_id: int) -> None:
    """What the writer stores, and what neither route would look at."""
    async with get_bypass_session_factory()() as db:
        from app.models import ContentPiece as _Piece

        piece = await db.get(_Piece, piece_id)
        piece.scenes = PLAN_74
        await db.commit()


DRAFT = {
    "kind": "generated",
    "language": "en",
    "hook": "What the first two weeks tell you.",
    "script": "Price, traffic, and what a cut says to a buyer.",
    "caption": "The first two weeks are the market talking back.",
}


@pytest.mark.asyncio
async def test_submit_does_not_launder_a_refused_shot(database_url: str) -> None:
    """The button that cleared the refusal instead of obeying it."""
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=DRAFT)
            assert created.status_code == 201, created.text
            piece_id = created.json()["id"]
            await _attach_plan(piece_id)

            submitted = await client.post(f"/api/v1/content/{piece_id}/submit")
            assert submitted.status_code == 422, submitted.text
            found = submitted.json()["detail"]["violations"]
            assert len(_shots(found)) == 1, found

            # The row itself, not the answer: the findings have to be
            # STORED, because the console reads them from there on the next
            # page load and that is where they were being lost.
            async with get_bypass_session_factory()() as db:
                from app.models import ContentPiece as _Piece

                row = await db.get(_Piece, piece_id)
                assert row.status is ContentStatus.DRAFT
                assert len(_shots(row.violations)) == 1, row.violations
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_edit_does_not_wipe_a_refused_shot(database_url: str) -> None:
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=DRAFT)
            piece_id = created.json()["id"]
            await _attach_plan(piece_id)

            edited = await client.patch(
                f"/api/v1/content/{piece_id}",
                json={"caption": "What the first two weeks are telling you."},
            )
            assert edited.status_code == 200, edited.text
            assert len(_shots(edited.json()["violations"])) == 1, edited.text
    finally:
        await _cleanup()

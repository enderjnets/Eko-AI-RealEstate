"""Lane B: what the writer plans, and what may never reach an image model.

The load-bearing claims:

1. **Fair Housing applies to pictures.** A frame full of one kind of household
   says who is welcome without a sentence anybody could edit in review, so the
   image prompts go through the phrase filter AND a person-descriptor denylist.
2. **The language guard reads what will be SPOKEN.** A correct hook over a
   script in another language is the exact bug this exists for — it cost a
   channel next door days of publishing in the wrong language.
3. **A plan with anything wrong in it stays a DRAFT.** It never walks itself
   into the approval queue, and no video is ever built from it.
4. **The video is made BEFORE approval**, so a person approves the video rather
   than a description of one.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
)
from app.services.content_writer import DraftPayload, Scene, _all_violations, _scene_plan
from app.services.fair_housing import picture_violations
from app.services.lang_guard import wrong_language
from app.services.tenant_context import org_scope

ORG = 1

ENGLISH = (
    "Three numbers decide what your home lists for in Denver this month, and "
    "none of them is what you paid. The first is what similar homes actually "
    "closed at, not what they asked. The second is how long they sat before "
    "they sold. The third is what it costs you to carry the house while you "
    "wait for a better offer than the one in front of you today."
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — lane B tests need live Postgres")
    return url


def _draft(**overrides) -> DraftPayload:
    base = {
        "hook": "What your home is worth today.",
        "script": ENGLISH,
        "caption": "Three numbers decide the price.",
        "narration": ENGLISH,
        "scenes": [
            Scene(visual_prompt="a brick bungalow on a Denver street", on_screen_text="One"),
            Scene(visual_prompt="the Front Range at sunrise", on_screen_text="Two"),
        ],
    }
    base.update(overrides)
    return DraftPayload(**base)


# ── Pictures ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prompt",
    [
        "a young family on the porch of a Denver bungalow",
        "a smiling couple signing documents at a kitchen table",
        "retirees walking through an open house",
        "children playing in the yard",
        "una pareja joven frente a una casa",
        "a professional woman reviewing an offer",
    ],
)
def test_a_prompt_that_draws_people_is_refused(prompt: str) -> None:
    """Housing advertising is regulated in pictures. Every one of these is a
    prompt a model reaches for by default when asked to illustrate a home."""
    assert picture_violations(prompt), f"{prompt!r} was allowed through"


@pytest.mark.parametrize(
    "prompt",
    [
        "a brick bungalow on a tree-lined Denver street",
        "the Front Range at sunrise from a rooftop",
        "keys on a kitchen counter next to a signed document",
        "a for-sale sign in fresh snow",
        "the manor house at the end of a wide street",
        "an empty living room with afternoon light",
    ],
)
def test_a_prompt_of_a_place_or_a_thing_is_allowed(prompt: str) -> None:
    """The other half of the instrument. A denylist that refuses everything is
    a denylist nobody can use — and "manor" must not trip on "man"."""
    assert picture_violations(prompt) == [], f"{prompt!r} was wrongly refused"


@pytest.mark.parametrize(
    "prompt",
    [
        "a well-maintained single-family home with a small yard",
        "a multi-family building on a corner lot",
        "a two-family duplex with separate entrances",
        "the family room after a remodel",
    ],
)
def test_a_property_type_is_not_a_description_of_people(prompt: str) -> None:
    """Caught in production on the very first real generation.

    "single-family home" is how the American real estate industry names a
    detached house. It says nothing about who lives in it, and a filter that
    refuses it refuses a large fraction of every legitimate listing prompt ever
    written — the draft sat in DRAFT waiting for an edit nobody could make,
    because scenes are not editable from the console.
    """
    assert picture_violations(prompt) == [], f"{prompt!r} was wrongly refused"


def test_a_property_type_does_not_launder_a_person() -> None:
    """The exemption removes exactly the compound, nothing more."""
    found = picture_violations("a family standing outside a single-family home")
    assert [v["phrase"] for v in found] == ["family"]


def test_a_draft_wrapped_in_a_code_fence_is_still_a_draft() -> None:
    """Asked for JSON, a model returns JSON — sometimes inside a markdown
    block, because that is how it has seen JSON written a million times. The
    first real rewrite in production was discarded over three backticks."""
    from app.services.content_writer import _parse

    raw = (
        '```json\n{"hook": "h", "script": "s", "caption": "c", '
        '"scenes": [{"visual_prompt": "a street", "on_screen_text": "x"}]}\n```'
    )
    draft = _parse(raw)
    assert draft is not None, "a fenced draft was dropped"
    assert draft.hook == "h"
    assert len(draft.scenes) == 1


def test_the_scene_that_offends_is_named(database_url: str) -> None:
    """A person has to be able to fix it, which means knowing which shot."""
    draft = _draft(
        scenes=[
            Scene(visual_prompt="the Front Range at sunrise", on_screen_text="a"),
            Scene(visual_prompt="a family in the doorway", on_screen_text="b"),
        ]
    )
    found = _all_violations(draft, ContentLanguage.EN)
    assert any(v.get("where") == "scene 2" for v in found), found


def test_the_narration_goes_through_the_filter(database_url: str) -> None:
    """The field the audience HEARS, and the one nobody can edit on screen.

    `narration` and `on_screen_text` arrived with lane B and neither was read
    by the Fair Housing filter, so a script could say "great schools" and
    "perfect for families" out loud, in a published video, with the row
    recording zero findings. Third time this repo has shipped a filter that
    did not cover the live lane.
    """
    draft = _draft(
        narration=(
            "Homes here sit near great schools and a safe neighborhood, "
            "perfect for families who want space and quiet on a wide street."
        )
    )
    found = _all_violations(draft, ContentLanguage.EN)
    phrases = {v["phrase"] for v in found}
    assert {"great schools", "safe neighborhood", "perfect for families"} <= phrases
    assert all(v.get("where") == "narration" for v in found if v["category"] != "language")


def test_the_words_burned_on_screen_go_through_it_too() -> None:
    draft = _draft(
        scenes=[
            Scene(visual_prompt="the Front Range at sunrise", on_screen_text="GREAT SCHOOLS")
        ]
    )
    found = _all_violations(draft, ContentLanguage.EN)
    assert any(v.get("where") == "scene 1 caption" for v in found), found


@pytest.mark.asyncio
async def test_editing_a_piece_cannot_launder_a_scene_finding(
    database_url: str,
) -> None:
    """The recovery path that became a laundering path.

    A person cannot edit scenes — the edit schema has only hook, script and
    caption — so the only thing they can do with a piece held for a bad image
    prompt is change some text or press Submit. Recomputing the findings from
    those three fields WIPED the scene finding, submitted the piece, and the
    worker was then paid to draw the exact prompt the gate had refused.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    try:
        piece_id = await _generated(
            ContentStatus.DRAFT,
            scenes={
                "narration": ENGLISH,
                "scenes": [
                    {"visual_prompt": "a smiling family in the doorway", "on_screen_text": "x"}
                ],
            },
            violations=[
                {"phrase": "family", "category": "people_in_pictures", "where": "scene 1"}
            ],
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            edited = await client.patch(
                f"/api/v1/content/{piece_id}", json={"caption": "A different caption."}
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["violations"], "the scene finding was wiped by an edit"

            submitted = await client.post(f"/api/v1/content/{piece_id}/submit")
        assert submitted.status_code == 422, submitted.text

        async with get_bypass_session_factory()() as db:
            status = (
                await db.execute(
                    text("SELECT status FROM content_pieces WHERE id=:p"), {"p": piece_id}
                )
            ).scalar_one()
        assert status == "draft"
    finally:
        await _cleanup()


# ── Language ─────────────────────────────────────────────────────────────


def test_a_narration_in_the_wrong_language_is_caught() -> None:
    spanish = (
        "Tres números deciden el precio de tu casa en Denver este mes, y "
        "ninguno de ellos es lo que pagaste por ella. El primero es lo que "
        "otras casas parecidas cerraron de verdad, no lo que pedían por ellas."
    )
    assert wrong_language(spanish, "en") is not None
    assert wrong_language(spanish, "es") is None


def test_a_script_that_switches_halfway_is_caught_too() -> None:
    """The case a naive check passes, and the one a model actually produces
    when its instructions and its context disagree."""
    mixed = (
        "Three numbers decide what your home lists for in Denver this month. "
        "El primero es lo que otras casas parecidas cerraron de verdad, y no "
        "lo que pedían por ellas cuando salieron al mercado el mes pasado."
    )
    assert wrong_language(mixed, "en") is not None


def test_a_hook_is_too_short_to_judge() -> None:
    """A guard that guesses on four words rejects correct work."""
    assert wrong_language("What your home is worth today.", "en") is None


def test_the_guard_reads_the_narration_not_the_hook() -> None:
    """The bug this exists for: a correct headline over a script in another
    language, which is exactly what shipped next door."""
    draft = _draft(
        hook="What your home is worth today.",
        narration=(
            "Tres números deciden el precio de tu casa en Denver este mes, y "
            "ninguno es lo que pagaste. El primero es lo que otras casas "
            "parecidas cerraron de verdad, no lo que pedían por ellas."
        ),
    )
    found = _all_violations(draft, ContentLanguage.EN)
    assert any(v["category"] == "language" for v in found), found


def test_a_clean_english_draft_passes_everything() -> None:
    assert _all_violations(_draft(), ContentLanguage.EN) == []


# ── The plan on the row ──────────────────────────────────────────────────


def test_the_plan_keeps_the_narration_separate_from_the_shots() -> None:
    """Named keys, not a list with the narration appended: every reader would
    otherwise have to special-case the last element."""
    plan = _scene_plan(_draft())
    assert set(plan) == {"narration", "scenes"}
    assert len(plan["scenes"]) == 2
    assert plan["scenes"][0]["visual_prompt"].startswith("a brick bungalow")


def test_a_draft_without_a_plan_stores_none() -> None:
    """The older shape still produces a usable draft — a piece somebody films
    — rather than nothing at all."""
    assert _scene_plan(_draft(scenes=[])) is None


# ── The queue ────────────────────────────────────────────────────────────


async def _generated(status: ContentStatus, **kwargs) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=status,
            hook="h",
            script=ENGLISH,
            caption="c",
            scenes=kwargs.get(
                "scenes",
                {"narration": ENGLISH, "scenes": [{"visual_prompt": "a house", "on_screen_text": "x"}]},
            ),
            violations=kwargs.get("violations"),
            media_path=kwargs.get("media_path"),
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _brokerage(value: str = "Engel & Völkers Aspen") -> None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(text("SELECT id FROM agent_settings WHERE org_id=1"))
        ).first()
        if row is None:
            from app.models import AgentSettings

            db.add(AgentSettings(org_id=ORG, brokerage_line=value))
        else:
            await db.execute(
                text("UPDATE agent_settings SET brokerage_line=:v WHERE org_id=1"),
                {"v": value},
            )
        await db.commit()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


@pytest.mark.asyncio
async def test_the_video_is_built_before_a_person_approves(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The product decision, held as a test.

    A generated piece waiting for approval gets its video queued FIRST, so what
    the agent approves is the video rather than a description of one.
    """
    from app.services.content_render import enqueue_generated

    monkeypatch.setattr(get_settings(), "RENDER_WORKER_ENABLED", True, raising=False)
    await _brokerage()
    try:
        piece_id = await _generated(ContentStatus.NEEDS_APPROVAL)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await enqueue_generated(db) == 1
                # And never twice: an image costs money, and the constraint —
                # not care — is what makes a second tick harmless.
                assert await enqueue_generated(db) == 0
        async with get_bypass_session_factory()() as db:
            kind = (
                await db.execute(
                    text("SELECT kind FROM render_jobs WHERE piece_id=:p"),
                    {"p": piece_id},
                )
            ).scalar_one()
        assert kind == "produce_b"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_draft_with_violations_costs_nothing(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No narration and no images for text a person still has to rewrite."""
    from app.services.content_render import enqueue_generated

    monkeypatch.setattr(get_settings(), "RENDER_WORKER_ENABLED", True, raising=False)
    await _brokerage()
    try:
        await _generated(
            ContentStatus.DRAFT,
            violations=[{"phrase": "perfect for families", "category": "familial_status"}],
        )
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await enqueue_generated(db) == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_nothing_is_queued_without_a_brokerage_line(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A narration and six paid images, every 24 hours, forever.

    The worker fails a job with no brokerage line, three failures mark it
    FAILED, and the cooldown re-queues it — so without this check the loop
    never ends and every lap costs money for a video that cannot legally carry
    its identification anyway.
    """
    from app.services.content_render import enqueue_generated

    monkeypatch.setattr(get_settings(), "RENDER_WORKER_ENABLED", True, raising=False)
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE agent_settings SET brokerage_line = '' WHERE org_id = 1")
        )
        await db.commit()
    try:
        await _generated(ContentStatus.NEEDS_APPROVAL)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await enqueue_generated(db) == 0
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "UPDATE agent_settings SET brokerage_line = "
                    "'Engel & Völkers Aspen' WHERE org_id = 1"
                )
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_nothing_is_queued_without_a_worker(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.content_render import enqueue_generated

    monkeypatch.setattr(get_settings(), "RENDER_WORKER_ENABLED", False, raising=False)
    try:
        await _generated(ContentStatus.NEEDS_APPROVAL)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await enqueue_generated(db) == 0
    finally:
        await _cleanup()

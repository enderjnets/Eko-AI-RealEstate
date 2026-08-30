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

"""The writer's two gates, exercised without an LLM in the room.

`generate_reply` is patched everywhere: what is under test is the machinery
around the model — the budget switches, the filter, the single rewrite, and
where a draft lands. The model's own behaviour cannot be tested and is not
trusted; that is why the gates exist.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import ContentKind, ContentLanguage, ContentPiece, ContentStatus
from app.services.content_writer import generate_draft
from app.services.llm import LLMResult
from app.services.tenant_context import org_scope


@pytest.fixture(autouse=True)
def _this_is_our_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Name whose content rail this is, exactly as production has to.

    Every worker on the rail refuses to act for an organization that is not
    the one named — the demo org migration 015 creates is a real tenant in
    every sweep, and it was quietly getting its own daily draft. A test that
    exercises the rail has to say whose it is, like the install does.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "CONTENT_ORG_ID", 1, raising=False)

ORG = 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — content writer tests need live Postgres")
    return url


@pytest.fixture(autouse=True)
def studio_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "CONTENT_STUDIO_ENABLED", True)


def _reply(payload: dict) -> LLMResult:
    return LLMResult(
        text=json.dumps(payload),
        provider="kimi",
        model="test",
        input_tokens=10,
        output_tokens=10,
    )


CLEAN = {
    "hook": "Three things to check before you offer.",
    "script": "Inspection, comparables, and your loan estimate — in that order.",
    "caption": "Save this for your next offer.",
}
DIRTY = {
    "hook": "Perfect for families!",
    "script": "This one is in a safe neighborhood with good schools.",
    "caption": "Ideal para familias.",
}


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


@pytest.mark.asyncio
async def test_a_clean_draft_queues_itself_for_approval(database_url: str) -> None:
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(CLEAN)),
                ):
                    piece = await generate_draft(db)
        assert piece is not None
        assert piece.status is ContentStatus.NEEDS_APPROVAL
        assert piece.violations is None
        assert piece.kind is ContentKind.GENERATED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_violating_draft_gets_one_rewrite_then_queues(
    database_url: str,
) -> None:
    calls: list[list] = []

    async def _model(messages, **kwargs):
        calls.append(messages)
        return _reply(DIRTY if len(calls) == 1 else CLEAN)

    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch("app.services.content_writer.generate_reply", _model):
                    piece = await generate_draft(db)
        assert piece is not None
        assert piece.status is ContentStatus.NEEDS_APPROVAL
        assert len(calls) == 2, "the rewrite was not asked for"
        # The rewrite request names the phrases, so the model has something to
        # fix rather than a vibe to guess at.
        feedback = calls[1][-1]["content"]
        assert "perfect for families" in feedback
        assert "safe neighborhood" in feedback
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_persistently_violating_draft_stays_a_draft(
    database_url: str,
) -> None:
    """It never walks itself into the approval queue.

    A person edits it, with the findings on the row — a human approving a
    flagged draft by accident is exactly the failure the queue must not
    invite.
    """
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(DIRTY)),
                ) as model:
                    piece = await generate_draft(db)
        assert piece is not None
        assert piece.status is ContentStatus.DRAFT
        assert piece.violations, "the findings are the editor's map"
        assert model.await_count == 2, "exactly one rewrite, then stop paying"
        phrases = {v["phrase"] for v in piece.violations}
        assert "perfect for families" in phrases
        assert "ideal para familias" in phrases, (
            "the Spanish caption's violation was missed — both lists always run"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_daily_cap_stops_the_spend(database_url: str) -> None:
    model = AsyncMock(return_value=_reply(CLEAN))
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch("app.services.content_writer.generate_reply", model):
                    made = [await generate_draft(db) for _ in range(5)]
        cap = get_settings().CONTENT_MAX_DRAFTS_PER_DAY
        assert sum(1 for m in made if m is not None) == cap
        assert model.await_count == cap, (
            f"the model was called {model.await_count} times for a cap of {cap} "
            "— the cap has to bound the bill, not just the rows"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_off_switch_means_off(database_url: str, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_STUDIO_ENABLED", False)
    model = AsyncMock(return_value=_reply(CLEAN))
    with org_scope(ORG):
        async with get_session_factory()() as db:
            with patch("app.services.content_writer.generate_reply", model):
                assert await generate_draft(db) is None
    assert model.await_count == 0, "disabled still called the model"


@pytest.mark.asyncio
async def test_garbage_from_the_model_is_dropped_not_raised(
    database_url: str,
) -> None:
    """A generation that crashes the loop stops tomorrow's piece too."""
    bad = LLMResult(text="Sure! Here's your script:", provider="kimi",
                    model="test", input_tokens=1, output_tokens=1)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=bad),
                ):
                    assert await generate_draft(db) is None
        async with get_bypass_session_factory()() as db:
            count = (
                await db.execute(select(ContentPiece.id))
            ).scalars().all()
        assert count == [], "garbage was persisted as a piece"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_provider_outage_is_a_quiet_none(database_url: str) -> None:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            with patch(
                "app.services.content_writer.generate_reply",
                AsyncMock(side_effect=RuntimeError("both providers down")),
            ):
                assert await generate_draft(db) is None


@pytest.mark.asyncio
async def test_languages_alternate_and_topics_rotate(database_url: str) -> None:
    model = AsyncMock(return_value=_reply(CLEAN))
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch("app.services.content_writer.generate_reply", model):
                    first = await generate_draft(db)
                    second = await generate_draft(db)
        assert first is not None and second is not None
        assert {first.language, second.language} == {
            ContentLanguage.EN,
            ContentLanguage.ES,
        }, "two consecutive drafts came out in the same language"
        briefs = [c.args[0][0]["content"] for c in model.await_args_list]
        assert briefs[0] != briefs[1], "the topic did not rotate"
    finally:
        await _cleanup()


# ── The spoken sign-off ──────────────────────────────────────────────────


def _drafted(**over):
    from app.services.content_writer import DraftPayload, Scene

    body = {
        "hook": "What your budget gets you.",
        "script": "Denver moves fast and the numbers move with it.",
        "caption": "The mechanics, in a minute.",
        "scenes": [Scene(visual_prompt="a brick house", on_screen_text="Reality")],
    }
    body.update(over)
    return DraftPayload(**body)


def test_the_sign_off_is_built_from_the_script_not_from_an_empty_field(
    monkeypatch,
) -> None:
    """The trap this closes, measured in production: the model never returns a
    `narration` field — on every generated piece `length(narration)` equals
    `length(script)` exactly, because `_scene_plan` falls back. Appending the
    sign-off to the raw None would have produced a narration consisting of the
    sign-off ALONE: a four-second video saying nothing but "Buying or selling
    in Denver?".
    """
    from app.config import get_settings
    from app.services import content_writer as cw

    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com")
    get_settings.cache_clear()
    try:
        out = cw._with_cta(_drafted(), ContentLanguage.EN, 0)
        assert out.narration is not None
        assert out.narration.startswith("Denver moves fast")
        assert "Denver Home Story dot com" in out.narration
    finally:
        get_settings.cache_clear()


def test_the_filter_reads_the_spoken_sign_off(monkeypatch) -> None:
    """The test that matters. Everything else here is hygiene.

    The sign-off is appended in `_with_cta` precisely because the caller runs
    the Fair Housing filter on what comes back. Move the append anywhere later
    — into `_scene_plan`, or into the worker — and the words a person hears are
    words no filter ever read. This repo has shipped that defect twice.
    """
    from app.config import get_settings
    from app.services import content_writer as cw

    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com")
    get_settings.cache_clear()
    monkeypatch.setattr(
        cw,
        "_SPOKEN_CTA",
        {ContentLanguage.EN: ("Perfect for families. Visit {domain}.",),
         ContentLanguage.ES: ("Perfecto para familias. Visita {domain}.",)},
    )
    try:
        draft = cw._with_cta(_drafted(), ContentLanguage.EN, 0)
        found = cw._all_violations(draft, ContentLanguage.EN)
        assert any("famil" in v["phrase"].lower() for v in found), found
    finally:
        get_settings.cache_clear()


def test_the_sign_off_rotates(monkeypatch) -> None:
    """One line heard thirty times a month is a line people stop hearing."""
    from app.config import get_settings
    from app.services import content_writer as cw

    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com")
    get_settings.cache_clear()
    try:
        said = [
            cw._with_cta(_drafted(), ContentLanguage.EN, i).narration
            for i in range(4)
        ]
        assert said[0] != said[1] != said[2]
        # And it comes back round rather than running out.
        assert said[3] == said[0]
    finally:
        get_settings.cache_clear()


def test_no_site_configured_means_no_spoken_sign_off(monkeypatch) -> None:
    """A site that does not resolve is not advertised — the same gate the
    written CTA already uses, so one switch governs both."""
    from app.config import get_settings
    from app.services import content_writer as cw

    monkeypatch.setenv("CONTENT_CTA_URL", "")
    get_settings.cache_clear()
    try:
        assert cw._with_cta(_drafted(), ContentLanguage.EN, 0).narration is None
    finally:
        get_settings.cache_clear()


def test_a_filmed_clip_gets_no_spoken_sign_off(monkeypatch) -> None:
    """No scene plan, no generated narration to sign off."""
    from app.config import get_settings
    from app.services import content_writer as cw

    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com")
    get_settings.cache_clear()
    try:
        assert cw._with_cta(_drafted(scenes=[]), ContentLanguage.EN, 0).narration is None
    finally:
        get_settings.cache_clear()


def test_the_spoken_domain_cannot_drift_from_the_real_one() -> None:
    """Written as words so nothing strips it — which also means nothing checks
    it. If the domain ever changes and the spoken form does not, this is what
    notices."""
    from app.services import content_writer as cw

    for language, spoken in cw._SPOKEN_DOMAIN.items():
        said = spoken.lower().replace(" dot ", ".").replace(" punto ", ".")
        assert said.replace(" ", "") == "denverhomestory.com", (language, spoken)

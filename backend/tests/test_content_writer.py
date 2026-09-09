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


# ── Which language the video comes out in ───────────────────────────────


async def _set_languages(
    content: list[str], chat: list[str] | None = None
) -> tuple[list[str], list[str]]:
    """Write the org's two language lists and return what was there.

    Through the bypass session, because this is the test wearing the owner's
    hat rather than the API's: in a fresh database the row may not exist yet,
    and `_get_or_create` lives in the router. The caller restores in a
    `finally` with the pair this returns — left behind, a `["en", "es"]` from
    one test makes the next one alternate depending on file order.
    """
    from app.models import AgentSettings

    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
        ).scalar_one_or_none()
        if row is None:
            row = AgentSettings(org_id=ORG)
            db.add(row)
            await db.flush()
        before = (list(row.content_languages), list(row.languages))
        row.content_languages = content
        if chat is not None:
            row.languages = chat
        await db.commit()
        return before


@pytest.mark.asyncio
async def test_the_video_language_is_not_the_chat_language(database_url: str) -> None:
    """Measured in production: the agency answers Spanish speakers in Spanish
    (`languages` = ["en", "es"]) and wants every video in English. The writer
    took turns over the CHAT list, so every other daily draft came out Spanish
    and the owner rejected all three by hand — pieces 13, 15 and 20, each a
    generation paid for a decision.
    """
    model = AsyncMock(return_value=_reply(CLEAN))
    before = await _set_languages(["en"], chat=["en", "es"])
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch("app.services.content_writer.generate_reply", model):
                    first = await generate_draft(db)
                    second = await generate_draft(db)
        assert first is not None and second is not None
        assert (first.language, second.language) == (
            ContentLanguage.EN,
            ContentLanguage.EN,
        ), "a draft came out in a language the agency only answers chat in"
        briefs = [c.args[0][0]["content"] for c in model.await_args_list]
        assert briefs[0] != briefs[1], "the topic did not rotate"
    finally:
        await _set_languages(*before)
        await _cleanup()


@pytest.mark.asyncio
async def test_an_agency_that_asks_for_two_languages_gets_them_in_turns(
    database_url: str,
) -> None:
    model = AsyncMock(return_value=_reply(CLEAN))
    before = await _set_languages(["en", "es"])
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
    finally:
        await _set_languages(*before)
        await _cleanup()


@pytest.mark.asyncio
async def test_an_agency_that_never_opened_settings_gets_english(
    database_url: str,
) -> None:
    """The fallback literal in `_language_for` IS the language for a tenant
    with no settings row, so it is asserted on its own — and through a SECOND
    call, because the old fallback `["en", "es"]` also answers English to the
    first one and only shows its hand on the next.
    """
    from app.models.organization import STATUS_ACTIVE, Organization
    from app.services.content_writer import _language_for

    slug = "content-language-probe"
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM organizations WHERE slug = :s"), {"s": slug})
        org = Organization(name="Content Language Probe", slug=slug, status=STATUS_ACTIVE)
        db.add(org)
        await db.commit()
        org_id = org.id
    try:
        with org_scope(org_id):
            async with get_session_factory()() as db:
                assert await _language_for(db) is ContentLanguage.EN
                db.add(
                    ContentPiece(
                        kind=ContentKind.GENERATED,
                        language=ContentLanguage.EN,
                        status=ContentStatus.DRAFT,
                    )
                )
                await db.commit()
                assert await _language_for(db) is ContentLanguage.EN, (
                    "with one English piece already made, the next draft "
                    "switched language for an agency that never asked for two"
                )
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM content_pieces WHERE org_id = :o"), {"o": org_id}
            )
            await db.execute(text("DELETE FROM organizations WHERE slug = :s"), {"s": slug})
            await db.commit()


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


# ── The shot list is machine input, and the machine reads English ────────


# Verbatim from piece 20 in production (2026-09-08), a Spanish educational
# piece whose six `visual_prompt`s were all Spanish. Synthetic strings would
# have let me pick words that make the guard look good; these are what the
# model actually wrote.
_REAL_SPANISH_PROMPTS = [
    "Un cartel de se vende frente a una casa en Denver",
    "Un sobre cerrado y unas llaves sobre una mesa de madera",
    "Documentos de contrato inmobiliario sobre una mesa",
    "Un formulario con casillas de verificación de contingencias",
    "Una puerta principal con cerradura y unas llaves en la mano",
    "Un escritorio con documentos y un teléfono sobre la mesa",
]

# Verbatim from piece 19, the English piece rendered the same night.
_REAL_ENGLISH_PROMPTS = [
    "A residential contract document on a kitchen counter, pen nearby",
    "A brick home with a for-sale sign in front, autumn light",
    "A laptop screen showing an email inbox with pending messages",
    "A stack of closing documents next to a set of house keys",
    "A calendar page showing circled dates and handwritten notes",
    "A phone screen displaying text messages with an agent",
]

_SPANISH_SCRIPT = (
    "El depósito de seriedad es un cheque que entregas al abrir una "
    "transacción para demostrar que vas en serio. Lo maneja una compañía de "
    "título o tu corredor, y se aplica a tu cierre. Si la compra se cae sin "
    "una contingencia activa, ese dinero puede quedarse del otro lado."
)


def _scenes(prompts):
    from app.services.content_writer import Scene

    return [
        Scene(visual_prompt=prompt, on_screen_text=f"Escena {index}")
        for index, prompt in enumerate(prompts, start=1)
    ]


def test_a_spanish_shot_list_is_a_violation_even_on_a_spanish_piece() -> None:
    """The defect this closes ran for two months and cost real money.

    The Spanish system prompt asked for the whole JSON in Spanish, so every
    Spanish piece sent Spanish `visual_prompt`s to fal.ai. fal does not refuse
    those — it answers 200 with a picture of something else. The video renders,
    the length checks pass, and the wrong image goes out under a licensed
    brokerage's name. There is no error anywhere to notice.

    The piece stays a DRAFT with the reason on the row, which is the right
    severity: nothing is lost, no narration and no images are bought, and a
    person sees why.

    Mutation: delete the `wrong_language(prompts, "en")` block in
    `_all_violations` → green with the exact data that shipped the bug.
    """
    from app.services import content_writer as cw

    draft = _drafted(script=_SPANISH_SCRIPT, scenes=_scenes(_REAL_SPANISH_PROMPTS))
    found = cw._all_violations(draft, ContentLanguage.ES)

    scenes_language = [
        v for v in found if v.get("where") == "scenes" and v["category"] == "language"
    ]
    assert scenes_language, found


def test_an_english_shot_list_on_a_spanish_piece_is_exactly_right() -> None:
    """The other half, and the one that stops the fix being "reject Spanish".

    A Spanish piece with English `visual_prompt`s is the CORRECT shape: the
    words a viewer reads stay Spanish, and the words an image model reads are
    English. If this went red the guard would be rejecting the thing it exists
    to produce.

    The Fair Housing filter does not weaken by the switch, and that is checked
    rather than assumed: `find_violations` takes a `language` and ignores it on
    purpose, and `PEOPLE_IN_PICTURES` lists both languages' terms.
    """
    from app.services import content_writer as cw

    draft = _drafted(script=_SPANISH_SCRIPT, scenes=_scenes(_REAL_ENGLISH_PROMPTS))
    found = cw._all_violations(draft, ContentLanguage.ES)

    assert not [v for v in found if v.get("where") == "scenes"], found


def test_the_english_denylist_still_bites_under_a_spanish_piece() -> None:
    """An English prompt under an ES piece must not slip the picture filter.

    This is the regression the switch could plausibly have caused — English
    words checked against a Spanish list — and the reason it does not is worth
    pinning: both lists always run, whatever `language` says.
    """
    from app.services import content_writer as cw

    prompts = list(_REAL_ENGLISH_PROMPTS)
    prompts[0] = "A family smiling on the porch of a brick home"
    draft = _drafted(script=_SPANISH_SCRIPT, scenes=_scenes(prompts))
    found = cw._all_violations(draft, ContentLanguage.ES)

    assert any(v["category"] == "people_in_pictures" for v in found), found

"""Three things borrowed from instagram-agent-skill (MIT), made to fit a brokerage.

Ender asked for them on 10-oct-2026 after an audit of the pack: the hook
formulas, the rule that a caption's point has to fit before Instagram's "more",
and the phrases that read as machine-written. The pack is written for a creator
talking to camera ("$18,000 is what one clause cost me"); a synthetic narrator
for two licensed agents may not invent a number, a date or a personal story, so
only the formulas that need none of those came across.
"""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from app.models import ContentLanguage, ContentSeries
from app.services.content_craft import (
    CAPTION_PREVIEW_CHARS,
    HOOK_FORMULAS,
    caption_opening,
    caption_opening_finding,
    hook_formula_for,
    machine_phrase_findings,
)
from app.services.content_writer import (
    _AI_DISCLOSURE,
    _CTA,
    _SOCIAL_CTA,
    _SPOKEN_CTA,
    _system_for,
    stored_violations,
)
from app.services.llm import LLMResult

#: The caption piece 119 (Sloan's Lake, 3D) went out with on 10-oct-2026. Its
#: first sentence is 210 characters: in the feed, the elephant never shows.
SLOANS_CAPTION = (
    "Sloan's Lake from above, in 3D: the farmer who supposedly flooded his own "
    "field overnight, the amusement park on the north shore, Roger the elephant "
    "and the supermarket parking lot he is said to be buried under. The legends, "
    "and what the records say.\n\nFollow for more Denver, decoded."
)


# --- hook formulas ---------------------------------------------------------------


def test_no_formula_asks_the_narrator_for_a_story_it_does_not_have() -> None:
    first_person = re.compile(r"\b(?:I|me|my|we|our|us)\b")
    for formula in HOOK_FORMULAS:
        for text in (formula.template, formula.example):
            assert not first_person.search(text), (formula.key, text)


def test_no_formula_needs_a_figure_the_brief_did_not_give() -> None:
    for formula in HOOK_FORMULAS:
        assert "$" not in formula.template and "%" not in formula.template, formula.key


def test_every_written_series_gets_a_formula_and_the_rotation_moves() -> None:
    for series in (
        ContentSeries.CONVERSION,
        ContentSeries.DENVER_DECODED,
        ContentSeries.DENVER_WEEKEND,
        ContentSeries.DENVER_MARKET_NO_HYPE,
    ):
        chosen = {hook_formula_for(series, i).key for i in range(12)}
        assert len(chosen) >= 3, (series, chosen)
        for i in range(12):
            assert series in hook_formula_for(series, i).series


def test_recorded_answers_get_no_formula() -> None:
    assert hook_formula_for(ContentSeries.ASK_DENVER_HOME_STORY, 0) is None


def _result(payload: dict) -> LLMResult:
    return LLMResult(text=json.dumps(payload), provider="test", model="test",
                     input_tokens=0, output_tokens=0)


def _topic():
    from app.services.content_topics import SELLER, Topic

    return Topic(key="t", brief_en="Write about appraisals.",
                 brief_es="Escribe sobre tasaciones.", audience=SELLER)


def _clean_reply() -> LLMResult:
    return _result({
        "hook": "Nobody tells you the appraisal can come in under your offer.",
        "script": "Denver appraisals follow recent sales.",
        "caption": "What happens when the appraisal comes in low.",
    })


def _sent(asked: AsyncMock) -> str:
    return "\n".join(str(m["content"]) for m in asked.await_args.args[0])


@pytest.mark.asyncio
async def test_the_draft_is_asked_for_one_named_formula() -> None:
    from app.services.content_writer import _ask

    asked = AsyncMock(return_value=_clean_reply())
    formula = hook_formula_for(ContentSeries.CONVERSION, 4)
    with patch("app.services.content_writer.generate_reply", asked):
        await _ask(_topic(), ContentLanguage.EN, hook_index=4)
    sent = _sent(asked)
    assert formula.name in sent and formula.template in sent
    assert "never invent" in sent.lower()


@pytest.mark.asyncio
async def test_without_an_index_nothing_about_formulas_is_sent() -> None:
    from app.services.content_writer import _ask

    asked = AsyncMock(return_value=_clean_reply())
    with patch("app.services.content_writer.generate_reply", asked):
        await _ask(_topic(), ContentLanguage.EN)
    assert "Hook formula" not in _sent(asked)


# --- the caption's first sentence ---------------------------------------------------


def test_the_opening_is_the_first_sentence_of_the_first_line() -> None:
    assert caption_opening("Short one. Then a second.\nMore") == "Short one."
    assert caption_opening("No full stop here\nnext line") == "No full stop here"
    assert caption_opening("") == ""


def test_a_caption_whose_point_is_cut_by_more_is_a_finding() -> None:
    found = caption_opening_finding(SLOANS_CAPTION)
    assert found is not None
    assert found["category"] == "caption" and found["where"] == "caption"
    assert str(CAPTION_PREVIEW_CHARS) in found["phrase"]


def test_a_short_opening_then_a_long_caption_is_fine() -> None:
    caption = (
        "Denver's biggest lake has two legends, and one is an elephant.\n\n"
        + "x " * 400
    )
    assert caption_opening_finding(caption) is None
    assert caption_opening_finding("") is None
    assert caption_opening_finding(None) is None


def test_the_system_prompt_asks_for_the_short_opening() -> None:
    for language in (ContentLanguage.EN, ContentLanguage.ES):
        assert str(CAPTION_PREVIEW_CHARS) in _system_for(language, ContentSeries.CONVERSION)


# --- machine-written phrases --------------------------------------------------------


def test_a_machine_phrase_is_found_and_named_with_its_field() -> None:
    found = machine_phrase_findings(
        hook="Let's delve into the Denver market.",
        script="It's not just a lake, it's a legend.",
        caption="A plain caption.",
    )
    phrases = {(f["where"], f["category"]) for f in found}
    assert ("hook", "ai-phrase") in phrases
    assert ("script", "ai-phrase") in phrases
    assert any("delve into" in f["phrase"] for f in found)


def test_ordinary_real_estate_words_are_not_machine_phrases() -> None:
    assert machine_phrase_findings(
        hook="Unlock the door and look at the landscape.",
        script="Leverage is how much of the house the bank owns. Your journey home.",
        caption="A remarkable, crucial, robust number.",
    ) == []


def test_our_own_fixed_lines_never_trip_the_filter() -> None:
    lines: list[str] = []
    lines += list(_CTA.values()) + list(_AI_DISCLOSURE.values())
    for group in _SOCIAL_CTA.values():
        lines += list(group)
    for group in _SPOKEN_CTA.values():
        lines += list(group)
    for line in lines:
        assert machine_phrase_findings(hook="", script=line, caption=line) == [], line


def test_a_word_inside_another_word_is_not_a_match() -> None:
    assert machine_phrase_findings(hook="", script="The delvers met.", caption="") == []


# --- both reach the console, through the one function it uses --------------------


def test_the_console_keeps_both_findings() -> None:
    found = stored_violations(
        hook="Let's delve into it.",
        script="A short script.",
        caption=SLOANS_CAPTION,
        scenes=None,
        language=ContentLanguage.EN,
        series=ContentSeries.DENVER_DECODED,
    )
    categories = {f["category"] for f in found}
    assert {"caption", "ai-phrase"} <= categories, found


def test_the_rewrite_is_told_what_each_new_finding_means() -> None:
    from app.services.content_writer import _feedback

    said = _feedback([
        caption_opening_finding(SLOANS_CAPTION),
        *machine_phrase_findings(hook="Let's delve into it.", script="", caption=""),
    ])
    assert "housing advertising" not in said
    assert str(CAPTION_PREVIEW_CHARS) in said
    assert "delve into" in said and "plain" in said

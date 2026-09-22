"""The spoken sign-off is said in the middle, because the end is empty.

Measured on the channel on 17-sep-2026, from YouTube's own retention curves:
retention holds through second 4 (losing under 9%), then falls from 105% to
60.6% by second 6.1 on a 13-second Short, and 93.8% of the audience never
leaves the Shorts player. 6,100 views in 28 days produced 14 visits to the
channel page — 0.23% — and 4 subscribers. A closing line is heard by the few
who stayed.

The yellow captions are transcribed from the audio by the render engine, so
what is SPOKEN is also what appears on screen. That matters here because
`on_screen_text` never reaches the engine at all: the bridge takes only
`visual_prompt` from each scene. The narration is the only surface this repo
controls that a viewer actually sees.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.models import ContentLanguage
from app.services.content_writer import (
    _SPOKEN_CTA,
    _sign_off_where_they_still_are,
    carries_spoken_domain,
    stored_violations,
    with_sign_off,
)

_URL = "https://www.denverhomestory.com"

#: The channel's signature shape, and the one that made the first version of
#: this a no-op: every seam after the first opens a continuation.
ENUMERADO = (
    "Three things shape what your home is worth. "
    "First: recent comparable sales, homes that sold like yours, nearby. "
    "Second: your home's condition, what has been updated, what needs work. "
    "Third: pricing strategy in the first two weeks."
)

NARRATIVO = (
    "If you pay three thousand five hundred a month in rent, buying puts you "
    "about twenty eight thousand five hundred ahead in five years. "
    "Principal paydown and tax deductions outweigh maintenance. "
    "The breakeven month is earlier than most renters think. "
    "That is the whole argument."
)


@pytest.fixture
def cta(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", _URL)
    return _URL


def _where(text: str, needle: str = "denver home story dot com") -> float:
    """How far into the spoken text the sign-off falls, 0 to 1."""
    return text.lower().index(needle) / len(text)


def _no_es_la_cola(text: str, needle: str = "denver home story dot com") -> None:
    """The property that matters: something is still said after the sign-off.

    Not "before the halfway character", which was the first version of this and
    was too tight: a script whose opening sentence IS the whole premise has its
    only seam at 50%, and refusing that would have refused the correct answer.
    What the retention curve asks for is that the line not be the last thing
    said, and that a real part of the piece follow it.
    """
    lower = text.lower()
    assert needle in lower, text
    despues = lower.split(needle, 1)[1]
    assert len(despues) / len(text) > 0.15, text
    assert _where(text, needle) <= 0.6, text


def test_the_sign_off_lands_before_the_middle(cta: str) -> None:
    _no_es_la_cola(with_sign_off(NARRATIVO, ContentLanguage.EN, 0))


def test_the_channel_enumeration_does_not_push_it_to_the_tail(cta: str) -> None:
    """The regression that made the first version worthless.

    Walking forward past every continuation fell off the end of this script
    and appended — a no-op on the format the channel uses most. The seam that
    works is the one before "First:", which is where a person would put it.
    """
    spoken = with_sign_off(ENUMERADO, ContentLanguage.EN, 0)
    _no_es_la_cola(spoken)
    # And not cutting the list in half.
    antes = spoken.lower().split("denver home story dot com")[0]
    assert "first:" not in antes, spoken


def test_a_script_of_two_sentences_still_appends(cta: str) -> None:
    """There is no middle to put anything in."""
    corto = "Rent is three thousand five hundred. Buying is ahead in five years."
    spoken = with_sign_off(corto, ContentLanguage.EN, 0)
    assert spoken.endswith(".")
    assert _where(spoken) > 0.5, spoken


def test_the_narrator_is_still_given_the_domain(cta: str) -> None:
    for script in (NARRATIVO, ENUMERADO):
        spoken = with_sign_off(script, ContentLanguage.EN, 0)
        assert carries_spoken_domain(spoken, ContentLanguage.EN), spoken


def test_a_script_that_already_says_it_gets_no_second_line(cta: str) -> None:
    ya = NARRATIVO + " Start at Denver Home Story dot com."
    assert with_sign_off(ya, ContentLanguage.EN, 0) == ya


def test_every_rotated_line_lands_in_the_middle(cta: str) -> None:
    """All three, because only one of them was ever looked at by hand."""
    for index in range(len(_SPOKEN_CTA[ContentLanguage.EN])):
        _no_es_la_cola(with_sign_off(NARRATIVO, ContentLanguage.EN, index))


def test_spanish_keeps_its_own_continuations(cta: str) -> None:
    es = (
        "Tres cosas deciden lo que vale tu casa. "
        "Primero: las ventas comparables recientes del barrio. "
        "Segundo: el estado de la casa y lo que haya que arreglar. "
        "Tercero: el precio que pongas las dos primeras semanas."
    )
    spoken = with_sign_off(es, ContentLanguage.ES, 0)
    _no_es_la_cola(spoken, "denver home story punto com")
    antes = spoken.lower().split("denver home story punto com")[0]
    assert "segundo:" not in antes, spoken


def test_the_piece_that_says_it_in_the_middle_has_nothing_against_it(
    cta: str,
) -> None:
    """The narration is read by the language guard and by Fair Housing.

    A short English sentence dropped inside an English script is the kind of
    thing that trips a language check written for whole paragraphs, and the
    piece would then be stuck as a DRAFT nobody can submit.
    """
    spoken = with_sign_off(NARRATIVO, ContentLanguage.EN, 0)
    plan = {
        "narration": spoken,
        "scenes": [
            {
                "visual_prompt": "A quiet Denver street of brick houses in even daylight",
                "on_screen_text": "Five year math",
            },
            {
                "visual_prompt": "An empty living room with morning light on a bare floor",
                "on_screen_text": "Where it goes",
            },
            {
                "visual_prompt": "A Denver home exterior seen from the sidewalk",
                "on_screen_text": "Compare",
            },
            {
                "visual_prompt": "A clean kitchen counter in a Denver condominium",
                "on_screen_text": "Costs",
            },
            {
                "visual_prompt": "House keys beside an unmarked ceramic bowl",
                "on_screen_text": "Equity",
            },
            {
                "visual_prompt": "The Denver skyline in clear afternoon light",
                "on_screen_text": "Five years",
            },
            {
                "visual_prompt": "An empty Denver front porch in evening light",
                "on_screen_text": "Try yours",
            },
        ],
    }
    assert (
        stored_violations(
            hook="What five years of rent actually costs you.",
            script=NARRATIVO,
            caption="The five year math, in plain numbers.",
            scenes=plan,
            language=ContentLanguage.EN,
        )
        == []
    )


def test_the_helper_never_returns_the_line_twice(cta: str) -> None:
    once = _sign_off_where_they_still_are(
        NARRATIVO, "Visit Denver Home Story dot com."
    )
    assert once.lower().count("denver home story dot com") == 1

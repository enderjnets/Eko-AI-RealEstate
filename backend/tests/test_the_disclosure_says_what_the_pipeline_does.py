"""The AI disclosure has to describe the pipeline that exists today.

This string has been wrong twice, in opposite directions, and that is the whole
reason this file exists.

1. It read *"Contains AI-generated visuals"* while every picture in the video
   was a licensed Pexels photograph. It was cut back to the narration alone,
   correctly: a disclosure that **overstates** is still a false statement on the
   channel of two licensed agents.
2. The note left behind said "if Kling ever draws the scenes, the visuals belong
   back in this sentence". Something does. Since `RENDER_ENGINE=bittrader` on
   10-sep-2026 the pictures come from `worker/pictures.py` — "fal.ai first,
   Pexels behind it", on `fal-ai/flux/schnell` — and on the generated lane stock
   never runs at all. For eight days the sentence **understated**.

The platform declaration was right the whole time: `kind=GENERATED` sends
`isAiGenerated` through Buffer. This is the half a person reads.

What is asserted here is therefore not a wording. It is that **both things the
pipeline actually does are named**, in both languages — so the next person who
swaps the picture source finds a red test instead of a caption that quietly
describes last month's pipeline.
"""

from __future__ import annotations

import pytest

from app.models import ContentLanguage
from app.services.content_writer import _AI_DISCLOSURE


@pytest.mark.parametrize("language", [ContentLanguage.EN, ContentLanguage.ES])
def test_the_narration_is_declared(language: ContentLanguage) -> None:
    """True of every piece this lane makes, whatever draws the pictures."""
    texto = _AI_DISCLOSURE[language].lower()
    palabras = {
        ContentLanguage.EN: ("synthetic", "voice"),
        ContentLanguage.ES: ("sintética", "voz"),
    }[language]
    faltan = [p for p in palabras if p not in texto]
    assert not faltan, f"the {language.value} disclosure no longer names the voice: {faltan}"


@pytest.mark.parametrize("language", [ContentLanguage.EN, ContentLanguage.ES])
def test_the_pictures_are_declared_because_they_are_drawn(
    language: ContentLanguage,
) -> None:
    """`worker/pictures.py` is fal.ai first, and stock never runs on this lane.

    If the picture source ever goes back to photographs, this test is the thing
    that has to be changed on purpose — which is the point. A disclosure that
    overstates is as wrong as one that understates, and this repo has shipped
    both.
    """
    texto = _AI_DISCLOSURE[language].lower()
    palabras = {
        ContentLanguage.EN: ("image", "ai-generated"),
        ContentLanguage.ES: ("imágenes", "ia"),
    }[language]
    faltan = [p for p in palabras if p not in texto]
    assert not faltan, (
        f"the {language.value} disclosure does not say the pictures are drawn, "
        f"and they are: {faltan}"
    )


@pytest.mark.parametrize("language", [ContentLanguage.EN, ContentLanguage.ES])
def test_it_stays_short_enough_to_be_read(language: ContentLanguage) -> None:
    """Conspicuous is part of the rule, and a caption gets cut off.

    Instagram and TikTok hide everything past the first lines behind "more".
    The disclosure sits below the brokerage line and the link on purpose; if it
    grows into a paragraph it stops being something a person reads and becomes
    something a person scrolls past.
    """
    assert len(_AI_DISCLOSURE[language]) <= 90, (
        f"the {language.value} disclosure is {len(_AI_DISCLOSURE[language])} "
        "characters and is turning into small print"
    )


def test_both_languages_say_the_same_two_things() -> None:
    """A disclosure present in one language and short in the other is worse
    than either, because nobody reads both and nobody notices."""
    assert set(_AI_DISCLOSURE) == {ContentLanguage.EN, ContentLanguage.ES}
    # Two sentences in each: the voice, then the pictures.
    for language, texto in _AI_DISCLOSURE.items():
        frases = [f for f in texto.split(".") if f.strip()]
        assert len(frases) == 2, (
            f"the {language.value} disclosure has {len(frases)} sentence(s); "
            "it should name the voice and the pictures"
        )

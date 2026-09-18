"""A shot that shows a street has to say which city's street it is.

Written on 18-sep-2026 from a frame, not from a worry. Piece 74's third shot
asked for *"a residential street lined with brick homes, a single unbranded post
with a blank sign slot"* and the engine returned a British terrace: brick
terraced houses, green metal railings, UK road markings. It published under a
Colorado brokerage's name, on a channel called Denver Home Story. The sign was
blank — the check that exists did its job. Nothing asked where the street was.

The rule is narrow on purpose, and the narrowness was measured rather than
guessed. Over the 189 prompts in production:

* 30 show a street, a row of homes, a neighbourhood or a skyline, and **25 of
  those already name Denver or the Front Range**. The check asks for what the
  writer already does five times out of six.
* A wider first attempt — which also matched `residential`, `porch`, `front
  yard` — flagged *"a residential contract document on a kitchen counter"*.
  That is indoors.
* A porch, a lawn, or a for-sale sign in a yard looks the same in Denver and in
  Ohio. Demanding a city there would refuse correct work to catch nothing a
  viewer could see. What gives a place away is the STREET.

Five of the 189 are caught and **none of them is in a live piece**, so this
puts no new red text in front of anybody.
"""

from __future__ import annotations

import pytest

from app.models import ContentLanguage
from app.services.content_writer import _SYSTEM, unplaced_streetscape

#: The prompt that actually shipped a British street, word for word.
LA_CALLE_INGLESA = (
    "A residential street lined with brick homes, a single unbranded post "
    "with a blank sign slot"
)

SIN_SITIO = [
    LA_CALLE_INGLESA,
    "A street view of homes with for-sale signs",
    "Exterior of a modern condo building on a city street",
    "Townhouse with a small front yard on a quiet street",
    "A for-sale sign in a green lawn, long shadows across a quiet street",
    "A neighbourhood of two-storey homes at golden hour",
    "A skyline at dusk with low clouds",
]

CON_SITIO = [
    "A residential Denver street with multiple for-sale signs and active listings",
    "Denver skyline with the Front Range visible in the background at golden hour",
    "A single-family home with a for-sale sign in a Denver neighborhood",
    "A downtown Denver street with a for-sale sign",
    "The Denver Front Range skyline at dusk, mountains in the distance",
    "A Colorado street lined with aspens turning gold",
]

#: Shots where the city is genuinely unknowable, so asking for it would refuse
#: correct work. These must NOT be flagged — the check earns its keep by being
#: narrow, and a test that only proves it catches things would not notice it
#: growing until it caught everything.
NO_SE_PUEDE_SABER = [
    "A covered porch with a moving box, late afternoon light, no people present",
    "A residential contract document on a kitchen counter, pen nearby",
    "A stack of residential property listings laid flat on a wooden table",
    "A set of residential house keys",
    "A for-sale sign freshly planted in a front yard at dawn, dew on the grass",
    "A simple glass hourglass resting on a bare wooden surface",
]


@pytest.mark.parametrize("prompt", SIN_SITIO)
def test_a_street_with_no_city_is_refused(prompt: str) -> None:
    """The engine picks a country when nobody names one, and it picked England."""
    assert unplaced_streetscape(prompt) is not None, (
        f"{prompt!r} shows a street and names no place, and nothing stopped it"
    )


@pytest.mark.parametrize("prompt", CON_SITIO)
def test_a_street_that_says_denver_passes(prompt: str) -> None:
    """Twenty-five of the thirty streetscapes in production already do this.

    If this direction broke, the check would refuse the writer's correct work
    every time it drew a street — which is most of what this channel shows.
    """
    assert unplaced_streetscape(prompt) is None, (
        f"{prompt!r} names the place and was refused anyway"
    )


@pytest.mark.parametrize("prompt", NO_SE_PUEDE_SABER)
def test_a_shot_where_the_city_is_unknowable_is_left_alone(prompt: str) -> None:
    """Narrowness is the feature, and this is the test that keeps it.

    A porch is a porch in Denver and in Ohio. The first version of the pattern
    was wider and flagged a contract on a kitchen counter; that is how this list
    was written.
    """
    assert unplaced_streetscape(prompt) is None, (
        f"{prompt!r} is not a streetscape and the check reached into it anyway"
    )


def test_it_names_the_word_not_just_the_fact() -> None:
    """"try again" versus "try again and say which street"."""
    assert unplaced_streetscape(LA_CALLE_INGLESA) == "street"


def test_naming_another_city_does_not_satisfy_it() -> None:
    """The video has to look like Denver, which is why this is not a gazetteer.

    A prompt that says "a Seattle street" is perfectly placed and perfectly
    wrong for this channel, so the check keeps refusing it.
    """
    assert unplaced_streetscape("A Seattle street lined with homes") is not None


@pytest.mark.parametrize("language", [ContentLanguage.EN, ContentLanguage.ES])
def test_the_writer_is_asked_before_it_is_refused(language: ContentLanguage) -> None:
    """A check with no matching instruction is a trap, not a rule.

    The pairing is the house pattern: `_SYSTEM` asks for a blank sign AND
    `readable_text_in_shot` reads the answer. This does the same. Asserted in
    both languages because the Spanish rail writes its shot list in English but
    is instructed in Spanish.
    """
    texto = _SYSTEM[language]
    # Two halves, asserted separately, because the first draft of this test
    # only looked for the example — and a mutation that deleted the REQUIREMENT
    # and left the example behind stayed green. An instruction is the demand
    # plus the shape of the answer; checking only the shape proves nothing.
    demanda = {
        ContentLanguage.EN: "MUST SAY WHERE IT IS",
        ContentLanguage.ES: "TIENE QUE DECIR DÓNDE ESTÁ",
    }[language]
    assert demanda in texto, (
        f"the {language.value} system prompt no longer REQUIRES the city, so "
        "the check would refuse work nobody was told how to do"
    )
    assert "Denver street" in texto, (
        f"the {language.value} system prompt demands a place but shows no "
        "example of one, which is how a model guesses wrong"
    )

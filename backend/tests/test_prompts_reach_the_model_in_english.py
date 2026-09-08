"""What may be sent to an image model, and the two ways a bad prompt hides.

fal.ai does not validate the language of a prompt. A Spanish one comes back 200
with a picture of something else, the video renders around it, every length and
size check passes, and the wrong image publishes under a licensed brokerage's
name. There is no error anywhere for anybody to notice — the only signal is a
person looking at the frame.

Measured in production on 2026-09-08, piece 20: "un sobre **cerrado**" drew a
rustic door with a *cerrado* sign, and "documentos de contrato inmobiliario"
drew the Château de Chantilly. Each one plausible enough to survive a skim.

Two shapes of failure, and the second is the one that took a second pass:

1. **A whole shot list in Spanish.** `wrong_language` sees it easily.
2. **A whole shot list in Spanish, written tersely.** Four noun phrases is
   twenty-four words, under the twenty-five-word floor `wrong_language` refuses
   to guess below — and that floor is correct, because a terse ENGLISH list
   carries no function words either and would be rejected for being short
   rather than for being wrong.

So the second check asks a narrower question — positive evidence of another
language, with no English at all — and the case it must NOT fire on is the one
this repo will actually meet: Colorado is full of Spanish place names.
"""

from __future__ import annotations

import pytest

from app.services.lang_guard import not_english_prompt

# Verbatim from piece 20, the Spanish piece whose six prompts were all Spanish.
LONG_SPANISH = (
    "Un cartel de se vende frente a una casa en Denver "
    "Un sobre cerrado y unas llaves sobre una mesa de madera "
    "Documentos de contrato inmobiliario sobre una mesa "
    "Un formulario con casillas de verificación de contingencias "
    "Una puerta principal con cerradura y unas llaves puestas "
    "Un escritorio con documentos y un teléfono sobre la mesa"
)

# Verbatim from piece 19, rendered the same night.
LONG_ENGLISH = (
    "A residential contract document on a kitchen counter, pen nearby "
    "A brick home with a for-sale sign in front, autumn light "
    "A laptop screen showing an email inbox with pending messages "
    "A stack of closing documents next to a set of house keys"
)


@pytest.mark.parametrize(
    "label, text",
    [
        ("the six real ones from piece 20", LONG_SPANISH),
        # The near miss. Not invented to be easy: prompts written as bare noun
        # phrases are what an image-prompt model actually produces, and piece
        # 20's own averaged nine words — four of them is twenty-four, under the
        # floor. This case passed before `not_english_prompt` existed.
        (
            "four terse Spanish noun phrases, under the floor",
            "Casa de ladrillo con jardín. Llaves sobre una mesa. "
            "Documento firmado. Puerta principal cerrada.",
        ),
    ],
)
def test_a_spanish_shot_list_is_refused(label: str, text: str) -> None:
    assert not_english_prompt(text) is not None, label


@pytest.mark.parametrize(
    "label, text",
    [
        ("the six real ones from piece 19", LONG_ENGLISH),
        # A terse English list carries no function words at all. Rejecting it
        # would be rejecting correct work for being short, which is exactly
        # what `MIN_WORDS` exists to prevent — so the second check demands
        # positive evidence of another language, not merely absence of English.
        ("terse English noun phrases", "Brick house, keys, front door, desk"),
        # The false positive this repo would actually hit. Colorado place names
        # are Spanish: Cañon City, Del Norte, Buena Vista, Alamosa. "Del Norte"
        # alone contributes a Spanish function word to the count. One English
        # function word anywhere settles it, and any real English sentence has
        # one.
        (
            "English prompt full of Colorado's Spanish place names",
            "Cañon City and Del Norte at sunrise, a brick home with keys "
            "on the porch, Buena Vista in the distance",
        ),
        ("a piece with no shot list at all", ""),
    ],
)
def test_an_english_shot_list_is_allowed(label: str, text: str) -> None:
    assert not_english_prompt(text) is None, label


def test_two_foreign_markers_and_no_english_is_not_enough_to_accuse() -> None:
    """Where the threshold actually bites, which is not where I first wrote it.

    I claimed the Colorado place-name case above was what a lowered threshold
    would break. It is not: that prompt has English function words, and one is
    enough to settle it before any count is reached. The threshold only decides
    text with **zero** English markers — a short list that is mostly proper
    nouns, where one or two Spanish words could as easily be a place name.

    That correction came from running the mutation, not from reading the code:
    dropping `FOREIGN_EVIDENCE` to 1 left the Colorado case green.

    Mutation: `FOREIGN_EVIDENCE = 1` → the first assertion here goes red, and
    what that would mean in production is a correct shot list refused, a piece
    silently not rendered, and nobody told to look at it.
    """
    # Two markers, no English, mostly proper nouns: not enough to accuse.
    assert not_english_prompt("Del Norte, la mesa, sunrise ridge") is None
    # Three: past coincidence.
    assert not_english_prompt("Del Norte, la mesa, una casa") is not None

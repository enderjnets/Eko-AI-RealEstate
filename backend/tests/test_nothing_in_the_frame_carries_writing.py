"""Nothing in the frame may carry readable writing.

Measured on 17-sep-2026, not supposed. Twenty-five of the thirty-three pieces
with a shot list ask for something that arrives with words on it — "sign"
appears twenty-nine times across the prompts, "document" fifteen, "screen" ten.
Of the published pieces, eleven have a shot that asks for a sign. I pulled the
frame from that exact scene in all eleven, computing the second from the scene's
index, and looked at them.

Two different failures, from two different places:

* **The image model invents the lettering.** "FOIR SALE". A "SOLD" sticker
  printed over an "...ALE". An illegible agency logo above a name that does not
  exist. Three of the eleven. Amateurish, and nothing worse.

* **Stock footage brings somebody else's branding.** One of the eleven, piece 8,
  published: a real, sharp photograph of a RE/MAX sign — the balloon logo, a
  named agent of that firm, two telephone numbers, "RE/MAX Infinity Realty Inc.
  · Independent member broker". An advertisement that has to identify itself as
  one brokerage showed a competitor's sign and another agent's telephone. Rule
  6.10 asks that advertising be accurate and not misleading to consumers.

Neither was ever going to be caught, because both live in the pixels and every
filter in this project reads what the model WRITES.

The fix allows the object and forbids the writing on it, and that distinction is
the whole design: refusing signs outright would have refused 82 of the 180 shots
in production, and a for-sale sign is a staple of this channel's imagery. So the
prompt teaches the model to ask for a blank, unbranded one, and this checks the
answer — because `_SYSTEM` has always said "never write a web address in any
field" and the model wrote them anyway.
"""

from __future__ import annotations

import pytest

from app.models import ContentLanguage
from app.services.content_writer import (
    _SYSTEM,
    DraftPayload,
    _all_violations,
    readable_text_in_shot,
)


def _draft(*prompts: str) -> DraftPayload:
    return DraftPayload(
        hook="Pricing high can cost you",
        script="A high list price turns quiet days into public information.",
        caption="The risk is not ambition; it is timing.",
        scenes=[
            {"visual_prompt": p, "on_screen_text": "Denver"} for p in prompts
        ],
    )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("A for-sale sign in front of a Denver-area house", "sign"),
        ("A house key placed on a contract document", "contract"),
        ("A laptop screen showing comparable sales", "screen"),
        ("A newspaper on a kitchen counter", "newspaper"),
        ("A business card on a table", "business card"),
        ("A calendar with dates highlighted", "calendar"),
    ],
)
def test_an_object_that_arrives_with_words_on_it_is_named(
    prompt: str, expected: str
) -> None:
    """Named, not just flagged: the rewrite has to say WHICH word to drop."""
    assert readable_text_in_shot(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "A blank, unbranded for-sale sign in front of a Denver-area house",
        "An unmarked sign at the end of a driveway",
        "A document with no legible text on a desk",
        "A screen, out of focus, behind a set of keys",
    ],
)
def test_saying_it_is_blank_is_the_way_through(prompt: str) -> None:
    """The escape hatch has to exist or the channel loses its main image.

    Measured against the 180 shots in production: forbidding these objects
    outright would have refused 82 of them, across 28 of 33 pieces. A for-sale
    sign is what a real estate short looks like. So the object is allowed and
    the writing is not.
    """
    assert readable_text_in_shot(prompt) is None


@pytest.mark.parametrize(
    "prompt",
    [
        "Denver skyline with the Front Range behind it at golden hour",
        "A quiet residential street in autumn",
        "A set of house keys on a wooden table",
        "An empty porch with the light on",
        "",
    ],
)
def test_a_shot_with_nothing_written_in_it_passes_untouched(prompt: str) -> None:
    """96 of the 180 shots in production are already like this."""
    assert readable_text_in_shot(prompt) is None


def test_a_missing_prompt_is_not_a_violation() -> None:
    assert readable_text_in_shot(None) is None


def test_the_draft_gate_refuses_the_shot_and_says_which_one() -> None:
    draft = _draft(
        "Denver skyline at golden hour",
        "A for-sale sign in front of a house",
        "A set of keys on a table",
    )
    found = _all_violations(draft, ContentLanguage.EN)
    shot = [f for f in found if f.get("category") == "shot"]
    assert len(shot) == 1
    # The position, so a person reading the console knows where to look.
    assert "shot 2" in shot[0]["phrase"]
    assert "sign" in shot[0]["phrase"]
    assert shot[0]["where"] == "scenes"


def test_every_offending_shot_is_reported_not_just_the_first() -> None:
    """One rewrite is all this gets, so it has to name all of them at once."""
    draft = _draft(
        "A for-sale sign in front of a house",
        "A contract on a desk",
        "Denver skyline at golden hour",
    )
    shot = [f for f in _all_violations(draft, ContentLanguage.EN) if f.get("category") == "shot"]
    assert len(shot) == 2
    assert "shot 1" in shot[0]["phrase"] and "shot 2" in shot[1]["phrase"]


def test_a_clean_shot_list_produces_no_findings_at_all() -> None:
    draft = _draft(
        "Denver skyline at golden hour",
        "A blank, unbranded for-sale sign on a lawn",
        "A set of keys on a wooden table",
    )
    assert _all_violations(draft, ContentLanguage.EN) == []


@pytest.mark.parametrize("language", [ContentLanguage.EN, ContentLanguage.ES])
def test_the_prompt_stops_offering_the_thing_it_used_to_ask_for(
    language: ContentLanguage,
) -> None:
    """The root cause, and it was in our own instructions.

    `_SYSTEM` listed "a document, a for-sale sign" as examples of a GOOD
    visual_prompt — the two objects that come back with invented lettering. The
    model was doing what it was told.
    """
    text = _SYSTEM[language]
    assert "a document, a for-sale sign" not in text
    assert "un cartel de se vende" not in text
    # And it now says what to do instead.
    assert "blank, unbranded" in text

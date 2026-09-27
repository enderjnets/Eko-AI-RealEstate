"""Some objects are nothing but writing, and "blank" does not empty them.

`test_nothing_in_the_frame_carries_writing.py` lets an object through when the
prompt says it is blank, because a blank for-sale sign comes back blank. On
27-sep-2026 two Denver, Decoded pieces showed that this does not hold for every
object. Both reached the render and were refused by the pixel gate
(`worker/verify.py`, "readable unapproved digits"), and the frames explain why:

* 98, "a blank calendar page turned to a month, no numbers visible" — a wall
  calendar with numbers on it, and the month ends on the 39th.
* 98, "a pair of vintage train tickets, blank, no writing" — a ticket that
  reads "TRAINN HTATE", "2010W.17.8573", "Waull Estate".
* 97, "a stone step with a blank plaque indicating correction" — a plaque that
  reads "CORRTION".
* 97, "a stone step with a small metal plaque, no readable writing visible" —
  "TOURT OR CHAN".

And one prompt ASKED for the words: "an engraved stone reading ONE MILE ABOVE
SEA LEVEL" came back as "ONE MILE SEA LEVEL". It passed the writer because
none of the words the old rule knew ("sign", "document"...) was in it.

The digit gate caught the numbers; nothing catches misspelt letters, so a
rebuild that happens to draw no digits would publish them. The place to stop
it is the shot list, before a paid render.

Measured on 27-sep-2026 over the 314 stored prompts: this rule refuses the six
shots of 97 and 98 above and no shot of any other piece that the current rule
lets through.
"""

from __future__ import annotations

import pytest

from app.models import ContentLanguage
from app.services.content_writer import (
    _SYSTEM,
    DraftPayload,
    _all_violations,
    writing_in_shot,
)


def _draft(*prompts: str) -> DraftPayload:
    return DraftPayload(
        hook="Why is the city called Denver?",
        script="The town company named it after a governor who had already left.",
        caption="A Denver name with a short, awkward history.",
        scenes=[
            {"visual_prompt": p, "on_screen_text": "Denver"} for p in prompts
        ],
    )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        # Verbatim from pieces 97 and 98, 27-sep-2026.
        ("a blank calendar page turned to a month, no numbers visible", "calendar"),
        ("a pair of vintage train tickets, blank, no writing", "tickets"),
        ("a stone step with a blank plaque indicating correction", "plaque"),
        ("a stone step with a small metal plaque, no readable writing visible", "plaque"),
        ("an old wooden desk with a quill and blank parchment, no visible text", "parchment"),
        ("a weathered stone with an engraved inscription, blank", "engraved"),
    ],
)
def test_blank_does_not_empty_an_object_that_is_only_writing(
    prompt: str, expected: str
) -> None:
    assert writing_in_shot(prompt) == expected


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "close-up of the 15th step showing an engraved stone reading ONE "
            "MILE ABOVE SEA LEVEL",
            "reading ONE",
        ),
        ("a brass sign that says “Welcome home”", "says “Welcome"),
        ("a stone lintel inscribed with 1892", "inscribed with 1892"),
    ],
)
def test_a_shot_that_asks_for_the_words_is_refused(
    prompt: str, expected: str
) -> None:
    assert writing_in_shot(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        # The staple the older rule protects must keep working.
        "A blank, unbranded for-sale sign in front of a Denver-area house",
        # Saying what is NOT there is not asking for it.
        "a set of old keys on a wooden table, blank, no engraving",
        "a granite step without inscription, morning light",
        # "reading" as a word, not as "reads these words".
        "a reading nook by a window in a Denver home",
        "the gold dome of the Colorado State Capitol against a clear sky",
        "",
    ],
)
def test_everything_else_passes(prompt: str) -> None:
    assert writing_in_shot(prompt) is None


def test_a_missing_prompt_is_not_a_violation() -> None:
    assert writing_in_shot(None) is None


def test_the_draft_gate_names_the_shot_and_does_not_say_blank() -> None:
    """The rewrite is told what to do. "Say it is blank" is the wrong advice
    here — it is exactly what 98 said, and it did not work."""
    draft = _draft(
        "Larimer Street downtown, Denver, historic brick buildings",
        "a pair of vintage train tickets, blank, no writing",
    )
    shot = [
        f for f in _all_violations(draft, ContentLanguage.EN)
        if f.get("category") == "shot"
    ]
    assert len(shot) == 1
    assert "shot 2" in shot[0]["phrase"]
    assert "tickets" in shot[0]["phrase"]
    assert "blank" not in shot[0]["phrase"].split("—")[-1]
    assert shot[0]["where"] == "scenes"


def test_one_finding_per_shot_not_two() -> None:
    """A calendar is also in the older list; the rewrite gets one instruction,
    and it is the one that works."""
    draft = _draft("A calendar with dates highlighted")
    shot = [
        f for f in _all_violations(draft, ContentLanguage.EN)
        if f.get("category") == "shot"
    ]
    assert len(shot) == 1
    assert "blank" not in shot[0]["phrase"].split("—")[-1]


@pytest.mark.parametrize("language", [ContentLanguage.EN, ContentLanguage.ES])
def test_the_writer_is_told_before_it_is_refused(language: ContentLanguage) -> None:
    text = _SYSTEM[language]
    assert "calendar" in text and "plaque" in text

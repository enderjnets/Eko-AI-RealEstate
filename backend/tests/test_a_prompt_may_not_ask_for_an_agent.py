"""A person in a housing advertisement, asked for by their job.

`PEOPLE_IN_PICTURES` named families, couples, children, professionals, men and
women — every demographic word a model reaches for — and not one occupational
one. Piece 16 asked for "a real estate agent reviewing documents at a kitchen
table", passed the writer's filter, rendered a man in a suit, and Buffer
published it to three platforms on the evening of 17-sep-2026.

Fair Housing is regulated in pictures too, which is why `picture_violations`
exists at all; a gate that reads the demographic words and not the job title is
one word away from the thing it was built to stop.
"""

from __future__ import annotations

import pytest

from app.services.fair_housing import picture_violations

#: Measured, not guessed. These are the shapes that put somebody in the frame.
CON_PERSONA = (
    "A real estate agent reviewing documents at a kitchen table",
    "A realtor showing a home to buyers",
    "A broker on the phone in a bright office",
    "Un agente inmobiliario enseñando una casa",
)

#: The reason the list stops at three words. Every one of these is a real
#: stored prompt or its shape: the trade is named, nobody is in the frame, and
#: refusing them would cost four correct prompts to catch none.
SIN_PERSONA = (
    "An appraiser's report document with a Denver skyline visible through a window",
    "A home inspector's clipboard with a detailed checklist",
    "A home repair checklist beside paint swatches, a tape measure, and a contractor's pencil",
    "A real estate feedback form on a clipboard with a pen, fields for buyer comments",
    "A quiet Denver street of brick houses in even daylight",
)


@pytest.mark.parametrize("prompt", CON_PERSONA)
def test_a_prompt_that_asks_for_somebody_by_their_job_is_refused(prompt: str) -> None:
    assert picture_violations(prompt), prompt


@pytest.mark.parametrize("prompt", SIN_PERSONA)
def test_naming_a_trade_is_not_putting_somebody_in_the_frame(prompt: str) -> None:
    assert picture_violations(prompt) == [], prompt


def test_the_piece_that_shipped_it_would_be_refused_today() -> None:
    """The exact prompt, from the row, so this cannot drift into a paraphrase."""
    found = picture_violations(
        "A real estate agent reviewing documents at a kitchen table"
    )
    # One finding per listed form that matches, which is how the rest of this
    # filter already reports; what matters is that the job title is named.
    assert "agent" in [f["phrase"] for f in found], found

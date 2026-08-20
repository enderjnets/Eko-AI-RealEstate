"""One test per forbidden phrase, and the false positives that matter.

A filter this list-shaped is only as good as its list, so the list is the test:
every phrase in `FORBIDDEN` is asserted to be caught, by construction, so
adding a phrase without a test is impossible and deleting one turns the suite
red rather than quietly widening what may be published.

The false-positive tests are the other half. A Fair Housing filter that fires on
"family room" gets switched off within a week by whoever is trying to get work
out, and a filter that is off catches nothing at all.
"""

from __future__ import annotations

import pytest

from app.services.fair_housing import FORBIDDEN, find_violations

ALL_PHRASES = [
    (category, phrase)
    for category, phrases in FORBIDDEN.items()
    for phrase in phrases
]


@pytest.mark.parametrize(("category", "phrase"), ALL_PHRASES)
def test_every_listed_phrase_is_caught(category: str, phrase: str) -> None:
    found = find_violations(f"Beautiful two bed in Denver. {phrase}. Call today.")
    assert any(f["phrase"] == phrase for f in found), (
        f"{phrase!r} is on the list and was not caught"
    )
    assert any(f["category"] == category for f in found)


def test_the_list_is_not_empty() -> None:
    """Its own canary. An empty list passes every test above vacuously."""
    assert len(ALL_PHRASES) > 50, (
        f"only {len(ALL_PHRASES)} phrases — the list has been gutted"
    )
    assert set(FORBIDDEN) >= {
        "familial_status",
        "steering",
        "race_or_colour",
        "religion",
        "national_origin",
        "disability",
        "sex",
    }, "a protected class disappeared from the filter"


@pytest.mark.parametrize(
    "text",
    [
        "Spacious family room with a fireplace.",
        "Three bedrooms, two baths, large yard.",
        "Close to the light rail and to Wash Park.",
        "Sala familiar amplia con chimenea.",
        "Tres habitaciones, dos banos, jardin grande.",
        "A dos cuadras del parque.",
    ],
)
def test_ordinary_listing_copy_is_left_alone(text: str) -> None:
    """The false positives that would get this filter switched off."""
    assert find_violations(text) == [], text


def test_accents_and_punctuation_do_not_defeat_it() -> None:
    """Typography is not a loophole.

    A generator writes "ideal para famílias" and hyphenates freely; a list that
    only matches bare ASCII lets both through while looking like it works.
    """
    assert find_violations("Ideal para famílias jóvenes."), "accents defeated it"
    assert find_violations("Perfect-for-families!"), "punctuation defeated it"
    assert find_violations("PERFECT FOR FAMILIES"), "case defeated it"


def test_the_other_language_is_still_checked() -> None:
    """A Spanish phrase in a piece tagged English is the same violation.

    Mislabelling the language must not be a way through.
    """
    from app.models import ContentLanguage

    assert find_violations("Great home. Barrio seguro.", ContentLanguage.EN), (
        "a Spanish forbidden phrase passed because the piece said it was English"
    )
    assert find_violations("Casa linda. Good schools nearby.", ContentLanguage.ES)


def test_every_hit_says_which_phrase_and_which_class() -> None:
    """The operator has to be able to fix it, which means knowing what to fix."""
    found = find_violations("Perfect for families and a safe neighborhood.")
    assert {f["category"] for f in found} == {"familial_status", "steering"}
    assert all(f["phrase"] and f["category"] for f in found)


def test_empty_text_is_not_a_violation() -> None:
    assert find_violations("") == []
    assert find_violations(None or "") == []

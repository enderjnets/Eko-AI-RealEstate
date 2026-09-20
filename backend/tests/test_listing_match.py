"""Scoring a listing against what somebody asked for, and the words for it.

Every assertion here is about one thing: the reason line reaches a buyer, so it
has to be traceable to a comparison. The dangerous failures are not wrong
scores — a human picks from this list — they are sentences that claim something
nobody checked.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.listing_match import (
    MET,
    MISSED,
    UNKNOWN,
    Requirement,
    matrix_recipe,
    reason_text,
    requirements_of,
    score_property,
)


def _prop(**kw) -> SimpleNamespace:
    base = {
        "id": 1,
        "bedrooms": 2,
        "bathrooms": Decimal("2.0"),
        "price": Decimal("585000"),
        "zone": "Denver Tech Center",
        "description": None,
        "raw": {"garage_spaces": 2, "parking_total": 2, "list_office_name": "Some Firm"},
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _status(checks, key: str) -> str | None:
    return next((c.status for c in checks if c.key == key), None)


def test_everything_they_asked_for_scores_full_marks() -> None:
    req = Requirement(
        zone="Denver Tech Center", budget_max=Decimal("600000"), beds_min=2,
        baths_min=Decimal("2.0"), garage_min=2,
    )
    score, checks = score_property(_prop(), req)
    assert score == 100
    assert {c.status for c in checks} == {MET}


def test_a_missing_garage_column_is_unknown_and_never_a_failure() -> None:
    """The column is blank on plenty of real rows, and that is a fact about the
    export rather than about the house. Scoring it as a miss ranks a listing we
    know nothing about below one we know is wrong, which is backwards."""
    req = Requirement(garage_min=2, beds_min=2)
    score, checks = score_property(_prop(raw={"garage_spaces": None}), req)
    assert _status(checks, "garage") == UNKNOWN
    # Beds were the only thing comparable, and they matched.
    assert score == 100


def test_a_garage_is_never_read_off_the_parking_count() -> None:
    """`Parking Total` counts a driveway pad. Somebody who asked for a garage
    for two SUVs did not ask for a pad."""
    req = Requirement(garage_min=2)
    _score, checks = score_property(
        _prop(raw={"garage_spaces": None, "parking_total": 4}), req
    )
    assert _status(checks, "garage") == UNKNOWN
    assert "4" not in reason_text(checks)


def test_an_office_is_carried_and_never_claimed() -> None:
    """The REcolorado Full export has no office column. Saying nothing would
    drop a requirement somebody wrote down; saying yes would be a lie."""
    req = Requirement(wants_office=True, beds_min=2)
    score, checks = score_property(_prop(), req)
    assert _status(checks, "office") == UNKNOWN
    assert "office not stated in the MLS" in reason_text(checks)
    # And it contributes nothing to the score in either direction.
    assert score == 100


def test_a_price_over_the_ceiling_costs_points_and_never_removes_the_listing() -> None:
    """`options.py` documents why: the figure a lead gives is routinely their
    savings. A lead whose $35,000 was a down payment would otherwise have every
    house in Denver filtered away from the person trying to help them."""
    req = Requirement(budget_max=Decimal("300000"), beds_min=2)
    score, checks = score_property(_prop(price=Decimal("585000")), req)
    assert _status(checks, "budget") == MISSED
    assert 0 < score < 100, "scored down, not removed"
    assert "over your $300,000" in reason_text(checks)


def test_what_was_never_asked_is_never_compared() -> None:
    req = Requirement(beds_min=2)
    _score, checks = score_property(_prop(), req)
    assert {c.key for c in checks} == {"beds"}


def test_nothing_comparable_scores_zero_rather_than_guessing() -> None:
    score, checks = score_property(_prop(), Requirement())
    assert score == 0
    assert checks == []


def test_the_reason_cannot_carry_another_firms_marketing_copy() -> None:
    """The one failure that would be invisible and expensive: a sentence built
    from `description` — REcolorado's `Public Remarks` — would walk "great
    schools" straight past a screen pointed at our own words."""
    req = Requirement(beds_min=2, zone="DTC")
    _score, checks = score_property(
        _prop(description="Great schools nearby, perfect for families!"), req
    )
    line = reason_text(checks)
    assert "schools" not in line.lower()
    assert "families" not in line.lower()


def test_the_recipe_names_every_criterion_a_person_has_to_type() -> None:
    req = Requirement(
        zone="DTC", budget_max=Decimal("600000"), beds_min=2,
        baths_min=Decimal("2.0"), garage_min=2, wants_office=True,
    )
    recipe = matrix_recipe(req)
    for expected in ("DTC", "$600,000", "Beds:", "Baths:", "Garage:", "Active", "Full"):
        assert expected in recipe, f"{expected} missing from the recipe"
    # And the caveat travels with the price, because the number may be savings.
    assert "not their savings" in recipe


def test_a_lead_who_said_nothing_gets_no_recipe_worth_running() -> None:
    assert Requirement().stated_anything is False


def test_requirements_come_off_the_lead_without_touching_the_database() -> None:
    lead = SimpleNamespace(
        zone="DTC", budget_min=None, budget_max=600000, beds_min=2,
        baths_min=Decimal("2.0"), garage_min=2, wants_office=True,
    )
    req = requirements_of(lead)
    assert req.beds_min == 2
    assert req.budget_max == Decimal("600000")
    assert isinstance(req.budget_max, Decimal), "a float here is the matcher crash"


@pytest.mark.parametrize("beds,expected", [(3, MET), (1, MISSED), (None, UNKNOWN)])
def test_beds_are_a_minimum_not_an_exact_match(beds, expected) -> None:
    _score, checks = score_property(_prop(bedrooms=beds), Requirement(beds_min=2))
    assert _status(checks, "beds") == expected


def test_an_abbreviation_does_not_reach_the_name_the_mls_files_it_under() -> None:
    """A known hole, asserted so it is a decision rather than a surprise.

    `zone_matches` compares words by prefix: "Wash Park" reaches "Washington
    Park" because "wash" starts "washington". "DTC" reaches nothing, because no
    word of "Denver Tech Center" starts with those three letters — and DTC is
    exactly what a buyer types.

    The consequence is honest rather than silent: the pool comes back empty,
    the notice says nothing matched, and the Matrix recipe goes out. Nobody is
    shown a wrong house. But the shortlist cannot be built from local inventory
    until either the lead's zone or the subdivision name is spelled out, and
    that is worth knowing before somebody reads "0 of 8" as a bug.
    """
    from app.services.listings import zone_matches

    assert zone_matches("Wash Park", "Washington Park") is True
    assert zone_matches("DTC", "Denver Tech Center") is False

    req = Requirement(zone="DTC", beds_min=2)
    _score, checks = score_property(_prop(zone="Denver Tech Center"), req)
    assert _status(checks, "zone") == MISSED

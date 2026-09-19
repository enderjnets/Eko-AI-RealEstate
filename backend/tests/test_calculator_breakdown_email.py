"""The breakdown we email back, and the three ways it could lie.

It could print a number the page never showed (rounding, or today's defaults
applied to yesterday's snapshot). It could print a net whose own parts do not
add up to it. Or it could carry prose that trips Fair Housing — this is a
licensed agent writing to a consumer about housing.

The prose is checked here with `find_violations` rather than by opinion, the
same way `test_calculator_copy.py` checks the page's strings: the filter is the
repo's own gate, and an empirical pass beats a second reading.
"""
from __future__ import annotations

import pytest

from app.services.calculator import DEFAULTS, build_snapshot
from app.services.calculator_email import _T, render_breakdown
from app.services.fair_housing import find_violations

INPUTS = {"rent": 2100, "savings": 15000, "credit": "good"}


def _snapshot(**overrides):
    lang = overrides.pop("lang", "en")
    return build_snapshot(INPUTS, overrides or None, lang=lang)


# ── the prose ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_template_string_clears_fair_housing(lang: str) -> None:
    for key, value in _T[lang].items():
        assert not find_violations(value, lang), (lang, key, value)


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_whole_rendered_email_clears_fair_housing(lang: str) -> None:
    subject, body = render_breakdown(_snapshot(lang=lang))
    assert not find_violations(f"{subject} {body}", lang)


@pytest.mark.parametrize("lang", ["en", "es"])
def test_it_calls_itself_an_estimate_and_not_a_quote(lang: str) -> None:
    """`docs/content/calculator-consistency.md`, rule 4: a result that depends on
    assumptions is labelled an estimate, never a guarantee."""
    _, body = render_breakdown(_snapshot(lang=lang))
    needle = "estimates, not a quote" if lang == "en" else "estimaciones, no una oferta"
    assert needle in body


def test_it_does_not_name_the_platform() -> None:
    """Same brand rule the page's copy is held to: a visitor reads about their
    own numbers, not about the software underneath."""
    _, body = render_breakdown(_snapshot())
    assert "Eko" not in body


# ── the numbers ──────────────────────────────────────────────────────────


def test_the_parts_add_up_to_the_net() -> None:
    """A breakdown whose lines do not reconcile is worse than no breakdown: the
    reader can check this one with a calculator, and some will."""
    _, body = render_breakdown(_snapshot(years=20))

    def money(label: str) -> int:
        line = next(ln for ln in body.splitlines() if ln.strip().startswith(label))
        raw = line.split("$")[1].split()[0].replace(",", "")
        return int(raw) * (-1 if "-$" in line else 1)

    total = next(ln for ln in body.splitlines() if "COMPARED WITH RENTING" in ln)
    net = int(total.split("$")[1].replace(",", ""))
    parts = sum(
        money(p)
        for p in ("Home value growth", "Loan paid down", "Monthly difference", "Closing costs", "Cost to sell")
    )
    assert parts == net


def test_the_horizon_is_the_one_that_was_stored() -> None:
    _, body = render_breakdown(_snapshot(years=20))
    assert "OVER 20 YEARS" in body
    _, five = render_breakdown(_snapshot())
    assert "OVER 5 YEARS" in five


def test_it_reads_the_stored_assumptions_not_todays_defaults() -> None:
    """An assumption edited next month must not rewrite what this person saw."""
    snapshot = _snapshot(appreciation=0.01)
    assert snapshot["assumptions"]["appreciation"] == 0.01
    _, body = render_breakdown(snapshot)
    assert "  Home value growth     1%" in body
    assert f"{DEFAULTS['appreciation'] * 100:.2f}%" not in body


def test_the_rate_shown_includes_the_credit_spread() -> None:
    _, body = render_breakdown(_snapshot())
    expected = (DEFAULTS["rate"] + DEFAULTS["rate_spread"]["good"]) * 100
    assert f"{expected:.2f}".rstrip("0").rstrip(".") + "%" in body


def test_the_monthly_and_the_comparison_are_labelled_apart() -> None:
    """`monthly_for` leaves upkeep out on purpose — it is the qualifying number —
    while the multi-year comparison counts it. Unlabelled, the two look like they
    should reconcile and do not."""
    _, body = render_breakdown(_snapshot())
    assert "counted in the comparison, not in the monthly cost" in body


def test_a_floor_snapshot_offers_a_conversation_not_a_number() -> None:
    """The page showed no price, so a comparison here would describe a purchase
    that was never offered."""
    snapshot = build_snapshot({"rent": 400, "savings": 0, "credit": "fair"}, None, lang="en")
    assert snapshot["result"]["capped_by"] == "floor"
    _, body = render_breakdown(snapshot)
    assert "below what homes in Denver" in body
    assert "COMPARED WITH RENTING" not in body


def test_an_unknown_language_falls_back_to_english() -> None:
    snapshot = _snapshot()
    snapshot["lang"] = "fr"
    subject, _ = render_breakdown(snapshot)
    assert subject == _T["en"]["subject"]

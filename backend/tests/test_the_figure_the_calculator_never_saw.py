"""A figure in a hook has to be one the calculator can account for.

On 12-14 September five videos went out saying "Renting at $2,600 a month? —
Buying is ~$21,000 ahead in five years." The calculator their own caption links
to answers **$52,210** for that rent under the assumptions the page uses.
Anyone who watched, clicked and typed their rent was shown a number two and a
half times larger than the promise they had just been made. The owner spotted
it and set all five to private.

The figures were not invented: $21,000 reproduces at a flat 2% annual
appreciation against the page's 3.75%. That is the worse outcome, because
"wrong" and "right under assumptions nobody recorded" are indistinguishable
from outside — and `docs/content/calculator-consistency.md` has required
recording them since 14-sep-2026. It was prose. Nothing read it.

The root cause is one line: **nothing in content generation has ever called the
calculator.** `app/services/calculator.py` is imported by `capture.py` and
`lead_notify.py` and by nothing else. The numbers arrive as prose from a model,
so approval is the first and only moment the claim and the arithmetic meet.
"""

from __future__ import annotations

from app.services.content_figures import (
    MINIMUM_CLAIM,
    figures_in,
    rounds_to,
    unexplained_figures,
)

GOOD = "good"


def scenario(rent: float, savings: float, credit: str = GOOD, **overrides):
    out = {"inputs": {"rent": rent, "savings": savings, "credit": credit}}
    if overrides:
        out["overrides"] = overrides
    return out


# ── Reading the figures out of the wording ───────────────────────────────


def test_it_finds_the_shapes_a_hook_actually_uses():
    assert figures_in("Renting at $2,600 a month? — Buying is ~$21,000 ahead") == [
        2600,
        21000,
    ]
    assert figures_in("$1,800 a month: an estimated $279,000 ceiling") == [1800, 279000]
    assert figures_in("$343,475.34 exactly") == [343475]
    # `.50` and above rounds up, because the calculator's own outputs are
    # rounded and a published cent should not create a phantom mismatch.
    assert figures_in("$99.50") == [100]


def test_a_number_without_a_dollar_sign_is_not_a_claim():
    """Demanding the calculator explain "five years" or "2026" would make this
    gate useless inside a week, and a useless gate gets switched off."""
    assert figures_in("Five years. 2026. Kenosha Pass, 10,000 ft.") == []
    assert figures_in("30-year fixed at 6.71%") == []


def test_nothing_in_the_text_is_nothing_to_check():
    assert figures_in("") == []
    assert figures_in(None) == []


# ── What counts as the same number ───────────────────────────────────────


def test_honest_rounding_passes():
    """A hook says $361,000 for a computed $360,794. That is how people write
    numbers, not a discrepancy."""
    assert rounds_to(361_000, 360_794.07) is True
    assert rounds_to(343_000, 343_475.34) is True
    assert rounds_to(279_000, 279_070.0) is True
    assert rounds_to(468_000, 467_682.0) is True
    assert rounds_to(35_000, 34_638.0) is True


def test_the_real_discrepancy_does_not():
    """$21,000 against a computed $52,210 — the five videos, in one line."""
    assert rounds_to(21_000, 52_210.0) is False
    assert rounds_to(21_700, 44_541.0) is False


def test_precision_is_read_off_the_claim_not_fixed_as_a_percentage():
    """The tolerance comes from the published number's own trailing zeros.

    A flat percentage is the trap: 10% of $361,000 is $36,100, so the same rule
    that forgives an honest rounding on a small figure waves through a
    two-and-a-half-fold error on a large one.
    """
    # Published to the nearest thousand: half a thousand either way.
    assert rounds_to(361_000, 361_499.0) is True
    assert rounds_to(361_000, 361_501.0) is False
    # Published to the dollar: it has to be the dollar.
    assert rounds_to(343_475, 343_475.4) is True
    assert rounds_to(343_475, 343_476.0) is False


def test_a_round_ten_thousand_is_not_a_licence_for_five_thousand_of_slack():
    """`$40,000` divides by 10,000, and reading that as "anything from 35,000
    to 45,000" would make every savings figure unfalsifiable. The step is
    therefore capped at a thousand, and this test is what pins the cap: without
    it the first assertion passes and the gate quietly stops being one.
    """
    assert rounds_to(40_000, 44_000.0) is False
    assert rounds_to(40_000, 40_400.0) is True


# ── The five that went out, and the six that were about to ───────────────


def test_the_five_hidden_videos_would_have_been_refused():
    """The measured claims, against the measured answers. Savings is unknown —
    no record survives, which is the point — so each is checked against the
    savings that flatters it most, and all five still fail.
    """
    claimed = {2_200: 21_700, 2_600: 21_000, 3_000: 24_300, 3_500: 28_500, 4_000: 32_800}
    for rent, said in claimed.items():
        text = f"Renting at ${rent:,} a month? — Buying is ~${said:,} ahead in five years."
        check = {"scenarios": [scenario(rent, s) for s in (20_000, 40_000, 60_000)]}
        assert unexplained_figures(text, check) == [said], rent


def test_the_six_in_flight_pieces_pass():
    """Pieces 40, 42, 44, 46 and 47 as production holds them, all at the
    $60,000 savings they were evidently written against."""
    assert (
        unexplained_figures(
            "$1,800 a month: explore an estimated $279,000 home-price ceiling",
            {"scenarios": [scenario(1_800, 60_000)]},
        )
        == []
    )
    assert (
        unexplained_figures(
            "$2,600 a month: explore an estimated $361,000 home-price ceiling",
            {"scenarios": [scenario(2_600, 60_000)]},
        )
        == []
    )
    assert (
        unexplained_figures(
            "$3,500 a month: explore an estimated $468,000 home-price ceiling",
            {"scenarios": [scenario(3_500, 60_000)]},
        )
        == []
    )


def test_two_scenarios_explain_a_piece_that_compares_two():
    """Piece 46: "With $40,000 saved: a $343,000 home. With $80,000 saved: a
    $378,000 home." Both savings figures are inputs, both prices are outputs."""
    text = "With $40,000 saved: a $343,000 home. — With $80,000 saved: a $378,000 home."
    check = {"scenarios": [scenario(2_600, 40_000), scenario(2_600, 80_000)]}
    assert unexplained_figures(text, check) == []


def test_a_difference_between_two_scenarios_is_explainable():
    """Piece 47: "Doubling your down payment adds $35,000 to the price." Nobody
    computed $35,000 — it is $378,113 minus $343,475, which is $34,638."""
    text = "Doubling your down payment — adds $35,000 to the price."
    check = {"scenarios": [scenario(2_600, 40_000), scenario(2_600, 80_000)]}
    assert unexplained_figures(text, check) == []


def test_a_difference_is_only_taken_within_the_same_field():
    """Subtracting a price from a monthly payment would manufacture an
    explanation for a number nobody computed, and with enough scenarios it
    would explain almost anything. The gate has to stay falsifiable."""
    # $343,475 (a price) minus $2,600 (a monthly) is $340,875. If cross-field
    # differences were allowed, this invented figure would pass.
    text = "A completely invented $340,875."
    check = {"scenarios": [scenario(2_600, 40_000)]}
    assert unexplained_figures(text, check) == [340_875]


# ── The record being required is the whole point ─────────────────────────


def test_a_figure_with_no_record_at_all_is_refused():
    text = "Renting at $2,600 a month? — Buying is ~$21,000 ahead in five years."
    assert unexplained_figures(text, None) == [2_600, 21_000]
    assert unexplained_figures(text, {}) == [2_600, 21_000]


def test_a_piece_with_no_figures_needs_no_record():
    """Most pieces. The autumn guides state no dollar amount, and a gate that
    blocked them would be switched off within a day."""
    assert unexplained_figures("Kenosha Pass belongs on your fall shortlist.", None) == []
    assert unexplained_figures("Same fall plans. Try a weekday.", None) == []


def test_small_change_is_not_a_calculator_claim():
    """`MINIMUM_CLAIM` exists so a gate about mortgage arithmetic does not
    block a piece over an HOA fee."""
    assert unexplained_figures(f"About ${MINIMUM_CLAIM - 1} a month in HOA.", None) == []
    assert unexplained_figures(f"About ${MINIMUM_CLAIM} a month in HOA.", None) == [
        MINIMUM_CLAIM
    ]


def test_a_number_that_is_deliberately_not_ours_can_be_declared():
    """A listing price, a recording fee. Written down one at a time, so it is
    an escape hatch nobody takes by accident."""
    text = "The transfer tax on that sale was $12,000."
    assert unexplained_figures(text, {"literal": [12_000]}) == []
    assert unexplained_figures(text, {"literal": [11_000]}) == [12_000]


def test_the_record_does_not_get_to_agree_with_itself():
    """The failure this design exists to avoid.

    A tidy snapshot saying $52,210 sitting beside a hook saying $21,000 is
    exactly the shape of every bug in this project's history: a record that
    agrees with a record while disagreeing with the world. The text is what is
    checked, so the piece is refused however good its paperwork looks.
    """
    text = "Buying is ~$21,000 ahead in five years."
    honest_record = {"scenarios": [scenario(2_600, 60_000)]}
    assert unexplained_figures(text, honest_record) == [21_000]


def test_the_assumptions_that_did_reproduce_it_are_accepted_when_recorded():
    """$21,000 is real at a flat 2% appreciation — solved by bisection against
    the deployed calculator, 1.962% at $20,000 saved rising to 2.000% at
    $60,000. Somebody used a round 2% where the page uses 3.75%.

    Recording that is allowed: the gate demands the assumptions be written
    down, not that they be the defaults. Whether a hook SHOULD quote a
    non-default assumption is an editorial question, and this is not the place
    that answers it — but it can no longer be answered by accident.
    """
    text = "Buying is ~$21,000 ahead in five years."
    check = {"scenarios": [scenario(2_600, 60_000, appreciation=0.02)]}
    assert unexplained_figures(text, check) == []


# ── The gate has a key, and the key works ────────────────────────────────


def test_the_edit_route_can_write_the_record():
    """A lock with no key is not a gate, it is an outage.

    Without a way to set `calculator_check`, a piece that states a figure could
    never be approved by anybody — the queue would simply stop the first time
    somebody wrote a price in a hook, and the fix would look like a bug in the
    approval route.
    """
    from app.api.v1.content import PieceEdit

    assert "calculator_check" in PieceEdit.model_fields
    edit = PieceEdit(calculator_check={"scenarios": [scenario(2_600, 60_000)]})
    assert "calculator_check" in edit.model_fields_set
    # Sending nothing must not clear a record that is already there: the loop
    # keys off `model_fields_set`, and the console saves hook/script/caption on
    # every keystroke-driven save.
    assert "calculator_check" not in PieceEdit(hook="x").model_fields_set


def test_the_record_is_readable_or_nobody_can_see_what_they_are_approving():
    from app.api.v1.content import PieceOut

    assert "calculator_check" in PieceOut.model_fields

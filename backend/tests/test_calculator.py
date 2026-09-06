"""The server's copy of the calculator gives the page's numbers.

Same fixture as `frontend/lib/__tests__/calculator.test.ts`: `jeff` and `hand`
are hand-written (the lender's Buy vs Rent sheet, arithmetic on paper); `cross`
holds prices the TypeScript side computed and this side must reproduce. If the
fixture is missing or empty this file fails on the first assertion — a fixture
that loads as `{}` would otherwise turn every parametrized case into a no-op.

The cliff case (test 14) is the one the two implementations are most likely to
diverge on: when the bisection cannot converge, both must return the cheap side.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.calculator import (
    CREDITS,
    DEFAULTS,
    OVERRIDABLE,
    balance_after,
    build_snapshot,
    compare,
    future_value,
    monthly_for,
    monthly_pi,
    solve_price,
    summary_line,
)

GOLDEN = Path(__file__).parent / "fixtures" / "calculator_golden.json"
golden = json.loads(GOLDEN.read_text())
assert golden["jeff"], "the golden fixture is missing or empty"
assert golden["hand"]

BASE = {"rent": 3000, "savings": 60_000, "credit": "excellent"}


def within(actual: float, expected: float, tolerance: float) -> None:
    assert abs(actual - expected) < tolerance, f"{actual} vs {expected} (±{tolerance})"


def jeff_assumptions() -> dict:
    j = golden["jeff"]
    return {
        **DEFAULTS,
        "rate": j["rate"],
        "rate_spread": {"excellent": 0.0, "good": 0.0, "fair": 0.0},
        "appreciation": j["appreciation_displayed"],
        "years": j["years"],
        "closing_rate": j["closing"] / j["price"],
        "selling_rate": j["selling_rate"],
    }


# ── the lender's sheet ────────────────────────────────────────────────────


def test_1_payment_on_the_sheet():
    j = golden["jeff"]
    within(monthly_pi(j["loan"], j["rate"], j["term"]), j["expect"]["pi"], 1)


def test_2_balance_after_nine_years():
    j = golden["jeff"]
    within(balance_after(j["loan"], j["rate"], j["term"], 108), j["expect"]["balance_after_108"], 100)


def test_3_value_after_nine_years_at_the_printed_rate():
    j = golden["jeff"]
    within(future_value(j["price"], j["appreciation_displayed"], j["years"]), j["expect"]["value_after_9"], 400)


def test_4_the_cascade_and_its_sum():
    j = golden["jeff"]
    inputs = {"rent": 4500, "savings": j["price"] - j["loan"] + j["closing"], "credit": "excellent"}
    a = jeff_assumptions()
    within(monthly_for(j["price"], inputs, a)["loan"], j["loan"], 1e-6)
    c = compare(inputs, a, j["price"])
    within(c["appreciation"], j["expect"]["appreciation_gain"], 400)
    within(c["amortization"], j["expect"]["amortization_gain"], 100)
    within(c["selling"], j["expect"]["selling_cost"], 20)
    within(c["closing"], j["closing"], 1e-6)
    within(c["net"], c["appreciation"] + c["amortization"] + c["cashflow_diff"] - c["closing"] - c["selling"], 0.01)
    assert len(c["rows"]) == j["years"]


# ── arithmetic on paper ───────────────────────────────────────────────────


def test_5a_zero_rate_loan_in_equal_slices():
    x = golden["hand"]["pi_zero_rate"]
    within(monthly_pi(x["loan"], x["rate"], x["term"]), x["expect"], 0.01)


def test_5b_balance_at_end_is_zero():
    x = golden["hand"]["balance_at_end_is_zero"]
    within(balance_after(x["loan"], x["rate"], x["term"], x["term"]), 0, 0.01)


def test_5c_balance_at_start_is_the_loan():
    x = golden["hand"]["balance_at_start_is_loan"]
    within(balance_after(x["loan"], x["rate"], x["term"], 0), x["loan"], 0.01)


def test_5d_flat_rent_over_five_years():
    x = golden["hand"]["rent_total_flat"]
    c = compare(
        {"rent": x["rent"], "savings": 0, "credit": "excellent"},
        {**DEFAULTS, "rent_growth": x["growth"], "years": x["years"]},
        0,
    )
    within(c["rent_total"], x["expect"], 0.01)
    assert c["buy_total"] == 0


def test_5e_two_years_at_ten_percent():
    x = golden["hand"]["future_value_two_years"]
    within(future_value(x["price"], x["rate"], x["years"]), x["expect"], 0.01)


def test_5f_zero_rate_balance_falls_by_the_flat_payment():
    x = golden["hand"]["pi_zero_rate"]
    within(balance_after(x["loan"], x["rate"], x["term"], 12), x["loan"] - 12 * x["expect"], 0.05)


# ── solving the price ─────────────────────────────────────────────────────


def test_6_lands_on_a_price_whose_monthly_cost_is_the_rent():
    r = solve_price(BASE, DEFAULTS)
    assert r["capped_by"] == "rent"
    within(monthly_for(r["price"], BASE, DEFAULTS)["total"], BASE["rent"], 1)
    within(r["monthly"]["total"], BASE["rent"], 1)
    assert r["price"] > DEFAULTS["price_floor"]


def test_7a_more_rent_buys_more_house():
    assert solve_price({**BASE, "rent": 4000}, DEFAULTS)["price"] > solve_price(BASE, DEFAULTS)["price"]


def test_7b_credit_orders_the_price():
    prices = [solve_price({**BASE, "credit": c}, DEFAULTS)["price"] for c in ("fair", "good", "excellent")]
    assert prices[0] < prices[1] < prices[2]


def test_8a_no_savings_is_the_floor():
    r = solve_price({**BASE, "savings": 0}, DEFAULTS)
    assert r["capped_by"] == "floor"
    assert r["price"] < DEFAULTS["price_floor"]


def test_8b_savings_that_cover_the_price():
    r = solve_price({**BASE, "savings": 10_000_000}, DEFAULTS)
    assert r["down"] == r["price"]
    assert r["loan"] == 0
    assert r["monthly"]["pi"] == 0
    assert r["monthly"]["pmi"] == 0
    assert r["capped_by"] == "rent"


def test_11_the_ceiling():
    r = solve_price(
        {"rent": 50_000, "savings": 0, "credit": "excellent"},
        {**DEFAULTS, "min_down": 0, "closing_rate": 0},
    )
    assert r["price"] == 5_000_000
    assert r["capped_by"] == "rent"


def test_14_rent_inside_the_pmi_cliff_lands_on_the_cheap_side():
    inputs = {"rent": 3200, "savings": 100_000, "credit": "fair"}
    r = solve_price(inputs, DEFAULTS)
    assert r["capped_by"] == "rent"
    assert r["monthly"]["total"] <= inputs["rent"] + 0.5
    assert r["monthly"]["pmi"] == 0
    assert r["price"] > 400_000
    assert monthly_for(r["price"] + 1, inputs, DEFAULTS)["total"] > inputs["rent"]


def test_16_little_savings_cap_the_price():
    # 20.000 es lo menos que sigue comprando algo en Denver por encima del suelo.
    inputs = {"rent": 6000, "savings": 20_000, "credit": "excellent"}
    r = solve_price(inputs, DEFAULTS)
    assert r["capped_by"] == "savings"
    within(r["price"], 20_000 / 0.045, 0.01)
    within(r["down"] / r["price"], 0.03, 0.0001)
    assert r["monthly"]["total"] < inputs["rent"]


def test_16b_ten_thousand_no_longer_reaches_the_denver_market():
    """El suelo es el borde del mercado, no una constante de UX.

    Con 10.000 dolares el tope por ahorro cae en 222.222, por debajo de lo que
    se vende en Denver (condo mediano 310.000, los de entrada sobre 300.000).
    Antes la pagina ensenaba esa cifra; ahora dice la verdad. Este test es la
    razon por la que el suelo subio de 150.000 a 250.000.
    """
    r = solve_price({"rent": 6000, "savings": 10_000, "credit": "excellent"}, DEFAULTS)
    assert r["capped_by"] == "floor"
    assert r["price"] < DEFAULTS["price_floor"]
    within(r["price"], 10_000 / 0.045, 0.01)


def test_garbage_inputs_do_not_raise():
    r = solve_price({"rent": math.nan, "savings": -5, "credit": "good"}, DEFAULTS)
    assert math.isfinite(r["price"])
    assert r["capped_by"] == "floor"
    r = solve_price({"rent": "3000", "savings": None, "credit": "good"}, DEFAULTS)
    assert r["capped_by"] == "floor"


# ── owning against renting ────────────────────────────────────────────────


def test_9_nothing_moving_one_year():
    inputs = {"rent": 3000, "savings": 200_000, "credit": "excellent"}
    a = {
        **DEFAULTS,
        "appreciation": 0,
        "rent_growth": 0,
        "maintenance_rate": 0,
        "selling_rate": 0,
        "closing_rate": 0,
        "years": 1,
    }
    price = solve_price(inputs, a)["price"]
    c = compare(inputs, a, price)
    assert len(c["rows"]) == 1
    within(c["rows"][0]["buy_monthly"] - c["rows"][0]["rent_monthly"], 0, 1)
    within(c["cashflow_diff"], 0, 12)
    within(c["net"], c["amortization"], 12)
    assert c["appreciation"] == 0
    assert c["selling"] == 0


def test_9b_closing_and_selling_come_out_of_the_net():
    inputs = {"rent": 3000, "savings": 200_000, "credit": "excellent"}
    a = {**DEFAULTS, "appreciation": 0, "rent_growth": 0, "maintenance_rate": 0, "years": 1}
    price = solve_price(inputs, a)["price"]
    c = compare(inputs, a, price)
    within(c["net"], c["amortization"] - (a["closing_rate"] + a["selling_rate"]) * price, 12)
    assert c["net"] < c["amortization"]


def test_10a_a_falling_market_never_crosses_over():
    a = {**DEFAULTS, "appreciation": -0.05}
    c = compare(BASE, a, solve_price(BASE, a)["price"])
    assert c["crossover_year"] is None
    assert c["net"] < 0


def test_10b_the_default_crossover_year_recorded():
    c = compare(BASE, DEFAULTS, solve_price(BASE, DEFAULTS)["price"])
    assert c["crossover_year"] == 3
    assert c["years"] == DEFAULTS["years"]
    assert [r["year"] for r in c["rows"]] == [1, 2, 3, 4, 5]


def test_10c_the_scan_reaches_past_the_displayed_horizon():
    a = {**DEFAULTS, "appreciation": 0}
    c = compare(BASE, a, solve_price(BASE, a)["price"])
    assert c["crossover_year"] == 8


def test_15_hoa_on_both_sides():
    a = {**DEFAULTS, "hoa_monthly": 250, "maintenance_rate": 0, "appreciation": 0}
    with_hoa = monthly_for(400_000, BASE, a)
    without = monthly_for(400_000, BASE, DEFAULTS)
    within(with_hoa["total"] - without["total"], 250, 0.01)
    c = compare(BASE, a, 400_000)
    within(c["rows"][0]["buy_monthly"] - with_hoa["total"], 0, 0.01)


def test_17_pmi_drops_off_under_eighty_percent():
    price = 500_000
    a = {**DEFAULTS, "appreciation": 0, "rent_growth": 0, "years": 2}
    inputs = {"rent": 3000, "savings": (a["closing_rate"] + 0.195) * price, "credit": "excellent"}
    m = monthly_for(price, inputs, a)
    within(m["loan"] / price, 0.805, 0.0001)
    assert m["pmi"] > 0
    c = compare(inputs, a, price)
    within(c["rows"][0]["buy_monthly"] - c["rows"][1]["buy_monthly"], m["loan"] * a["pmi"]["excellent"] / 12, 0.01)


def test_17b_pmi_is_keyed_to_the_price_not_the_value():
    price = 500_000
    a = {**DEFAULTS, "appreciation": 0.05, "rent_growth": 0, "years": 2}
    inputs = {"rent": 3000, "savings": (a["closing_rate"] + 0.18) * price, "credit": "excellent"}
    assert monthly_for(price, inputs, a)["pmi"] > 0
    c = compare(inputs, a, price)
    carry = (a["tax_rate"] + a["insurance_rate"] + a["maintenance_rate"]) / 12
    within(c["rows"][1]["buy_monthly"] - c["rows"][0]["buy_monthly"], price * 0.05 * carry, 0.01)


def test_18_growth_starts_in_year_two():
    a = {**DEFAULTS, "maintenance_rate": 0}
    r = solve_price(BASE, a)
    c = compare(BASE, a, r["price"])
    assert c["rows"][0]["rent_monthly"] == BASE["rent"]
    within(c["rows"][1]["rent_monthly"], BASE["rent"] * 1.02, 0.01)
    within(c["rows"][0]["buy_monthly"], r["monthly"]["total"], 0.01)


def test_19_the_credit_spread_reaches_the_note_rate():
    m = monthly_for(400_000, {**BASE, "credit": "fair"}, DEFAULTS)
    within(m["pi"], monthly_pi(m["loan"], DEFAULTS["rate"] + DEFAULTS["rate_spread"]["fair"], 360), 0.001)
    assert m["pi"] > monthly_for(400_000, BASE, DEFAULTS)["pi"]


def test_20_garbage_assumptions_do_not_hang_or_poison():
    assert compare(BASE, {**DEFAULTS, "years": math.inf}, 400_000)["years"] == DEFAULTS["years"]
    c = compare(BASE, {**DEFAULTS, "years": 100}, 400_000)
    assert c["years"] == 40
    assert len(c["rows"]) == 40
    n = compare(BASE, {**DEFAULTS, "years": math.nan, "hoa_monthly": -1e9, "rate": math.nan}, 400_000)
    assert n["years"] == DEFAULTS["years"]
    assert math.isfinite(n["net"])
    within(n["rows"][0]["buy_monthly"], compare(BASE, DEFAULTS, 400_000)["rows"][0]["buy_monthly"], 0.01)
    g = compare(BASE, {**DEFAULTS, "appreciation": math.nan, "rent_growth": None}, 400_000)
    within(g["net"], compare(BASE, DEFAULTS, 400_000)["net"], 0.01)
    assert compare(BASE, {**DEFAULTS, "years": 0}, 400_000)["years"] == 1


# ── parity with the page ──────────────────────────────────────────────────


def test_12_cross_anchors_to_the_cent():
    cross = golden["cross"]
    assert len(cross) == 3
    for row in cross:
        inputs = {k: row[k] for k in ("rent", "savings", "credit")}
        within(solve_price(inputs, DEFAULTS)["price"], row["price"], 0.01)


def test_defaults_are_the_page_defaults():
    # The values the TypeScript side declares, by hand — not read from it.
    assert DEFAULTS["rate"] == 0.0671
    assert DEFAULTS["tax_rate"] == 0.0052
    assert DEFAULTS["insurance_rate"] == 0.007
    assert DEFAULTS["pmi"] == {"excellent": 0.0045, "good": 0.008, "fair": 0.013}
    assert DEFAULTS["rate_spread"] == {"excellent": 0.0, "good": 0.0025, "fair": 0.0075}
    assert DEFAULTS["years"] == 5 and DEFAULTS["price_floor"] == 250_000
    assert set(CREDITS) == {"excellent", "good", "fair"}


# ── what gets stored with the lead ────────────────────────────────────────


def test_snapshot_shape_and_integers():
    s = build_snapshot({"rent": 2100, "savings": 15000, "credit": "good"}, None, lang="es")
    assert set(s) == {"version", "computed_at", "lang", "inputs", "assumptions", "result"}
    assert s["version"] == 1 and s["lang"] == "es"
    assert s["computed_at"].endswith("+00:00")
    assert s["inputs"] == {"rent": 2100.0, "savings": 15000.0, "credit": "good"}
    assert set(s["result"]) == {"price", "capped_by", "loan", "down", "monthly", "net_5y", "crossover_year"}
    assert set(s["result"]["monthly"]) == {"pi", "tax", "insurance", "pmi", "hoa", "total"}
    for k in ("price", "loan", "down", "net_5y"):
        assert isinstance(s["result"][k], int), k
    for v in s["result"]["monthly"].values():
        assert isinstance(v, int)
    assert s["result"]["capped_by"] == "rent"
    assert s["assumptions"]["years"] == 5
    json.dumps(s)  # JSONB-safe


def test_snapshot_matches_the_cross_anchor():
    row = golden["cross"][0]
    s = build_snapshot({k: row[k] for k in ("rent", "savings", "credit")}, None, lang=None)
    assert s["result"]["price"] == round(row["price"])
    assert s["lang"] is None


def test_snapshot_overrides_replace_the_base_rate_and_keep_the_spread():
    # A-3: an overridden rate replaces the base; the credit spread is added after.
    s = build_snapshot({"rent": 3000, "savings": 60000, "credit": "fair"}, {"rate": 0.05, "foo": 1}, lang="en")
    assert s["assumptions"]["rate"] == 0.05
    assert "foo" not in s["assumptions"]
    loan = s["result"]["loan"]
    within(s["result"]["monthly"]["pi"], monthly_pi(loan, 0.05 + DEFAULTS["rate_spread"]["fair"], 360), 1)
    assert set(OVERRIDABLE) == {"appreciation", "rent_growth", "rate", "hoa_monthly"}


def test_snapshot_ignores_a_none_override_and_bad_lang():
    s = build_snapshot({"rent": 3000, "savings": 60000, "credit": "good"}, {"appreciation": None}, lang="fr")
    assert s["assumptions"]["appreciation"] == DEFAULTS["appreciation"]
    assert s["lang"] is None


def test_snapshot_rejects_an_unknown_credit():
    with pytest.raises(ValueError):
        build_snapshot({"rent": 3000, "savings": 60000, "credit": "superb"}, None, lang="en")


def test_summary_line_reads_like_a_sentence():
    s = build_snapshot({"rent": 2100, "savings": 15000, "credit": "good"}, None, lang="en")
    line = summary_line(s)
    assert line.startswith("Used the rent-vs-buy calculator: rent $2,100/mo, savings $15,000, good credit")
    # The first cross anchor is 262,451.17 — by hand, not from the code.
    assert "up to ~$262,000" in line
    assert "5-yr net vs renting: " in line
    assert line.endswith(").")
    assert "," in line.split("~$")[1]  # thousands separator in the price


def test_summary_line_on_the_floor_shows_no_price():
    s = build_snapshot({"rent": 500, "savings": 0, "credit": "fair"}, None, lang="en")
    assert s["result"]["capped_by"] == "floor"
    line = summary_line(s)
    assert "no estimate" in line
    assert "up to" not in line
    # And nothing about a purchase that was never offered is stored either.
    assert s["result"]["net_5y"] is None
    assert s["result"]["crossover_year"] is None


def test_summary_line_negative_net():
    s = build_snapshot({"rent": 3000, "savings": 60000, "credit": "excellent"}, {"appreciation": -0.05}, lang="en")
    assert s["result"]["net_5y"] < 0
    assert "net vs renting: -$" in summary_line(s)


def test_summary_line_at_the_ceiling_says_so():
    s = build_snapshot({"rent": 50_000, "savings": 5_000_000, "credit": "excellent"}, None, lang="en")
    assert s["result"]["price"] == 5_000_000
    line = summary_line(s)
    assert "at least $5,000,000 (search ceiling)" in line
    assert "up to" not in line


def test_snapshot_rounds_half_up_like_the_page():
    # 833/mo with 100k saved lands on a bisection midpoint: 195,312.5 exactly.
    s = build_snapshot({"rent": 833, "savings": 100_000, "credit": "excellent"}, None, lang="en")
    assert s["result"]["price"] == 195_313
    assert s["assumptions"]["pmi"] is not DEFAULTS["pmi"]
    assert s["assumptions"]["pmi"] == DEFAULTS["pmi"]


def test_25_the_mortgage_payment_stops_when_the_loan_is_paid_off():
    """El prestamo son 360 meses; cobrarlo en el ano 31 inflaba el coste de
    comprar en todo horizonte mayor que el plazo. Invisible mientras la pagina
    solo ensenaba cinco anos, y falso en cuanto ofrece treinta.
    """
    inputs = {"rent": 2000, "savings": 30_000, "credit": "good"}
    price = solve_price(inputs, DEFAULTS)["price"]
    c = compare(inputs, {**DEFAULTS, "years": 35}, price)
    rows = {r["year"]: r["buy_monthly"] for r in c["rows"]}
    pi = monthly_for(price, inputs, DEFAULTS)["pi"]
    assert rows[31] < rows[30]
    assert rows[30] - rows[31] > pi * 0.9
    assert rows[35] > rows[31]
    assert rows[35] < pi


def test_26_the_crossing_is_searched_as_far_as_the_visitor_looks():
    inputs = {"rent": 2000, "savings": 30_000, "credit": "good"}
    price = solve_price(inputs, DEFAULTS)["price"]
    for years in (5, 30):
        c = compare(inputs, {**DEFAULTS, "years": years}, price)
        if c["crossover_year"] is not None:
            assert c["crossover_year"] <= max(10, years)


def test_defaults_carry_an_inflation_for_todays_money():
    assert DEFAULTS["inflation"] == 0.02

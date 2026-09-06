"""The rent-to-price arithmetic behind `/calculator`, server side.

The page computes the visitor's number in the browser
(`frontend/lib/calculator.ts`); when they leave their email, the browser sends
the three inputs — never the result — and this module recomputes everything
before it is stored with the lead. The server does not trust a number a
browser typed, and the two implementations must agree: both read the golden
fixture at `tests/fixtures/calculator_golden.json`, whose `cross` anchors were
computed by the TypeScript side. A change to one that is not mirrored in the
other turns a test red here.

Same rules, same order of operations, same bisection — including its stop
rule and what it returns when it runs out of iterations (the cheap side of the
PMI cliff). A "better" bisection would be more precise and fail parity.

Every default carries its source and date on the TypeScript side (`SOURCES`);
this module keeps only the values, so there is one place to read the why.
"""
from __future__ import annotations

import copy
import math
from datetime import UTC, datetime
from typing import Any

CREDITS: tuple[str, ...] = ("excellent", "good", "fair")

DEFAULTS: dict[str, Any] = {
    "rate": 0.0671,
    "term_months": 360,
    "tax_rate": 0.0052,
    "insurance_rate": 0.007,
    "maintenance_rate": 0.01,
    "hoa_monthly": 0.0,
    "closing_rate": 0.015,
    "selling_rate": 0.04,
    "min_down": 0.03,
    "pmi": {"excellent": 0.0045, "good": 0.008, "fair": 0.013},
    "rate_spread": {"excellent": 0.0, "good": 0.0025, "fair": 0.0075},
    "appreciation": 0.02,
    "rent_growth": 0.02,
    "years": 5,
    "price_floor": 250_000,
}

# The only assumptions the page lets a visitor move. Anything else in an
# overrides dict is ignored, not applied.
OVERRIDABLE: tuple[str, ...] = ("appreciation", "rent_growth", "rate", "hoa_monthly")

# The search ceiling. A rent no price under it can absorb returns it as-is.
UPPER = 5_000_000
# The longest horizon the comparison will scan.
MAX_YEARS = 40


def _dollars(n: Any) -> float:
    """A non-finite, non-numeric or negative dollar amount is zero."""
    if isinstance(n, bool) or not isinstance(n, int | float):
        return 0.0
    return float(n) if math.isfinite(n) and n > 0 else 0.0


def _finite(n: Any, fallback: float) -> float:
    if isinstance(n, bool) or not isinstance(n, int | float) or not math.isfinite(n):
        return float(fallback)
    return float(n)


def _clamp(n: float, lo: float, hi: float) -> float:
    return min(max(n, lo), hi)


def _round(n: float) -> int:
    """Half up, like the page's `Math.round`. Python's `round` is half-to-even,
    and the bisection's midpoints (5e6 / 2^k) land on exact halves often enough
    that the dashboard would show $1 less than the visitor saw."""
    return int(math.floor(n + 0.5))


def _normalize(a: dict[str, Any]) -> dict[str, Any]:
    """The editable assumptions are the ones that can arrive as garbage."""
    years = a.get("years")
    if isinstance(years, bool) or not isinstance(years, int | float) or not math.isfinite(years):
        years_n = float(DEFAULTS["years"])
    else:
        years_n = float(math.floor(years))
    out = dict(a)
    out["rate"] = _finite(a.get("rate"), DEFAULTS["rate"])
    out["appreciation"] = _finite(a.get("appreciation"), DEFAULTS["appreciation"])
    out["rent_growth"] = _finite(a.get("rent_growth"), DEFAULTS["rent_growth"])
    out["hoa_monthly"] = _dollars(a.get("hoa_monthly"))
    out["years"] = int(_clamp(years_n, 1, MAX_YEARS))
    return out


def _note_rate(a: dict[str, Any], credit: str) -> float:
    """The base rate — overridden or not — plus the credit spread, in that order."""
    return a["rate"] + a["rate_spread"][credit]


def monthly_pi(loan: float, annual_rate: float, term_months: int) -> float:
    """Level monthly principal-and-interest payment."""
    if loan <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return loan / term_months
    return (loan * r) / (1 - (1 + r) ** -term_months)


def balance_after(loan: float, annual_rate: float, term_months: int, months_paid: float) -> float:
    """Remaining balance after `months_paid` level payments. Never negative."""
    if loan <= 0:
        return 0.0
    m = monthly_pi(loan, annual_rate, term_months)
    r = annual_rate / 12
    k = _clamp(months_paid, 0, term_months)
    if r == 0:
        return max(0.0, loan - m * k)
    growth = (1 + r) ** k
    return max(0.0, loan * growth - (m * (growth - 1)) / r)


def future_value(price: float, annual_rate: float, years: float) -> float:
    return price * (1 + annual_rate) ** years


def monthly_for(price: float, inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, float]:
    """What a home at `price` costs per month for this buyer — the qualifying
    number. Upkeep is deliberately not here."""
    a = _normalize(raw)
    v = _dollars(price)
    savings = _dollars(inputs.get("savings"))
    credit = inputs["credit"]
    closing = a["closing_rate"] * v
    down = _clamp(savings - closing, 0, v)
    loan = v - down
    ltv = loan / v if v > 0 else 0.0
    pi = monthly_pi(loan, _note_rate(a, credit), a["term_months"])
    tax = (v * a["tax_rate"]) / 12
    insurance = (v * a["insurance_rate"]) / 12
    pmi = (loan * a["pmi"][credit]) / 12 if ltv > 0.8 else 0.0
    hoa = a["hoa_monthly"]
    return {
        "pi": pi,
        "tax": tax,
        "insurance": insurance,
        "pmi": pmi,
        "hoa": hoa,
        "total": pi + tax + insurance + pmi + hoa,
        "loan": loan,
        "down": down,
        "closing": closing,
    }


def solve_price(inputs: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """The price whose monthly cost equals the rent, capped by what the savings
    can put down. Bisection on a monotone non-decreasing total."""
    a = _normalize(raw)
    rent = _dollars(inputs.get("rent"))
    savings = _dollars(inputs.get("savings"))

    def total(v: float) -> float:
        return monthly_for(v, inputs, a)["total"]

    if total(UPPER) < rent:
        v_rent = float(UPPER)
    else:
        lo = 0.0
        hi = float(UPPER)
        converged: float | None = None
        for _ in range(80):
            mid = (lo + hi) / 2
            t = total(mid)
            if abs(t - rent) < 0.5:
                converged = mid
                break
            if t < rent:
                lo = mid
            else:
                hi = mid
        # No price inside the PMI jump costs the rent to the half-dollar; `lo`
        # is the highest one that costs no more than it. Same rule as the page.
        v_rent = converged if converged is not None else lo

    entry = a["min_down"] + a["closing_rate"]
    v_savings = savings / entry if entry > 0 else math.inf

    price = min(v_rent, v_savings)
    capped_by = "rent" if price == v_rent else "savings"
    if price < a["price_floor"]:
        capped_by = "floor"

    m = monthly_for(price, inputs, a)
    return {
        "price": price,
        "loan": m["loan"],
        "down": m["down"],
        "closing": m["closing"],
        "monthly": {k: m[k] for k in ("pi", "tax", "insurance", "pmi", "hoa", "total")},
        "capped_by": capped_by,
    }


def _horizon(inputs: dict[str, Any], a: dict[str, Any], price: float, years: int) -> dict[str, Any]:
    v = _dollars(price)
    rent = _dollars(inputs.get("rent"))
    credit = inputs["credit"]
    m = monthly_for(v, inputs, a)
    rate = _note_rate(a, credit)
    pmi_monthly = (m["loan"] * a["pmi"][credit]) / 12
    carry = (a["tax_rate"] + a["insurance_rate"] + a["maintenance_rate"]) / 12

    rows: list[dict[str, float]] = []
    buy_total = 0.0
    rent_total = 0.0
    for y in range(1, years + 1):
        value = v * (1 + a["appreciation"]) ** (y - 1)
        balance_at_start = balance_after(m["loan"], rate, a["term_months"], 12 * (y - 1))
        # PMI is keyed to the purchase price, not to a value that has since moved.
        pmi = pmi_monthly if v > 0 and balance_at_start / v > 0.8 else 0.0
        buy_monthly = m["pi"] + value * carry + pmi + a["hoa_monthly"]
        rent_monthly = rent * (1 + a["rent_growth"]) ** (y - 1)
        rows.append({"year": y, "buy_monthly": buy_monthly, "rent_monthly": rent_monthly})
        buy_total += 12 * buy_monthly
        rent_total += 12 * rent_monthly

    cashflow_diff = rent_total - buy_total
    closing = a["closing_rate"] * v
    value_n = future_value(v, a["appreciation"], years)
    selling = a["selling_rate"] * value_n
    appreciation = value_n - v
    amortization = m["loan"] - balance_after(m["loan"], rate, a["term_months"], 12 * years)
    net = appreciation + amortization + cashflow_diff - closing - selling
    return {
        "appreciation": appreciation,
        "amortization": amortization,
        "cashflow_diff": cashflow_diff,
        "closing": closing,
        "selling": selling,
        "net": net,
        "buy_total": buy_total,
        "rent_total": rent_total,
        "rows": rows,
    }


def compare(inputs: dict[str, Any], raw: dict[str, Any], price: float) -> dict[str, Any]:
    """Owning at `price` against renting, over `years`. A negative net is a
    result, not an error."""
    a = _normalize(raw)
    years = a["years"]
    h = _horizon(inputs, a, price, years)
    crossover: int | None = None
    for n in range(1, 11):
        if _horizon(inputs, a, price, n)["net"] > 0:
            crossover = n
            break
    return {"years": years, **h, "crossover_year": crossover}


def build_snapshot(
    inputs: dict[str, Any], overrides: dict[str, Any] | None, *, lang: str | None
) -> dict[str, Any]:
    """Recompute on the server and return what is stored with the lead.

    `inputs` is the three things the visitor typed; `overrides` the sliders
    they moved (only `OVERRIDABLE` keys are honored). The caller has validated
    ranges already (`CalculatorIn`); an unknown credit range here is a
    programming error, not user input, and raises.
    """
    credit = inputs.get("credit")
    if credit not in CREDITS:
        raise ValueError(f"unknown credit range: {credit!r}")
    clean = {
        "rent": _dollars(inputs.get("rent")),
        "savings": _dollars(inputs.get("savings")),
        "credit": credit,
    }
    # Deep: `pmi` and `rate_spread` are dicts, and a shallow copy would hand
    # every snapshot the same objects as the module constant.
    a = copy.deepcopy(DEFAULTS)
    for key in OVERRIDABLE:
        value = (overrides or {}).get(key)
        if value is not None:
            a[key] = value
    a = _normalize(a)
    solved = solve_price(clean, a)
    comparison = compare(clean, a, solved["price"])
    # Under the floor the page shows no figure, so the comparison is of a
    # purchase that was never offered; storing its net would hand the
    # dashboard "buying a $0 home nets +$31,000".
    floored = solved["capped_by"] == "floor"
    return {
        "version": 1,
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "lang": lang if lang in ("en", "es") else None,
        "inputs": clean,
        "assumptions": a,
        "result": {
            "price": _round(solved["price"]),
            "capped_by": solved["capped_by"],
            "loan": _round(solved["loan"]),
            "down": _round(solved["down"]),
            "monthly": {k: _round(v) for k, v in solved["monthly"].items()},
            "net_5y": None if floored else _round(comparison["net"]),
            "crossover_year": None if floored else comparison["crossover_year"],
        },
    }


def summary_line(snapshot: dict[str, Any]) -> str:
    """One line for the Inbox and the new-lead notice, in English.

    'Used the rent-vs-buy calculator: rent $2,100/mo, savings $15,000, good
    credit → up to ~$310,000 (5-yr net vs renting: +$18,600).'
    """
    i = snapshot["inputs"]
    r = snapshot["result"]
    years = snapshot.get("assumptions", {}).get("years", DEFAULTS["years"])
    head = (
        f"Used the rent-vs-buy calculator: rent ${i['rent']:,.0f}/mo, "
        f"savings ${i['savings']:,.0f}, {i['credit']} credit"
    )
    if r["capped_by"] == "floor" or r.get("net_5y") is None:
        return f"{head} → below the price floor, no estimate shown."
    net = int(r["net_5y"])
    sign = "+" if net >= 0 else "-"
    tail = f"({years}-yr net vs renting: {sign}${abs(net):,})."
    if r["price"] >= UPPER:
        # The search ceiling, not an estimate: the rent absorbs more than any
        # price the page looks at.
        return f"{head} → at least ${UPPER:,} (search ceiling) {tail}"
    price_k = _round(r["price"] / 1000.0) * 1000
    return f"{head} → up to ~${price_k:,} {tail}"

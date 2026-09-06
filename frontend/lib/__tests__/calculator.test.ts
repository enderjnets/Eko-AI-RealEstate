import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DEFAULTS,
  LIMITS,
  SOURCES,
  balanceAfter,
  buildPayload,
  compare,
  netCurve,
  inTodaysMoney,
  futureValue,
  monthlyFor,
  monthlyPI,
  solvePrice,
  type Assumptions,
  type Credit,
  type Inputs,
} from "../calculator";

/**
 * The arithmetic behind `/calculator`, against the lender's Buy vs Rent sheet.
 *
 * The expected values live in `backend/tests/fixtures/calculator_golden.json`,
 * shared with the Python implementation. `jeff` and `hand` are written by hand
 * — the sheet's printed figures and arithmetic done on paper — never generated
 * by the code under test. `cross` is different: three prices computed by THIS
 * module, kept so the server cannot drift from the page; they prove parity,
 * not correctness.
 *
 * Tolerances are the sheet's rounding: it prints the rate to two decimals and
 * the dollars to the unit, so its own cascade is only reproducible to within a
 * few hundred dollars on the compounding terms.
 */

interface Golden {
  jeff: {
    price: number;
    loan: number;
    rate: number;
    term: number;
    years: number;
    appreciation_displayed: number;
    closing: number;
    selling_rate: number;
    expect: {
      pi: number;
      balance_after_108: number;
      value_after_9: number;
      appreciation_gain: number;
      amortization_gain: number;
      selling_cost: number;
    };
  };
  hand: {
    pi_zero_rate: { loan: number; rate: number; term: number; expect: number };
    balance_at_end_is_zero: { loan: number; rate: number; term: number };
    balance_at_start_is_loan: { loan: number; rate: number; term: number };
    rent_total_flat: { rent: number; growth: number; years: number; expect: number };
    future_value_two_years: { price: number; rate: number; years: number; expect: number };
  };
  cross: Array<Inputs & { price: number }>;
}

const golden: Golden = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "..", "backend", "tests", "fixtures", "calculator_golden.json"),
    "utf8",
  ),
);

const within = (actual: number, expected: number, tolerance: number) =>
  expect(Math.abs(actual - expected)).toBeLessThan(tolerance);

/** The sheet's own loan: no credit spread, its rate, its horizon. */
function jeffAssumptions(): Assumptions {
  const j = golden.jeff;
  return {
    ...DEFAULTS,
    rate: j.rate,
    rateSpread: { excellent: 0, good: 0, fair: 0 },
    appreciation: j.appreciation_displayed,
    years: j.years,
    closingRate: j.closing / j.price,
    sellingRate: j.selling_rate,
  };
}

describe("the golden fixture", () => {
  it("is present and hand-written", () => {
    expect(golden.jeff.expect.pi).toBe(4670);
    expect(Object.keys(golden.hand)).toHaveLength(5);
  });
});

describe("the lender's sheet, reproduced", () => {
  const j = golden.jeff;

  it("1. the payment on $720,000 at 6.75% over 360 months", () => {
    within(monthlyPI(j.loan, j.rate, j.term), j.expect.pi, 1);
  });

  it("2. the balance after nine years of payments", () => {
    within(balanceAfter(j.loan, j.rate, j.term, 108), j.expect.balance_after_108, 100);
  });

  it("3. the value after nine years at the printed 4.94%", () => {
    // The sheet prints 4.94%; the rate it actually used is (1234407/800000)^(1/9)
    // = 4.9376%, so the printed rate lands a few hundred dollars high.
    within(futureValue(j.price, j.appreciation_displayed, j.years), j.expect.value_after_9, 400);
  });

  it("4. the cascade: appreciation, amortization, closing, cost to sell — and their sum", () => {
    // Savings such that the down payment is exactly the sheet's $80,000 after
    // its $12,000 of closing costs.
    const inputs: Inputs = { rent: 4500, savings: j.price - j.loan + j.closing, credit: "excellent" };
    const a = jeffAssumptions();
    const m = monthlyFor(j.price, inputs, a);
    expect(m.loan).toBeCloseTo(j.loan, 6);
    const c = compare(inputs, a, j.price);
    within(c.appreciation, j.expect.appreciation_gain, 400);
    within(c.amortization, j.expect.amortization_gain, 100);
    within(c.selling, j.expect.selling_cost, 20);
    expect(c.closing).toBeCloseTo(j.closing, 6);
    // Costs are subtracted, gains added. Flip a sign and this is what goes red.
    within(c.net, c.appreciation + c.amortization + c.cashflowDiff - c.closing - c.selling, 0.01);
    expect(c.rows).toHaveLength(j.years);
  });
});

describe("arithmetic done on paper", () => {
  const h = golden.hand;

  it("5a. a zero-rate loan is paid in equal slices", () => {
    const x = h.pi_zero_rate;
    within(monthlyPI(x.loan, x.rate, x.term), x.expect, 0.01);
  });

  it("5b. the balance at the end of the term is zero", () => {
    const x = h.balance_at_end_is_zero;
    within(balanceAfter(x.loan, x.rate, x.term, x.term), 0, 0.01);
  });

  it("5c. the balance before the first payment is the loan", () => {
    const x = h.balance_at_start_is_loan;
    within(balanceAfter(x.loan, x.rate, x.term, 0), x.loan, 0.01);
  });

  it("5d. flat rent over five years", () => {
    const x = h.rent_total_flat;
    const c = compare(
      { rent: x.rent, savings: 0, credit: "excellent" },
      { ...DEFAULTS, rentGrowth: x.growth, years: x.years },
      0,
    );
    within(c.rentTotal, x.expect, 0.01);
    expect(c.buyTotal).toBe(0);
  });

  it("5e. two years at ten percent", () => {
    const x = h.future_value_two_years;
    within(futureValue(x.price, x.rate, x.years), x.expect, 0.01);
  });
});

describe("solving the price from the rent", () => {
  const base: Inputs = { rent: 3000, savings: 60000, credit: "excellent" };

  it("6. lands on a price whose monthly cost is the rent", () => {
    const r = solvePrice(base, DEFAULTS);
    expect(r.cappedBy).toBe("rent");
    within(monthlyFor(r.price, base, DEFAULTS).total, base.rent, 1);
    within(r.monthly.total, base.rent, 1);
    expect(r.price).toBeGreaterThan(DEFAULTS.priceFloor);
  });

  it("7a. more rent buys more house", () => {
    expect(solvePrice({ ...base, rent: 4000 }, DEFAULTS).price).toBeGreaterThan(
      solvePrice(base, DEFAULTS).price,
    );
  });

  it("7b. fair credit buys less than excellent, same rent and savings", () => {
    const order: Credit[] = ["fair", "good", "excellent"];
    const prices = order.map((credit) => solvePrice({ ...base, credit }, DEFAULTS).price);
    expect(prices[0]).toBeLessThan(prices[1]);
    expect(prices[1]).toBeLessThan(prices[2]);
  });

  it("8a. no savings: the floor, not a figure", () => {
    const r = solvePrice({ ...base, savings: 0 }, DEFAULTS);
    expect(r.cappedBy).toBe("floor");
    expect(r.price).toBeLessThan(DEFAULTS.priceFloor);
  });

  it("8c. $10,000 no longer reaches the Denver market: the floor, not a figure", () => {
    // The savings cap lands at $222,222 — under the median Denver condo
    // ($310,000) and under what entry condos start at. The page says so
    // instead of showing a price nothing can be bought with. This is why the
    // floor moved from $150,000 to $250,000.
    const r = solvePrice({ ...base, savings: 10_000 }, DEFAULTS);
    expect(r.cappedBy).toBe("floor");
    expect(r.price).toBeLessThan(DEFAULTS.priceFloor);
    within(r.price, 10_000 / 0.045, 0.01);
  });

  it("8b. savings that cover the whole price: no loan, no payment, no PMI", () => {
    const r = solvePrice({ ...base, savings: 10_000_000 }, DEFAULTS);
    expect(r.down).toBe(r.price);
    expect(r.loan).toBe(0);
    expect(r.monthly.pi).toBe(0);
    expect(r.monthly.pmi).toBe(0);
    expect(r.cappedBy).toBe("rent");
  });

  it("11. a rent no price under $5M absorbs returns the ceiling, not a half-converged value", () => {
    const r = solvePrice(
      { rent: 50_000, savings: 0, credit: "excellent" },
      { ...DEFAULTS, minDown: 0, closingRate: 0 },
    );
    expect(r.price).toBe(5_000_000);
    expect(r.cappedBy).toBe("rent");
  });

  it("does not choke on garbage numbers", () => {
    const r = solvePrice({ rent: Number.NaN, savings: -5, credit: "good" }, DEFAULTS);
    expect(Number.isFinite(r.price)).toBe(true);
    expect(r.cappedBy).toBe("floor");
  });
});

describe("owning against renting", () => {
  it("9. with nothing moving and one year, the two sides cost the same and the net is the principal paid", () => {
    // Savings past 20% so no PMI drops off mid-horizon.
    const inputs: Inputs = { rent: 3000, savings: 200_000, credit: "excellent" };
    const a: Assumptions = {
      ...DEFAULTS,
      appreciation: 0,
      rentGrowth: 0,
      maintenanceRate: 0,
      sellingRate: 0,
      closingRate: 0,
      years: 1,
    };
    const price = solvePrice(inputs, a).price;
    const c = compare(inputs, a, price);
    expect(c.rows).toHaveLength(1);
    within(c.rows[0].buyMonthly - c.rows[0].rentMonthly, 0, 1);
    within(c.cashflowDiff, 0, 12);
    within(c.net, c.amortization, 12);
    expect(c.appreciation).toBe(0);
    expect(c.selling).toBe(0);
  });

  it("9b. closing and selling costs come OUT of the net", () => {
    const inputs: Inputs = { rent: 3000, savings: 200_000, credit: "excellent" };
    const a: Assumptions = {
      ...DEFAULTS,
      appreciation: 0,
      rentGrowth: 0,
      maintenanceRate: 0,
      years: 1,
    };
    const price = solvePrice(inputs, a).price;
    const c = compare(inputs, a, price);
    // Rent and buy cost the same in year one, value is flat, so the net is the
    // principal paid minus 1.5% to buy and 4% to sell.
    within(c.net, c.amortization - (a.closingRate + a.sellingRate) * price, 12);
    expect(c.net).toBeLessThan(c.amortization);
  });

  it("10a. a falling market never crosses over", () => {
    const inputs: Inputs = { rent: 3000, savings: 60_000, credit: "excellent" };
    const a = { ...DEFAULTS, appreciation: -0.05 };
    const c = compare(inputs, a, solvePrice(inputs, a).price);
    expect(c.crossoverYear).toBeNull();
    expect(c.net).toBeLessThan(0);
  });

  it("10b. with the defaults, the crossover year is what it is — recorded, not forced", () => {
    // Product information, not a target: at 2% appreciation and 2% rent growth
    // this is when owning pulls ahead for $3,000 of rent and $60,000 saved.
    const inputs: Inputs = { rent: 3000, savings: 60_000, credit: "excellent" };
    const c = compare(inputs, DEFAULTS, solvePrice(inputs, DEFAULTS).price);
    expect(c.crossoverYear).toBe(3);
    expect(c.years).toBe(DEFAULTS.years);
    expect(c.rows.map((r) => r.year)).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("parity anchors and sources", () => {
  it("12. the three cross anchors the server must reproduce", () => {
    expect(golden.cross).toHaveLength(3);
    for (const { price, ...inputs } of golden.cross) {
      within(solvePrice(inputs, DEFAULTS).price, price, 1);
    }
  });

  it("13. every assumption carries a source with a date", () => {
    for (const key of Object.keys(DEFAULTS) as Array<keyof Assumptions>) {
      const s = SOURCES[key];
      expect(s.label, key).toBeTruthy();
      expect(s.asOf, key).toMatch(/^\d{4}(-\d{2}){1,2}$/);
      if (s.url) expect(s.url, key).toMatch(/^https:\/\//);
    }
    // The ones that move the answer most are not rules of thumb.
    expect(SOURCES.rate.url).toContain("fred.stlouisfed.org");
    expect(SOURCES.appreciation.url).toContain("fred.stlouisfed.org");
  });
});

describe("what the audit found missing", () => {
  const base: Inputs = { rent: 3000, savings: 60000, credit: "excellent" };

  it("14. a rent inside the PMI cliff never buys a payment above the rent", () => {
    // The monthly cost jumps at LTV 80%. For these inputs the jump spans
    // roughly $3,064–$3,468 a month; no price costs exactly $3,200, so the
    // bisection runs out. It must land on the cheap side of the cliff.
    const inputs: Inputs = { rent: 3200, savings: 100_000, credit: "fair" };
    const r = solvePrice(inputs, DEFAULTS);
    expect(r.cappedBy).toBe("rent");
    expect(r.monthly.total).toBeLessThanOrEqual(inputs.rent + 0.5);
    expect(r.monthly.pmi).toBe(0);
    expect(r.price).toBeGreaterThan(400_000);
    // And the far side really is more expensive: a dollar more of price
    // crosses into PMI.
    expect(monthlyFor(r.price + 1, inputs, DEFAULTS).total).toBeGreaterThan(inputs.rent);
  });

  it("15. the HOA is part of the payment, on both sides of the comparison", () => {
    const a: Assumptions = { ...DEFAULTS, hoaMonthly: 250, maintenanceRate: 0, appreciation: 0 };
    const withHoa = monthlyFor(400_000, base, a);
    const without = monthlyFor(400_000, base, DEFAULTS);
    within(withHoa.total - without.total, 250, 0.01);
    expect(withHoa.hoa).toBe(250);
    const c = compare(base, a, 400_000);
    within(c.rows[0].buyMonthly - withHoa.total, 0, 0.01);
  });

  it("16. little savings: the ceiling is savings ÷ (3% down + 1.5% closing)", () => {
    // $20,000 is about the least that still clears the Denver floor; below it
    // the answer is "nothing sells here", which case 8c covers.
    const inputs: Inputs = { rent: 6000, savings: 20_000, credit: "excellent" };
    const r = solvePrice(inputs, DEFAULTS);
    expect(r.cappedBy).toBe("savings");
    within(r.price, 20_000 / 0.045, 0.01);
    within(r.down / r.price, 0.03, 0.0001);
    expect(r.monthly.total).toBeLessThan(inputs.rent); // the rent is not what capped it
  });

  it("17. PMI drops off once the balance is under 80% of the price", () => {
    // 19.5% down: LTV starts at 80.5% and the first year's principal takes it
    // under 80%, so year two costs exactly one month of PMI less.
    const price = 500_000;
    const a: Assumptions = { ...DEFAULTS, appreciation: 0, rentGrowth: 0, years: 2 };
    const inputs: Inputs = { rent: 3000, savings: (a.closingRate + 0.195) * price, credit: "excellent" };
    const m = monthlyFor(price, inputs, a);
    within(m.loan / price, 0.805, 0.0001);
    expect(m.pmi).toBeGreaterThan(0);
    const c = compare(inputs, a, price);
    within(c.rows[0].buyMonthly - c.rows[1].buyMonthly, (m.loan * a.pmi.excellent) / 12, 0.01);
  });

  it("17b. PMI is keyed to the purchase price, not to a value that has since grown", () => {
    // 18% down, a market up 5% a year: by year two the balance is 77% of the
    // VALUE but still 81% of the PRICE. PMI is still owed in year two, so the
    // only thing that moves between the rows is the carrying cost of a home
    // worth 5% more.
    const price = 500_000;
    const a: Assumptions = { ...DEFAULTS, appreciation: 0.05, rentGrowth: 0, years: 2 };
    const inputs: Inputs = { rent: 3000, savings: (a.closingRate + 0.18) * price, credit: "excellent" };
    const m = monthlyFor(price, inputs, a);
    expect(m.pmi).toBeGreaterThan(0);
    const c = compare(inputs, a, price);
    const carry = (a.taxRate + a.insuranceRate + a.maintenanceRate) / 12;
    within(c.rows[1].buyMonthly - c.rows[0].buyMonthly, price * 0.05 * carry, 0.01);
  });

  it("18. growth starts in year two: year one is what the visitor typed", () => {
    const a: Assumptions = { ...DEFAULTS, maintenanceRate: 0 };
    const r = solvePrice(base, a);
    const c = compare(base, a, r.price);
    expect(c.rows[0].rentMonthly).toBe(base.rent);
    within(c.rows[1].rentMonthly, base.rent * 1.02, 0.01);
    // Year one of owning is the qualifying payment itself: no upkeep here,
    // and the value has not moved yet.
    within(c.rows[0].buyMonthly, r.monthly.total, 0.01);
    within(c.rows[1].buyMonthly - c.rows[0].buyMonthly, r.price * 0.02 * (a.taxRate + a.insuranceRate) / 12, 0.01);
  });

  it("19. the credit spread reaches the note rate", () => {
    const m = monthlyFor(400_000, { ...base, credit: "fair" }, DEFAULTS);
    within(m.pi, monthlyPI(m.loan, DEFAULTS.rate + DEFAULTS.rateSpread.fair, DEFAULTS.termMonths), 0.001);
    expect(m.pi).toBeGreaterThan(monthlyFor(400_000, base, DEFAULTS).pi);
  });

  it("10c. the crossover scan reaches past the displayed horizon", () => {
    // Flat prices: owning pulls ahead only in year eight — after the five the
    // page shows, inside the ten it scans. Recorded from the model, kept so a
    // scan that stops at the displayed horizon cannot print "10+ years".
    const a = { ...DEFAULTS, appreciation: 0 };
    const c = compare(base, a, solvePrice(base, a).price);
    expect(c.crossoverYear).toBe(8);
    expect(c.crossoverYear).toBeGreaterThan(DEFAULTS.years);
  });

  it("5f. a zero-rate balance falls by the flat payment", () => {
    const x = golden.hand.pi_zero_rate;
    within(balanceAfter(x.loan, x.rate, x.term, 12), x.loan - 12 * x.expect, 0.05);
  });

  it("20. garbage assumptions do not hang or poison the result", () => {
    // Not a number at all: the default horizon. A number, just absurd: capped.
    const inf = compare(base, { ...DEFAULTS, years: Number.POSITIVE_INFINITY }, 400_000);
    expect(inf.years).toBe(DEFAULTS.years);
    const c = compare(base, { ...DEFAULTS, years: 100 }, 400_000);
    expect(c.years).toBe(40);
    expect(c.rows).toHaveLength(40);
    const n = compare(base, { ...DEFAULTS, years: Number.NaN, hoaMonthly: -1e9, rate: Number.NaN }, 400_000);
    expect(n.years).toBe(DEFAULTS.years);
    expect(Number.isFinite(n.net)).toBe(true);
    within(n.rows[0].buyMonthly, compare(base, DEFAULTS, 400_000).rows[0].buyMonthly, 0.01);
    const r = solvePrice(base, { ...DEFAULTS, hoaMonthly: Number.NaN });
    within(r.price, solvePrice(base, DEFAULTS).price, 0.01);
    const g = compare(base, { ...DEFAULTS, appreciation: Number.NaN, rentGrowth: Number.NaN }, 400_000);
    expect(Number.isFinite(g.net)).toBe(true);
    within(g.net, compare(base, DEFAULTS, 400_000).net, 0.01);
    expect(compare(base, { ...DEFAULTS, years: 0 }, 400_000).years).toBe(1);
  });
});

describe("what travels with the lead", () => {
  const inputs: Inputs = { rent: 2100, savings: 15000, credit: "good" };

  it("21. untouched assumptions send nothing — including a rate that went through a percent field", () => {
    // 6.71 / 100 is 0.06709999999999999 in floating point. A strict `!==`
    // against DEFAULTS.rate sent the untouched rate as an override on every
    // lead; the comparison has a tolerance now.
    const a: Assumptions = { ...DEFAULTS, rate: Number("6.71") / 100 };
    expect(a.rate === DEFAULTS.rate).toBe(false);
    expect(buildPayload(inputs, a, "es")).toEqual({ rent: 2100, savings: 15000, credit: "good", lang: "es" });
  });

  it("22. a moved slider or field travels, rounded, under the server's snake_case name", () => {
    const a: Assumptions = {
      ...DEFAULTS,
      rate: Number("6.5") / 100,
      appreciation: 3.25 / 100,
      rentGrowth: 0,
      hoaMonthly: 250,
    };
    expect(buildPayload(inputs, a, "en")).toEqual({
      rent: 2100,
      savings: 15000,
      credit: "good",
      lang: "en",
      rate: 0.065,
      appreciation: 0.0325,
      rent_growth: 0,
      hoa_monthly: 250,
    });
  });

  it("23. the page's limits are the server's", () => {
    // CalculatorIn: rent le=50_000, savings le=5_000_000, hoa_monthly le=5_000, rate le=0.20.
    expect(LIMITS).toEqual({ rent: 50_000, savings: 5_000_000, hoaMonthly: 5_000, ratePct: 20 });
  });
});

describe("the PMI cliff", () => {
  // 24. With 20% of the price in hand, the highest price that costs no more
  // than the rent sits at LTV 0.80 and can leave a real gap under the rent:
  // one more dollar of price switches PMI on. The page's copy depends on this
  // shape (it names the gap instead of claiming "the same monthly cost").
  it("24. leaves the solved price at LTV 0.80, under the rent, with PMI one dollar away", () => {
    const inputs = { rent: 2444, savings: 80_000, credit: "good" as const };
    const r = solvePrice(inputs, DEFAULTS);
    expect(r.cappedBy).toBe("rent");
    expect(r.loan / r.price).toBeCloseTo(0.8, 3);
    expect(r.monthly.pmi).toBe(0);
    expect(2444 - r.monthly.total).toBeGreaterThan(50);
    const up = monthlyFor(r.price + 1, inputs, DEFAULTS);
    expect(up.pmi).toBeGreaterThan(100);
    expect(up.total).toBeGreaterThan(2444);
  });
});

describe("long horizons", () => {
  const inputs: Inputs = { rent: 2000, savings: 30_000, credit: "good" };
  const price = solvePrice(inputs, DEFAULTS).price;

  // 25. The loan is 360 months. Charging its payment in year 31 inflated the
  // cost of owning at every horizon past the term — invisible while the page
  // only showed five years, and wrong the moment it offers thirty.
  it("25. the mortgage payment stops when the loan is paid off", () => {
    const c = compare(inputs, { ...DEFAULTS, years: 35 }, price);
    const y30 = c.rows.find((r) => r.year === 30)!;
    const y31 = c.rows.find((r) => r.year === 31)!;
    const y35 = c.rows.find((r) => r.year === 35)!;
    expect(y31.buyMonthly).toBeLessThan(y30.buyMonthly);
    // What drops out is exactly the principal and interest.
    const pi = monthlyFor(price, inputs, DEFAULTS).pi;
    expect(y30.buyMonthly - y31.buyMonthly).toBeGreaterThan(pi * 0.9);
    // And past the term only the carrying costs are left, which keep rising
    // with the home's value.
    expect(y35.buyMonthly).toBeGreaterThan(y31.buyMonthly);
    expect(y35.buyMonthly).toBeLessThan(pi);
  });

  // 26. The crossing was only ever searched for in years 1..10, so a visitor
  // looking twenty years out was told "renting stays cheaper" about a horizon
  // the page was not searching.
  it("26. the crossing is searched as far as the visitor is looking", () => {
    // A crossing INSIDE the horizon but past year 10: pinned to the year, so
    // narrowing the search back to 1..10 turns this red instead of quietly
    // returning null and printing "renting stays cheaper for this whole term".
    const slow: Inputs = { rent: 2000, savings: 30_000, credit: "good" };
    const flat = { ...DEFAULTS, appreciation: 0, rentGrowth: 0 };
    const p = solvePrice(slow, flat).price;
    expect(compare(slow, { ...flat, years: 20 }, p).crossoverYear).toBe(12);

    // Its twin: a crossing that really falls OUTSIDE the horizon. Here null is
    // the truth, and the sentence the page prints with it is true too.
    const falling = { ...flat, appreciation: -0.035 };
    expect(compare(slow, { ...falling, years: 20 }, p).crossoverYear).toBeNull();
    // Proof the null came from the horizon and not from a broken search: the
    // same assumptions, looked at for thirty years, do find the crossing.
    expect(compare(slow, { ...falling, years: 30 }, p).crossoverYear).toBe(25);
  });

  // 27. The curve the chart draws is the same arithmetic as the headline.
  it("27. the chart's curve agrees with compare() at every point", () => {
    const curve = netCurve(inputs, DEFAULTS, price, 30);
    expect(curve).toHaveLength(30);
    for (const year of [1, 5, 12, 30]) {
      const fromCurve = curve.find((c) => c.year === year)!.net;
      within(fromCurve, compare(inputs, { ...DEFAULTS, years: year }, price).net, 0.01);
    }
  });

  // 28. A figure thirty years out is worth much less than it reads.
  it("28. today's money discounts at the stated inflation", () => {
    within(inTodaysMoney(1000, 0.02, 0), 1000, 0.001);
    within(inTodaysMoney(1000, 0.02, 1), 1000 / 1.02, 0.001);
    within(inTodaysMoney(580_971, 0.02, 30), 580_971 / Math.pow(1.02, 30), 0.01);
    expect(inTodaysMoney(1000, Number.NaN, 10)).toBeCloseTo(1000 / Math.pow(1.02, 10), 6);
  });
});

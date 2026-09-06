/**
 * The rent-to-price arithmetic behind `/calculator`.
 *
 * A visitor types three things — what they pay in rent, what they have saved
 * and their credit range — and this module answers two questions: up to what
 * price could that same monthly money buy, and what does owning look like
 * against renting over a few years. Pure functions, no React, no DOM: the page
 * renders what comes out and the server (`backend/app/services/calculator.py`)
 * recomputes the same numbers from the same rules before storing them with a
 * lead. The two implementations read one golden fixture
 * (`backend/tests/fixtures/calculator_golden.json`), so they cannot drift apart
 * quietly.
 *
 * The model is the "Buy vs Rent" sheet a lender sent the brokerage, reproduced
 * to the dollar in the tests, with four deliberate departures: it starts from
 * the rent and solves for the price (the sheet starts from the price); it quotes
 * no APR and no lender language (the brokerage does not lend money); it drops
 * the tax benefit (it depends on bracket, filing status and itemizing); and
 * appreciation is a slider with a conservative default instead of a printed
 * fact — on the sheet that one number is 89% of the "gain".
 *
 * Every default carries its source and date in `SOURCES`. Rounding happens in
 * the view, never here.
 */

export type Credit = "excellent" | "good" | "fair";

export interface Inputs {
  /** Monthly rent today, dollars. */
  rent: number;
  /** Cash available for down payment and closing, dollars. */
  savings: number;
  credit: Credit;
}

export interface Assumptions {
  /** Annual note rate before the credit spread, e.g. 0.0671. */
  rate: number;
  termMonths: number;
  /** Property tax, share of value per year. */
  taxRate: number;
  /** Homeowners insurance, share of value per year. */
  insuranceRate: number;
  /** Upkeep, share of value per year — counted in the comparison ONLY. */
  maintenanceRate: number;
  hoaMonthly: number;
  /** Buyer closing costs, share of price. */
  closingRate: number;
  /** Cost to sell, share of the future value. */
  sellingRate: number;
  /** Minimum down payment, share of price. */
  minDown: number;
  /** Annual PMI on the loan while LTV > 80%, by credit range. */
  pmi: Record<Credit, number>;
  /** Added to `rate`, by credit range. Illustrative, not a quote. */
  rateSpread: Record<Credit, number>;
  /** Home value growth per year. */
  appreciation: number;
  /** Rent growth per year. */
  rentGrowth: number;
  /** Comparison horizon. */
  years: number;
  /** Below this price the page shows no figure. UX, not market. */
  priceFloor: number;
}

export interface Source {
  label: string;
  /** Empty when the value is a rule of thumb or a product constant. */
  url: string;
  asOf: string;
}

export const DEFAULTS: Assumptions = {
  rate: 0.0671,
  termMonths: 360,
  taxRate: 0.0052,
  insuranceRate: 0.007,
  maintenanceRate: 0.01,
  hoaMonthly: 0,
  closingRate: 0.015,
  sellingRate: 0.04,
  minDown: 0.03,
  pmi: { excellent: 0.0045, good: 0.008, fair: 0.013 },
  rateSpread: { excellent: 0, good: 0.0025, fair: 0.0075 },
  appreciation: 0.02,
  rentGrowth: 0.02,
  years: 5,
  priceFloor: 250_000,
};

export const SOURCES: Record<keyof Assumptions, Source> = {
  rate: {
    label: "Freddie Mac PMMS, 30-year fixed, via FRED (MORTGAGE30US)",
    url: "https://fred.stlouisfed.org/series/MORTGAGE30US",
    asOf: "2026-09-03",
  },
  termMonths: {
    label: "30-year fixed: the loan most first-time buyers use",
    url: "",
    asOf: "2026-09-05",
  },
  taxRate: {
    label: "Denver effective residential property tax, 0.48%–0.55% of market value",
    url: "https://propertytaxrates.org/blog/colorado-property-tax-guide-2026",
    asOf: "2026-09",
  },
  insuranceRate: {
    label: "Colorado average premium $3,200–$3,800 a year on a ~$450k home (estimate)",
    url: "https://www.moneygeek.com/insurance/homeowners/average-cost-home-insurance-colorado/",
    asOf: "2026-09",
  },
  maintenanceRate: {
    label: "The 1% rule of thumb for upkeep (estimate)",
    url: "",
    asOf: "2026-09-05",
  },
  hoaMonthly: {
    label: "Editable: Denver HOAs run from $0 to several hundred a month",
    url: "",
    asOf: "2026-09-05",
  },
  closingRate: {
    label: "Buy vs Rent reference sheet: $12,000 on an $800,000 purchase",
    url: "",
    asOf: "2026-09",
  },
  sellingRate: {
    label: "Buy vs Rent reference sheet: 4% of the future value",
    url: "",
    asOf: "2026-09",
  },
  minDown: {
    label: "Conventional 97 (3% down); FHA is 3.5%",
    url: "https://themortgagereports.com/21489/how-to-buy-a-home-conventional-loan-mortgage-rates-guidelines",
    asOf: "2026-09",
  },
  pmi: {
    label: "2026 PMI ranges by credit tier with about 5% down (illustrative)",
    url: "https://www.altgage.com/blog/how-much-is-pmi",
    asOf: "2026-09",
  },
  rateSpread: {
    label: "Illustrative rate spread by credit range — not a lender quote",
    url: "",
    asOf: "2026-09-05",
  },
  appreciation: {
    label: "Case-Shiller Denver: −1.8% year over year (May 2026); 2% is a conservative long-run default",
    url: "https://fred.stlouisfed.org/series/DNXRSA",
    asOf: "2026-05",
  },
  rentGrowth: {
    label: "Denver rents −1.5% to −3% year over year in 2026; 2% is a conservative default",
    url: "https://www.zillow.com/rental-manager/market-trends/denver-co/",
    asOf: "2026-09",
  },
  years: {
    label: "Five years: a typical first-buyer horizon, and the hardest case for buying",
    url: "",
    asOf: "2026-09-05",
  },
  priceFloor: {
    label:
      "Below this Denver has almost nothing to buy: the median condo sells for $310,000 and entry condos start around $300,000",
    url: "https://www.redfin.com/city/5155/CO/Denver/housing-market",
    asOf: "2026-09",
  },
};

/** A non-finite or negative dollar amount is treated as zero. */
function dollars(n: number): number {
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** A rate that is not a finite number falls back to the default. */
function finite(n: number, fallback: number): number {
  return Number.isFinite(n) ? n : fallback;
}

/** The longest horizon the comparison will scan. */
const MAX_YEARS = 40;

/**
 * The assumptions the page lets a visitor edit are the ones that can arrive
 * as garbage: an emptied field is `NaN`, a negative HOA is nonsense, and an
 * unbounded `years` is a loop that never returns.
 */
function normalize(a: Assumptions): Assumptions {
  return {
    ...a,
    rate: finite(a.rate, DEFAULTS.rate),
    appreciation: finite(a.appreciation, DEFAULTS.appreciation),
    rentGrowth: finite(a.rentGrowth, DEFAULTS.rentGrowth),
    hoaMonthly: dollars(a.hoaMonthly),
    years: clamp(finite(Math.floor(a.years), DEFAULTS.years), 1, MAX_YEARS),
  };
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(Math.max(n, lo), hi);
}

/** Note rate for a credit range: the base rate plus its spread. */
function noteRate(a: Assumptions, credit: Credit): number {
  return a.rate + a.rateSpread[credit];
}

/** Level monthly principal-and-interest payment. */
export function monthlyPI(loan: number, annualRate: number, termMonths: number): number {
  if (loan <= 0) return 0;
  const r = annualRate / 12;
  if (r === 0) return loan / termMonths;
  return (loan * r) / (1 - Math.pow(1 + r, -termMonths));
}

/** Remaining balance after `monthsPaid` level payments. Never negative. */
export function balanceAfter(
  loan: number,
  annualRate: number,
  termMonths: number,
  monthsPaid: number,
): number {
  if (loan <= 0) return 0;
  const m = monthlyPI(loan, annualRate, termMonths);
  const r = annualRate / 12;
  const k = clamp(monthsPaid, 0, termMonths);
  if (r === 0) return Math.max(0, loan - m * k);
  const growth = Math.pow(1 + r, k);
  return Math.max(0, loan * growth - (m * (growth - 1)) / r);
}

/** Value after `years` of compound growth at `annualRate`. */
export function futureValue(price: number, annualRate: number, years: number): number {
  return price * Math.pow(1 + annualRate, years);
}

export interface Monthly {
  pi: number;
  tax: number;
  insurance: number;
  pmi: number;
  hoa: number;
  total: number;
}

/**
 * What a home at `price` costs per month for this buyer — the number a lender
 * qualifies on. Upkeep is deliberately NOT here: a lender does not count it,
 * and adding it would produce a figure that looks nothing like the bank's.
 */
export function monthlyFor(
  price: number,
  inputs: Inputs,
  raw: Assumptions,
): Monthly & { loan: number; down: number; closing: number } {
  const a = normalize(raw);
  const v = dollars(price);
  const savings = dollars(inputs.savings);
  const closing = a.closingRate * v;
  const down = clamp(savings - closing, 0, v);
  const loan = v - down;
  const ltv = v > 0 ? loan / v : 0;
  const pi = monthlyPI(loan, noteRate(a, inputs.credit), a.termMonths);
  const tax = (v * a.taxRate) / 12;
  const insurance = (v * a.insuranceRate) / 12;
  const pmi = ltv > 0.8 ? (loan * a.pmi[inputs.credit]) / 12 : 0;
  const hoa = a.hoaMonthly;
  return { pi, tax, insurance, pmi, hoa, total: pi + tax + insurance + pmi + hoa, loan, down, closing };
}

export type CappedBy = "rent" | "savings" | "floor";

export interface PriceResult {
  price: number;
  loan: number;
  down: number;
  closing: number;
  monthly: Monthly;
  cappedBy: CappedBy;
}

/** The search ceiling. A rent no price under it can absorb returns it as-is. */
export const UPPER = 5_000_000;

/**
 * The server's bounds (`CalculatorIn` in `backend/app/api/v1/public.py`). The
 * page clamps its fields to them so it never shows a figure the server would
 * refuse to store beside the lead.
 */
export const LIMITS = { rent: 50_000, savings: 5_000_000, hoaMonthly: 5_000, ratePct: 20 } as const;

/**
 * The price whose monthly cost equals the rent, capped by what the savings can
 * put down. Bisection: `monthlyFor(v).total` is monotone non-decreasing in `v`
 * (every term is, and the cap on `down` keeps `loan` so).
 */
export function solvePrice(inputs: Inputs, raw: Assumptions): PriceResult {
  const a = normalize(raw);
  const rent = dollars(inputs.rent);
  const savings = dollars(inputs.savings);
  const total = (v: number) => monthlyFor(v, inputs, a).total;

  let vRent: number;
  if (total(UPPER) < rent) {
    vRent = UPPER;
  } else {
    let lo = 0;
    let hi = UPPER;
    let converged: number | null = null;
    for (let i = 0; i < 80; i++) {
      const mid = (lo + hi) / 2;
      const t = total(mid);
      if (Math.abs(t - rent) < 0.5) {
        converged = mid;
        break;
      }
      if (t < rent) lo = mid;
      else hi = mid;
    }
    // The monthly cost jumps where PMI starts (LTV 80%), so a rent inside
    // that jump has no price within the tolerance and the loop runs out with
    // `lo` and `hi` pinned to either side of the cliff. `lo` is the highest
    // price that still costs no more than the rent — the honest answer. `hi`
    // would be a price the page then describes as "the same monthly cost"
    // while showing a total hundreds of dollars above it.
    vRent = converged ?? lo;
  }

  // The minimum down payment and the closing costs come out of the same
  // savings. With neither required, savings never cap the price.
  const entry = a.minDown + a.closingRate;
  const vSavings = entry > 0 ? savings / entry : Infinity;

  const price = Math.min(vRent, vSavings);
  let cappedBy: CappedBy = price === vRent ? "rent" : "savings";
  if (price < a.priceFloor) cappedBy = "floor";

  const m = monthlyFor(price, inputs, a);
  return {
    price,
    loan: m.loan,
    down: m.down,
    closing: m.closing,
    monthly: { pi: m.pi, tax: m.tax, insurance: m.insurance, pmi: m.pmi, hoa: m.hoa, total: m.total },
    cappedBy,
  };
}

export interface YearRow {
  year: number;
  buyMonthly: number;
  rentMonthly: number;
}

export interface Comparison {
  years: number;
  appreciation: number;
  amortization: number;
  cashflowDiff: number;
  closing: number;
  selling: number;
  net: number;
  buyTotal: number;
  rentTotal: number;
  rows: YearRow[];
  /** First horizon in 1..10 where owning nets more than renting; null if none. */
  crossoverYear: number | null;
}

interface Horizon {
  appreciation: number;
  amortization: number;
  cashflowDiff: number;
  closing: number;
  selling: number;
  net: number;
  buyTotal: number;
  rentTotal: number;
  rows: YearRow[];
}

function horizon(inputs: Inputs, raw: Assumptions, price: number, years: number): Horizon {
  const a = normalize(raw);
  const v = dollars(price);
  const rent = dollars(inputs.rent);
  const m = monthlyFor(v, inputs, a);
  const rate = noteRate(a, inputs.credit);
  const pmiMonthly = (m.loan * a.pmi[inputs.credit]) / 12;
  const carry = (a.taxRate + a.insuranceRate + a.maintenanceRate) / 12;

  const rows: YearRow[] = [];
  let buyTotal = 0;
  let rentTotal = 0;
  for (let y = 1; y <= years; y++) {
    const value = v * Math.pow(1 + a.appreciation, y - 1);
    const balanceAtStart = balanceAfter(m.loan, rate, a.termMonths, 12 * (y - 1));
    // PMI drops off once the balance falls under 80% of the purchase price.
    const pmi = v > 0 && balanceAtStart / v > 0.8 ? pmiMonthly : 0;
    const buyMonthly = m.pi + value * carry + pmi + a.hoaMonthly;
    const rentMonthly = rent * Math.pow(1 + a.rentGrowth, y - 1);
    rows.push({ year: y, buyMonthly, rentMonthly });
    buyTotal += 12 * buyMonthly;
    rentTotal += 12 * rentMonthly;
  }

  const cashflowDiff = rentTotal - buyTotal;
  const closing = a.closingRate * v;
  const valueN = futureValue(v, a.appreciation, years);
  const selling = a.sellingRate * valueN;
  const appreciation = valueN - v;
  const amortization = m.loan - balanceAfter(m.loan, rate, a.termMonths, 12 * years);
  const net = appreciation + amortization + cashflowDiff - closing - selling;
  return { appreciation, amortization, cashflowDiff, closing, selling, net, buyTotal, rentTotal, rows };
}

/**
 * Owning at `price` against renting, over `a.years`. Renting carries no
 * renter's insurance and owning carries upkeep: both choices lean against
 * buying, on purpose. A negative `net` is a result, not an error.
 */
export function compare(inputs: Inputs, raw: Assumptions, price: number): Comparison {
  const a = normalize(raw);
  const years = a.years;
  const h = horizon(inputs, a, price, years);
  let crossoverYear: number | null = null;
  for (let n = 1; n <= 10; n++) {
    if (horizon(inputs, a, price, n).net > 0) {
      crossoverYear = n;
      break;
    }
  }
  return { years, ...h, crossoverYear };
}

/**
 * What travels with the lead: the inputs, the page's language, and only the
 * assumptions that moved off their defaults — the server recomputes from
 * these. Mirrors `CalculatorIn` on the server; `lib/api.ts` re-exports it.
 */
export interface CalculatorPayload {
  rent: number;
  savings: number;
  credit: Credit;
  appreciation?: number;
  rent_growth?: number;
  rate?: number;
  hoa_monthly?: number;
  lang?: "en" | "es";
}

/** Six decimals: enough for a rate in percent with two, and stable to compare. */
function round6(n: number): number {
  return Number(n.toFixed(6));
}

/**
 * Builds the payload. "Moved" is decided with a tolerance, not `!==`:
 * `6.71 / 100` is `0.06709999999999999`, not `0.0671`, and a strict
 * comparison sent the untouched rate as an override on every lead.
 */
export function buildPayload(inputs: Inputs, a: Assumptions, lang: "en" | "es"): CalculatorPayload {
  const moved = (x: number, d: number) => Math.abs(x - d) > 1e-9;
  const p: CalculatorPayload = {
    rent: inputs.rent,
    savings: inputs.savings,
    credit: inputs.credit,
    lang,
  };
  if (moved(a.appreciation, DEFAULTS.appreciation)) p.appreciation = round6(a.appreciation);
  if (moved(a.rentGrowth, DEFAULTS.rentGrowth)) p.rent_growth = round6(a.rentGrowth);
  if (moved(a.rate, DEFAULTS.rate)) p.rate = round6(a.rate);
  if (moved(a.hoaMonthly, DEFAULTS.hoaMonthly)) p.hoa_monthly = a.hoaMonthly;
  return p;
}

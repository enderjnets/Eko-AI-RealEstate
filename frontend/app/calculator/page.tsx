"use client";

/**
 * `/calculator`: what your rent could buy, and what five years of owning
 * looks like against renting. The page a Short promises.
 *
 * Three inputs, everything else an assumption the visitor can see and, for
 * the ones that move the answer most, move. The number is shown before
 * anything is asked — the result is free, the form comes after. All the
 * arithmetic lives in `lib/calculator.ts` and is recomputed by the server when
 * a lead is captured; this file only renders.
 *
 * Deliberately NOT a loan page: no APR, no lender language, no tax benefit.
 * The brokerage does not lend money, and the disclaimer says so in both
 * languages. A negative five-year net is shown as such — never hidden.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { ConsultForm } from "@/components/landing/ConsultForm";
import { LandingTracker } from "@/components/landing/LandingTracker";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import {
  DEFAULTS,
  LIMITS,
  SOURCES,
  UPPER,
  buildPayload,
  compare,
  solvePrice,
  type Assumptions,
  type CalculatorPayload,
  type Credit,
  type Inputs,
} from "@/lib/calculator";
import { useI18n } from "@/lib/i18n";
import { LANDING } from "@/lib/landing";
import { getTracker } from "@/lib/track";

/** The sections the tracker measures. Every id must be in `LANDING_SECTIONS`. */
const SECTIONS = ["inputs", "result", "compare", "consult"] as const;
const CREDITS: readonly Credit[] = ["excellent", "good", "fair"];
const DEBOUNCE_MS = 150;
/** Slider range for the two growth rates, in percent. */
const SLIDER = { min: 0, max: 5, step: 0.25 };
/** One-tap amounts. A phone keyboard is the slowest part of this page, and
 *  these are the Denver rents and the down payments people actually type. */
const QUICK_RENT = [1500, 2000, 2500] as const;
const QUICK_SAVINGS = [10_000, 25_000, 50_000] as const;

/** A number from a money field: digits and one dot, nothing else; never NaN;
 *  never above what the server accepts, so the figure shown is one the lead
 *  can carry. */
function dollars(raw: string, max: number): number {
  const n = Number(raw.replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) && n > 0 ? Math.min(n, max) : 0;
}

/** A percent from a rate field, bounded like the server's `CalculatorIn`.
 *  Empty is "not set", not zero: `Number("")` is 0, and a field cleared to be
 *  retyped must not price the loan at 0% in the meantime. A comma decimal is
 *  what an ES keyboard offers. */
function ratePercent(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed.replace(",", "."));
  return Number.isFinite(n) && n >= 0 && n <= LIMITS.ratePct ? n : null;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

const READ_ONLY: ReadonlyArray<{ key: keyof Assumptions; label: string }> = [
  { key: "taxRate", label: "calculator.assumptions.tax" },
  { key: "insuranceRate", label: "calculator.assumptions.insurance" },
  { key: "maintenanceRate", label: "calculator.assumptions.maintenance" },
  { key: "closingRate", label: "calculator.assumptions.closing" },
  { key: "sellingRate", label: "calculator.assumptions.selling" },
  { key: "pmi", label: "calculator.assumptions.pmi" },
  { key: "rateSpread", label: "calculator.assumptions.rateSpread" },
  { key: "minDown", label: "calculator.assumptions.minDown" },
];

export default function CalculatorPage() {
  const { t, lang } = useI18n();
  const locale = lang === "es" ? "es-US" : "en-US";
  const usd = useMemo(
    () =>
      new Intl.NumberFormat(locale, { style: "currency", currency: "USD", maximumFractionDigits: 0 }),
    [locale],
  );
  const grouped = useMemo(
    () => new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
    [locale],
  );
  const pct = (n: number, digits = 2) => `${(n * 100).toFixed(digits)}%`;

  const [rentRaw, setRentRaw] = useState("");
  const [savingsRaw, setSavingsRaw] = useState("");
  const [credit, setCredit] = useState<Credit>("good");
  const [appreciationPct, setAppreciationPct] = useState(DEFAULTS.appreciation * 100);
  const [rentGrowthPct, setRentGrowthPct] = useState(DEFAULTS.rentGrowth * 100);
  const [rateRaw, setRateRaw] = useState((DEFAULTS.rate * 100).toFixed(2));
  const [hoaRaw, setHoaRaw] = useState("");

  const rent = useDebounced(dollars(rentRaw, LIMITS.rent), DEBOUNCE_MS);
  const savings = useDebounced(dollars(savingsRaw, LIMITS.savings), DEBOUNCE_MS);
  const ratePct = ratePercent(rateRaw);

  const assumptions: Assumptions = useMemo(
    () => ({
      ...DEFAULTS,
      appreciation: appreciationPct / 100,
      rentGrowth: rentGrowthPct / 100,
      rate: ratePct === null ? DEFAULTS.rate : ratePct / 100,
      hoaMonthly: dollars(hoaRaw, LIMITS.hoaMonthly),
    }),
    [appreciationPct, rentGrowthPct, ratePct, hoaRaw],
  );
  const inputs: Inputs = useMemo(() => ({ rent, savings, credit }), [rent, savings, credit]);

  // Both money fields must have been typed: an untouched savings field is
  // "not yet", not "$0" — and $0 is a floor answer the visitor did not ask for.
  const savingsTyped = savingsRaw.trim() !== "";
  const result = useMemo(
    () => (rent > 0 && savingsTyped ? solvePrice(inputs, assumptions) : null),
    [inputs, assumptions, rent, savingsTyped],
  );
  const shown = result !== null && result.cappedBy !== "floor";
  const comparison = useMemo(
    () => (result && shown ? compare(inputs, assumptions, result.price) : null),
    [inputs, assumptions, result, shown],
  );

  // One funnel event per page load, on the first figure actually shown. The
  // tracker deduplicates too; the ref keeps this effect from even asking.
  const reported = useRef(false);
  useEffect(() => {
    if (reported.current || !result || !shown) return;
    reported.current = true;
    getTracker()?.record("calculator_result", {
      price_k: Math.round(result.price / 1000),
      capped: result.cappedBy,
      credit,
    });
  }, [result, shown, credit]);

  // What travels with the lead: the inputs and only the sliders that moved,
  // and only once the page has a figure to stand behind. The server recomputes
  // all of it; a form sent before the numbers are typed carries nothing —
  // one more way a calculation can never cost the lead.
  const payload: CalculatorPayload | undefined = useMemo(
    () => (result ? buildPayload(inputs, assumptions, lang) : undefined),
    [result, inputs, assumptions, lang],
  );

  const brandLine = [LANDING.brand, LANDING.advisors].filter(Boolean).join(" · ");
  // The footer mirrors `/fall` and the landing exactly: this is real-estate
  // advertising by licensed agents, and the brokerage disclosure must read the
  // same on every page.
  const footerWho = [LANDING.brand, LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ");
  const legal = [
    LANDING.address,
    LANDING.brokerage ? "Licensed in Colorado" : "",
    LANDING.brokerage ? "Equal Housing Opportunity" : "",
  ].filter(Boolean);

  // At the PMI cliff the highest price that costs no more than the rent can sit
  // well under it: one more dollar of price adds mortgage insurance and the
  // payment overshoots. "The same monthly cost as your rent" would be false
  // there by up to several hundred dollars (measured: $578 at $250k saved), so
  // the sentence names the gap and the reason instead.
  const cliffGap =
    result && result.cappedBy === "rent" && result.price < UPPER ? rent - result.monthly.total : 0;
  const atCliff = cliffGap > 20;

  const priceLabel = result
    ? result.price >= UPPER
      ? t("calculator.result.ceiling")
      : usd.format(Math.round(result.price / 1000) * 1000)
    : null;

  const rows = comparison ? comparison.rows.filter((r) => [1, 3, 5].includes(r.year)) : [];

  // The five parts of the five-year answer, in the order the plan lists them,
  // with the largest magnitude setting the scale for every bar.
  const cascade = comparison
    ? [
        { label: "calculator.compare.appreciation", amount: comparison.appreciation },
        { label: "calculator.compare.amortization", amount: comparison.amortization },
        { label: "calculator.compare.cashflow", amount: comparison.cashflowDiff },
        { label: "calculator.compare.closing", amount: -comparison.closing },
        { label: "calculator.compare.selling", amount: -comparison.selling },
      ]
    : [];
  const cascadeMax = cascade.reduce((m, c) => Math.max(m, Math.abs(c.amount)), 0);

  return (
    <main className="min-h-screen bg-ln-canvas text-ln-body">
      <LandingTracker variant="calculator" sections={SECTIONS} />
      {/* A band of the city under the question. Decorative — empty alt, and it
          fades into the canvas so no text ever sits on the photograph. Same
          plain <img> the landing uses. */}
      <div className="lg:flex lg:min-h-screen lg:items-stretch">
      {/* The instrument: on a wide screen it stays put while the answer scrolls
          beside it, so changing the rent never means losing sight of the
          figure. On a phone it is simply the top of the page. */}
      <aside className="bg-ln-paper lg:sticky lg:top-0 lg:h-screen lg:w-[452px] lg:flex-none lg:overflow-y-auto lg:border-r lg:border-ln-hair">
      <div className="relative h-[132px] overflow-hidden lg:hidden" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element -- the public
            pages use plain <img> throughout: `sharp` is not installed, so
            next/image would optimise nothing and only add a dependency. */}
        <img
          src="/landing/denver-card.jpg"
          alt=""
          decoding="async"
          className="h-full w-full object-cover [object-position:50%_58%]"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-ln-night/30 via-ln-canvas/25 to-ln-canvas" />
      </div>
      <div className="px-5 pb-10 pt-7 sm:px-8 lg:px-11 lg:py-10">
        <div className="flex items-center justify-between gap-4">
          {brandLine ? (
            <a
              href="/"
              className="inline-block text-[11px] uppercase tracking-[0.2em] text-ln-gold hover:text-ln-dark"
            >
              {brandLine}
            </a>
          ) : (
            <span />
          )}
          {/* The switcher is styled for the dark hero; on this light canvas
              its default grey is invisible (1.3:1). Same override the landing
              uses, in the light palette. */}
          <span className="[&_button]:text-ln-body [&_button:hover]:text-ln-dark">
            <LanguageSwitcher />
          </span>
        </div>

        <h1 className="mt-5 font-ln-serif text-[34px] leading-[1.06] text-ln-ink sm:text-[44px]">
          {t("calculator.title")}
        </h1>
        <p className="mt-4 max-w-[46ch] text-[15px] leading-[1.7] text-ln-muted">
          {t("calculator.intro")}
        </p>

        {/* ── Inputs ─────────────────────────────────────────────────── */}
        <section id="inputs" aria-label={t("calculator.inputs.heading")} className="mt-8 scroll-mt-10">
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-1">
            <MoneyField
              id="calc-rent"
              label={t("calculator.inputs.rent")}
              value={rentRaw}
              onChange={setRentRaw}
              suffix={t("calculator.inputs.perMonth")}
              quick={QUICK_RENT}
              format={(n) => usd.format(n)}
              group={(n) => grouped.format(n)}
            />
            <MoneyField
              id="calc-savings"
              label={t("calculator.inputs.savings")}
              value={savingsRaw}
              onChange={setSavingsRaw}
              quick={QUICK_SAVINGS}
              format={(n) => usd.format(n)}
              group={(n) => grouped.format(n)}
            />
          </div>
          <fieldset className="mt-6">
            <legend className="text-[11px] uppercase tracking-[0.14em] text-ln-muted">
              {t("calculator.inputs.credit")}
            </legend>
            <div className="mt-3 flex flex-wrap gap-2">
              {CREDITS.map((c) => {
                const active = credit === c;
                return (
                  <button
                    key={c}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setCredit(c)}
                    // 44px floor: below it a thumb misses on a phone.
                    className={`min-h-[44px] px-[18px] text-[11px] uppercase tracking-[0.14em] transition-colors ${
                      active
                        ? "bg-ln-dark text-ln-cream"
                        : "border border-ln-line-strong text-ln-body hover:border-ln-dark hover:text-ln-dark"
                    }`}
                  >
                    {t(`calculator.credit.${c}`)}
                  </button>
                );
              })}
            </div>
          </fieldset>
          <p className="mt-8 hidden text-[11px] leading-[1.7] text-ln-faint lg:block">
            {t("calculator.disclaimer")}
          </p>
        </section>
      </div>
      </aside>

      {/* The answer, and everything that explains it. */}
      <div className="min-w-0 flex-1 px-5 pb-14 pt-2 sm:px-8 lg:px-12 lg:py-10">
        {/* ── Result ─────────────────────────────────────────────────── */}
        <section id="result" className="scroll-mt-10">
          {!(result && shown) && (
            /* The empty state wears the answer's own chrome: on a wide screen
               the column is otherwise a void, and a visitor cannot tell what
               typing buys them. Nothing here is a number — the dashes are
               decoration and are hidden from screen readers. */
            <div className="border border-ln-line bg-ln-paper/60 p-6 sm:p-9">
              <h2 className="text-[11px] uppercase tracking-[0.18em] text-ln-gold">
                {t("calculator.result.heading")}
              </h2>
              {result && !shown ? (
                <p className="mt-4 text-[16px] leading-[1.7]">{t("calculator.result.floor")}</p>
              ) : (
                <>
                  <p
                    aria-hidden="true"
                    className="mt-3 font-ln-serif text-[52px] leading-[0.95] text-ln-line-strong sm:text-[78px]"
                  >
                    $&mdash;&mdash;&mdash;
                  </p>
                  <p className="mt-4 text-[15px] leading-[1.7] text-ln-muted">
                    {t("calculator.result.empty")}
                  </p>
                  <div
                    aria-hidden="true"
                    className="mt-7 flex flex-wrap gap-x-10 gap-y-5 border-t border-ln-hair pt-6"
                  >
                    {[
                      t("calculator.monthly.total"),
                      t("calculator.result.down"),
                      t("calculator.result.loan"),
                    ].map((label) => (
                      <div key={label}>
                        <p className="text-[11px] uppercase tracking-[0.14em] text-ln-faint">{label}</p>
                        <p className="mt-1 font-ln-serif text-[20px] leading-none text-ln-line-strong">
                          &mdash;
                        </p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          {result && shown && (
            /* The answer gets a ground of its own. Flat on the canvas it read
               as one more paragraph; the seven-row breakdown competed with the
               figure the visitor came for, so it folds away behind a summary —
               nothing is removed, it is ranked. */
            <div className="border border-ln-line bg-ln-paper p-6 shadow-[0_2px_28px_-20px_rgba(23,21,15,0.7)] sm:p-9">
              {/* The label belongs to the figure, so it lives inside the card. */}
              <h2 className="text-[11px] uppercase tracking-[0.18em] text-ln-gold">
                {t("calculator.result.heading")}
              </h2>
              <p
                data-testid="calc-price"
                className="mt-3 font-ln-serif text-[52px] leading-[0.95] text-ln-ink sm:text-[78px]"
              >
                {priceLabel}
              </p>
              <p className="mt-4 text-[15px] leading-[1.7]">
                {result.cappedBy === "savings"
                  ? t("calculator.result.capped.savings", { n: Math.round(DEFAULTS.minDown * 100) })
                  : atCliff
                    ? t("calculator.result.capped.pmi", { gap: usd.format(Math.round(cliffGap)) })
                    : t("calculator.result.capped.rent")}
              </p>
              <div className="mt-7 flex flex-wrap gap-x-10 gap-y-5 border-t border-ln-hair pt-6">
                <Stat
                  label={t("calculator.monthly.total")}
                  value={usd.format(Math.round(result.monthly.total))}
                  lead
                />
                <Stat label={t("calculator.result.down")} value={usd.format(Math.round(result.down))} />
                <Stat label={t("calculator.result.loan")} value={usd.format(Math.round(result.loan))} />
              </div>
              <details className="mt-7 border-t border-ln-hair pt-5">
                <summary className="cursor-pointer text-[11px] uppercase tracking-[0.14em] text-ln-dark">
                  {t("calculator.monthly.heading")}
                </summary>
              <dl className="mt-3 divide-y divide-ln-hair text-[14px]">
                <Line label={t("calculator.monthly.pi")} value={usd.format(Math.round(result.monthly.pi))} />
                <Line label={t("calculator.monthly.tax")} value={usd.format(Math.round(result.monthly.tax))} />
                <Line
                  label={t("calculator.monthly.insurance")}
                  value={usd.format(Math.round(result.monthly.insurance))}
                />
                {result.monthly.pmi > 0 && (
                  <Line label={t("calculator.monthly.pmi")} value={usd.format(Math.round(result.monthly.pmi))} />
                )}
                {result.monthly.hoa > 0 && (
                  <Line label={t("calculator.monthly.hoa")} value={usd.format(Math.round(result.monthly.hoa))} />
                )}
                <Line
                  label={t("calculator.monthly.total")}
                  value={usd.format(Math.round(result.monthly.total))}
                  strong
                />
              </dl>
              </details>
            </div>
          )}
          <p className="mt-6 text-[12px] leading-[1.7] text-ln-muted lg:hidden">
            {t("calculator.disclaimer")}
          </p>
        </section>

        {/* ── Compare ────────────────────────────────────────────────── */}
        <section id="compare" className="mt-12 scroll-mt-10 border-t border-ln-hair pt-10">
          <h2 className="font-ln-serif text-[22px] text-ln-dark">{t("calculator.compare.heading")}</h2>
          {comparison && (
            <>
              <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-ln-muted">
                {t("calculator.compare.net")}
              </p>
              <p
                className={`mt-2 font-ln-serif text-[36px] leading-none sm:text-[44px] ${
                  comparison.net > 0 ? "text-emerald-800" : "text-ln-dark"
                }`}
              >
                {comparison.net >= 0 ? "+" : "−"}
                {usd.format(Math.round(Math.abs(comparison.net)))}
              </p>
              <p className="mt-3 text-[15px] leading-[1.7]">
                {comparison.crossoverYear === null
                  ? t("calculator.compare.noCrossover")
                  : t("calculator.compare.crossover", { n: comparison.crossoverYear })}
              </p>
              {/* Five signed figures in a column say which is which but not
                  which one weighs; the bars are scaled to the largest so the
                  answer's shape is readable before the numbers are. */}
              <div className="mt-6 flex flex-col gap-3">
                {cascade.map((c) => (
                  <Bar key={c.label} label={t(c.label)} amount={c.amount} max={cascadeMax} usd={usd} />
                ))}
              </div>
              <div className="mt-6 overflow-x-auto">
                <table className="w-full text-left text-[14px]">
                  <thead className="text-[11px] uppercase tracking-[0.14em] text-ln-muted">
                    <tr>
                      <th className="py-2 pr-4 font-normal">{t("calculator.compare.year")}</th>
                      <th className="py-2 pr-4 font-normal">{t("calculator.compare.buyMonthly")}</th>
                      <th className="py-2 font-normal">{t("calculator.compare.rentMonthly")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ln-hair">
                    {rows.map((r) => (
                      <tr key={r.year}>
                        <td className="py-2 pr-4">{r.year}</td>
                        <td className="py-2 pr-4">{usd.format(Math.round(r.buyMonthly))}</td>
                        <td className="py-2">{usd.format(Math.round(r.rentMonthly))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="mt-8 grid gap-6 sm:grid-cols-2">
            <Slider
              id="calc-appreciation"
              label={t("calculator.compare.appreciationSlider")}
              value={appreciationPct}
              onChange={setAppreciationPct}
            />
            <Slider
              id="calc-rent-growth"
              label={t("calculator.compare.rentGrowthSlider")}
              value={rentGrowthPct}
              onChange={setRentGrowthPct}
            />
          </div>

          <details className="mt-8 border border-ln-hair p-5">
            <summary className="cursor-pointer text-[11px] uppercase tracking-[0.14em] text-ln-dark">
              {t("calculator.assumptions.heading")}
            </summary>
            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              <div>
                <label className="block text-[12px] text-ln-muted" htmlFor="calc-rate">
                  {t("calculator.assumptions.rate")}
                  <input
                    id="calc-rate"
                    type="text"
                    inputMode="decimal"
                    value={rateRaw}
                    onChange={(e) => setRateRaw(e.target.value)}
                    aria-describedby="calc-rate-source"
                    className="mt-1 h-11 w-full border-b border-ln-line-strong bg-transparent text-[15px] text-ln-dark outline-none focus:border-ln-dark"
                  />
                </label>
                <Source id="calc-rate-source" source={SOURCES.rate} t={t} />
              </div>
              <div>
                <label className="block text-[12px] text-ln-muted" htmlFor="calc-hoa">
                  {t("calculator.assumptions.hoa")}
                  <input
                    id="calc-hoa"
                    type="text"
                    inputMode="decimal"
                    value={hoaRaw}
                    onChange={(e) => setHoaRaw(e.target.value)}
                    placeholder="0"
                    aria-describedby="calc-hoa-source"
                    className="mt-1 h-11 w-full border-b border-ln-line-strong bg-transparent text-[15px] text-ln-dark outline-none focus:border-ln-dark"
                  />
                </label>
                <Source id="calc-hoa-source" source={SOURCES.hoaMonthly} t={t} />
              </div>
            </div>
            <dl className="mt-5 divide-y divide-ln-hair text-[13px]">
              {READ_ONLY.map(({ key, label }) => {
                const raw = assumptions[key];
                const value =
                  typeof raw === "number"
                    ? pct(raw)
                    : pct((raw as Record<Credit, number>)[credit]);
                return (
                  <div key={key} className="py-2">
                    <dt className="flex items-baseline justify-between gap-x-4 text-ln-muted">
                      <span>
                        {t(label)} <span className="italic">({t("calculator.assumptions.estimate")})</span>
                      </span>
                      <span className="text-ln-dark">{value}</span>
                    </dt>
                    <dd>
                      <Source source={SOURCES[key]} t={t} />
                    </dd>
                  </div>
                );
              })}
            </dl>
          </details>
        </section>

        {/* ── Consult: the shared form, with the calculation riding along ── */}
      </div>
      </div>
      <section id="consult" className="relative mt-14 scroll-mt-10 overflow-hidden bg-ln-dark">
        {/* The frame carries an MLS watermark baked along its bottom edge, and
            at this section's aspect ratio `object-position` cannot crop enough
            of it away — measured on screen at 1280 and at 390. Rendering it
            taller than the box and anchoring it to the top puts the watermark
            out of view at every width. */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element -- see the band above. */}
          <img
            src="/landing/cta-bg.jpg"
            alt=""
            loading="lazy"
            decoding="async"
            className="absolute left-0 top-0 h-[125%] w-full object-cover object-top"
          />
        </div>
        {/* Two reasons for the scrim, both measured on screen: the photograph's
            bright patches lifted the ground until the small print stopped being
            readable, and the source frame carries an MLS watermark along its
            bottom edge — the crop above pushes it out of view and this covers
            what is left. Same treatment the landing gives the same file. */}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(20,18,14,0.88)_0%,rgba(20,18,14,0.82)_55%,rgba(20,18,14,0.94)_100%)]" />
        <div className="relative mx-auto max-w-2xl px-5 py-14 sm:px-8 sm:py-16">
          {LANDING.advisors && (
            <div className="flex items-center gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element -- see above. */}
              <img
                src="/landing/natalia-robbie.jpg"
                alt={LANDING.advisors}
                loading="lazy"
                decoding="async"
                className="h-12 w-12 flex-none rounded-full object-cover ring-1 ring-ln-cream/30 [object-position:50%_12%]"
              />
              <p className="text-[11px] uppercase tracking-[0.18em] text-ln-canvas/70">
                {LANDING.advisors}
              </p>
            </div>
          )}
          <h2 className="mt-6 font-ln-serif text-[28px] leading-tight text-ln-cream sm:text-[36px]">
            {/* Anchored to the figure they just saw, when there is one. */}
            {shown && priceLabel
              ? t("calculator.cta.headingPriced", { price: priceLabel })
              : t("calculator.cta.heading")}
          </h2>
          <p className="mt-4 text-[15px] leading-[1.7] text-ln-canvas/80">{t("calculator.cta.body")}</p>
          <p className="mt-2 text-[13px] leading-[1.7] text-ln-canvas/75">
            {t("calculator.cta.reassure")}
          </p>
          {/* The form is shared with `/`, `/fall` and `/contact`; its own file is
              not touched. The dark-panel styling is nudged from here so a change
              on this page can never move a pixel on those three. */}
          <div className="mt-8 [&_button[type=submit]]:bg-ln-cream [&_button[type=submit]]:text-ln-dark [&_input:not([type=checkbox])]:border-ln-cream/25 [&_input:not([type=checkbox])]:bg-ln-cream/[0.05] [&_input:not([type=checkbox])]:px-3">
            <ConsultForm variant="calculator" calculator={payload} />
          </div>
        </div>
      </section>
      <footer className="border-t border-ln-hair bg-ln-canvas px-5 py-10 sm:px-8">
        <div className="mx-auto max-w-2xl text-[11px] leading-[1.75] tracking-[0.04em] text-ln-muted">
          {footerWho && <p>{footerWho}</p>}
          {legal.length > 0 && <p>{legal.join(" · ")}</p>}
        </div>
      </footer>
    </main>
  );
}

function signed(n: number, usd: Intl.NumberFormat): string {
  const rounded = Math.round(n);
  return `${rounded < 0 ? "−" : "+"}${usd.format(Math.abs(rounded))}`;
}

/** A money field with a ground of its own and one-tap amounts under it. The
 *  underline version read as decoration next to the rest of the page; this is
 *  the only thing on the screen a visitor is meant to touch. */
function MoneyField({
  id,
  label,
  value,
  onChange,
  suffix,
  quick,
  format,
  group,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  suffix?: string;
  quick?: readonly number[];
  format?: (n: number) => string;
  group?: (n: number) => string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] uppercase tracking-[0.14em] text-ln-muted">
        {label}
      </label>
      <div className="mt-2 flex items-baseline gap-2 border border-ln-line bg-ln-canvas px-4 py-3 focus-within:border-ln-dark">
        <span className="text-[17px] text-ln-faint">$</span>
        <input
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => {
            if (!group) return;
            const n = Number(value.replace(/[^0-9.]/g, ""));
            if (Number.isFinite(n) && n > 0) onChange(group(n));
          }}
          className="w-full min-w-0 bg-transparent font-ln-serif text-[30px] leading-[1.15] text-ln-ink outline-none [font-variant-numeric:tabular-nums]"
        />
        {suffix && <span className="flex-none text-[13px] text-ln-faint">{suffix}</span>}
      </div>
      {quick && format && (
        <div className="mt-2 flex gap-2">
          {quick.map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onChange(group ? group(n) : String(n))}
              aria-label={`${label}: ${format(n)}`}
              className="min-h-[44px] flex-1 border border-ln-line-strong text-[12px] text-ln-body transition-colors hover:border-ln-dark hover:text-ln-dark"
            >
              {format(n)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** One line of the five-year cascade: label, a bar scaled against the biggest
 *  of the five, and the signed figure. Gains and costs read apart by colour and
 *  by the sign, never by colour alone. */
function Bar({
  label,
  amount,
  max,
  usd,
}: {
  label: string;
  amount: number;
  max: number;
  usd: Intl.NumberFormat;
}) {
  const width = max > 0 ? Math.max(2, Math.round((Math.abs(amount) / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-3 sm:gap-4">
      <span className="w-[136px] flex-none text-[13px] leading-[1.4] text-ln-body sm:w-[184px]">
        {label}
      </span>
      <span className="hidden h-3 flex-1 bg-ln-tint sm:block">
        <span
          className={`block h-3 ${amount >= 0 ? "bg-ln-bronze" : "bg-ln-line-strong"}`}
          style={{ width: `${width}%` }}
        />
      </span>
      <span className="ml-auto w-[92px] flex-none text-right text-[13px] text-ln-dark [font-variant-numeric:tabular-nums] sm:ml-0">
        {signed(amount, usd)}
      </span>
    </div>
  );
}

/** A figure with its label, for the row under the price. `lead` is the one the
 *  visitor compares against their rent. */
function Stat({ label, value, lead = false }: { label: string; value: string; lead?: boolean }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.14em] text-ln-muted">{label}</p>
      <p
        className={
          lead
            ? "mt-1 font-ln-serif text-[28px] leading-none text-ln-ink"
            : "mt-1 font-ln-serif text-[20px] leading-none text-ln-dark"
        }
      >
        {value}
      </p>
    </div>
  );
}

function Line({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className={strong ? "font-semibold text-ln-dark" : "text-ln-muted"}>{label}</dt>
      <dd className={strong ? "font-semibold text-ln-dark" : "text-ln-dark"}>{value}</dd>
    </div>
  );
}

function Slider({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label htmlFor={id} className="block text-[12px] text-ln-muted">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="text-ln-dark">{value.toFixed(2)}%</span>
      </span>
      <input
        id={id}
        type="range"
        min={SLIDER.min}
        max={SLIDER.max}
        step={SLIDER.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 h-11 w-full accent-ln-dark"
      />
    </label>
  );
}

function Source({
  id,
  source,
  t,
}: {
  id?: string;
  source: { label: string; url: string; asOf: string };
  t: (key: string) => string;
}) {
  return (
    <p id={id} className="mt-1 text-[11px] leading-[1.6] text-ln-muted">
      {t("calculator.assumptions.source")}: {source.label} ({t("calculator.assumptions.asOf")}{" "}
      {source.asOf})
      {source.url && (
        <>
          {" "}
          <a
            href={source.url}
            rel="noopener noreferrer"
            target="_blank"
            aria-label={source.label}
            className="inline-block px-2 py-1 underline"
          >
            ↗
          </a>
        </>
      )}
    </p>
  );
}

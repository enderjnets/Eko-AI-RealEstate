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

import { LandingTracker } from "@/components/landing/LandingTracker";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import {
  DEFAULTS,
  SOURCES,
  UPPER,
  compare,
  solvePrice,
  type Assumptions,
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

/** A number from a money field: digits and one dot, nothing else; never NaN. */
function dollars(raw: string): number {
  const n = Number(raw.replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** A percent from a rate field, bounded like the server's `CalculatorIn`.
 *  Empty is "not set", not zero: `Number("")` is 0, and a field cleared to be
 *  retyped must not price the loan at 0% in the meantime. A comma decimal is
 *  what an ES keyboard offers. */
function ratePercent(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed.replace(",", "."));
  return Number.isFinite(n) && n >= 0 && n <= 20 ? n : null;
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
  const pct = (n: number, digits = 2) => `${(n * 100).toFixed(digits)}%`;

  const [rentRaw, setRentRaw] = useState("");
  const [savingsRaw, setSavingsRaw] = useState("");
  const [credit, setCredit] = useState<Credit>("good");
  const [appreciationPct, setAppreciationPct] = useState(DEFAULTS.appreciation * 100);
  const [rentGrowthPct, setRentGrowthPct] = useState(DEFAULTS.rentGrowth * 100);
  const [rateRaw, setRateRaw] = useState((DEFAULTS.rate * 100).toFixed(2));
  const [hoaRaw, setHoaRaw] = useState("");

  const rent = useDebounced(dollars(rentRaw), DEBOUNCE_MS);
  const savings = useDebounced(dollars(savingsRaw), DEBOUNCE_MS);
  const ratePct = ratePercent(rateRaw);

  const assumptions: Assumptions = useMemo(
    () => ({
      ...DEFAULTS,
      appreciation: appreciationPct / 100,
      rentGrowth: rentGrowthPct / 100,
      rate: ratePct === null ? DEFAULTS.rate : ratePct / 100,
      hoaMonthly: dollars(hoaRaw),
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

  const priceLabel = result
    ? result.price >= UPPER
      ? t("calculator.result.ceiling")
      : usd.format(Math.round(result.price / 1000) * 1000)
    : null;

  const rows = comparison ? comparison.rows.filter((r) => [1, 3, 5].includes(r.year)) : [];

  return (
    <main className="min-h-screen bg-ln-canvas text-ln-body">
      <LandingTracker variant="calculator" sections={SECTIONS} />
      <div className="mx-auto max-w-2xl px-5 py-12 sm:px-8 sm:py-16">
        <div className="flex items-center justify-between gap-4">
          {brandLine ? (
            <a
              href="/"
              className="inline-block text-[11px] uppercase tracking-[0.18em] text-ln-muted hover:text-ln-gold"
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

        <h1 className="mt-5 font-ln-serif text-[32px] leading-[1.15] text-ln-dark sm:text-[44px]">
          {t("calculator.title")}
        </h1>
        <p className="mt-5 text-[16px] leading-[1.75]">{t("calculator.intro")}</p>

        {/* ── Inputs ─────────────────────────────────────────────────── */}
        <section id="inputs" className="mt-10 scroll-mt-10">
          <h2 className="font-ln-serif text-[22px] text-ln-dark">{t("calculator.inputs.heading")}</h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <MoneyField
              id="calc-rent"
              label={t("calculator.inputs.rent")}
              value={rentRaw}
              onChange={setRentRaw}
            />
            <MoneyField
              id="calc-savings"
              label={t("calculator.inputs.savings")}
              value={savingsRaw}
              onChange={setSavingsRaw}
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
        </section>

        {/* ── Result ─────────────────────────────────────────────────── */}
        <section id="result" className="mt-12 scroll-mt-10 border-t border-ln-hair pt-10">
          <h2 className="text-[11px] uppercase tracking-[0.18em] text-ln-gold">
            {t("calculator.result.heading")}
          </h2>
          {!result && <p className="mt-4 text-[16px] text-ln-muted">{t("calculator.result.empty")}</p>}
          {result && !shown && (
            <p className="mt-4 text-[16px] leading-[1.7]">{t("calculator.result.floor")}</p>
          )}
          {result && shown && (
            <>
              <p
                data-testid="calc-price"
                className="mt-3 font-ln-serif text-[44px] leading-none text-ln-dark sm:text-[60px]"
              >
                {priceLabel}
              </p>
              <p className="mt-3 text-[15px] leading-[1.7]">
                {result.cappedBy === "savings"
                  ? t("calculator.result.capped.savings", { n: Math.round(DEFAULTS.minDown * 100) })
                  : t("calculator.result.capped.rent")}
              </p>
              <dl className="mt-7 grid gap-x-8 gap-y-2 text-[14px] sm:grid-cols-2">
                <Line label={t("calculator.result.down")} value={usd.format(Math.round(result.down))} />
                <Line label={t("calculator.result.loan")} value={usd.format(Math.round(result.loan))} />
              </dl>
              <h3 className="mt-8 font-ln-serif text-[19px] text-ln-dark">
                {t("calculator.monthly.heading")}
              </h3>
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
            </>
          )}
          <p className="mt-6 text-[12px] leading-[1.7] text-ln-muted">{t("calculator.disclaimer")}</p>
        </section>

        {/* ── Compare ────────────────────────────────────────────────── */}
        <section id="compare" className="mt-12 scroll-mt-10 border-t border-ln-hair pt-10">
          <h2 className="font-ln-serif text-[22px] text-ln-dark">{t("calculator.compare.heading")}</h2>
          {!comparison && <p className="mt-4 text-[15px] text-ln-muted">{t("calculator.result.empty")}</p>}
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
              <dl className="mt-6 divide-y divide-ln-hair text-[14px]">
                <Line
                  label={t("calculator.compare.appreciation")}
                  value={signed(comparison.appreciation, usd)}
                />
                <Line
                  label={t("calculator.compare.amortization")}
                  value={signed(comparison.amortization, usd)}
                />
                <Line label={t("calculator.compare.cashflow")} value={signed(comparison.cashflowDiff, usd)} />
                <Line label={t("calculator.compare.closing")} value={signed(-comparison.closing, usd)} />
                <Line label={t("calculator.compare.selling")} value={signed(-comparison.selling, usd)} />
              </dl>
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

        {/* ── Consult (the form arrives in the next phase) ───────────── */}
      </div>
      <section id="consult" className="relative mt-12 scroll-mt-10 overflow-hidden bg-ln-dark">
        <div className="mx-auto max-w-2xl px-5 py-14 sm:px-8 sm:py-16">
          <h2 className="font-ln-serif text-[26px] leading-tight text-ln-cream sm:text-[32px]">
            {t("calculator.cta.heading")}
          </h2>
          <p className="mt-4 text-[15px] leading-[1.7] text-ln-canvas/80">{t("calculator.cta.body")}</p>
          <div id="consult-form" className="mt-8" />
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

function MoneyField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label htmlFor={id} className="block text-[11px] uppercase tracking-[0.14em] text-ln-muted">
      {label}
      <div className="mt-1 flex items-baseline border-b border-ln-line-strong focus-within:border-ln-dark">
        <span className="pr-1 text-[18px] text-ln-muted">$</span>
        <input
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-12 w-full bg-transparent font-ln-serif text-[26px] text-ln-dark outline-none"
        />
      </div>
    </label>
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

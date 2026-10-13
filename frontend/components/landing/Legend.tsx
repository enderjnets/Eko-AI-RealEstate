"use client";

import { ArrowLeft, ArrowUpRight, Calculator, House, Phone } from "lucide-react";
import Link from "next/link";

import { LandingTracker } from "@/components/landing/LandingTracker";
import { collectAttribution, withAttribution } from "@/lib/capture";
import { useI18n } from "@/lib/i18n";
import { LANDING, dialable, readableUsPhone } from "@/lib/landing";
import { LEGEND_MODEL_NOTE, type Legend as LegendData } from "@/lib/legends";

type SearchValue = string | string[] | undefined;
export type LegendSearchParams = Record<string, SearchValue>;

/** Same attribution as `/start`: the UTM the short path put on the URL travels
 *  into the calculator and the consult form, so a lead from a legend video is
 *  still credited to it. Only the variant differs. */
function attributedLinks(searchParams: LegendSearchParams, slug: string) {
  const attribution = collectAttribution({
    get(key) {
      const value = searchParams[key];
      return Array.isArray(value) ? (value[0] ?? null) : (value ?? null);
    },
  });
  if (!attribution.landing_variant) attribution.landing_variant = `legend-${slug}`;
  return {
    calculator: withAttribution("/calculator", attribution),
    consult: withAttribution("/#consult", attribution),
  };
}

export function Legend({ legend, searchParams = {} }: { legend: LegendData; searchParams?: LegendSearchParams }) {
  const { t } = useI18n();
  const links = attributedLinks(searchParams, legend.slug);
  const phone = dialable(LANDING.phone);
  const cell = "flex min-h-[132px] flex-col border-r border-t border-ln-line-strong p-5 transition-colors sm:p-6";

  return (
    <div className="eko-landing flex min-h-[100svh] flex-col bg-ln-canvas font-ln-sans text-ln-ink" lang="en">
      <LandingTracker variant={`legend-${legend.slug}`} sections={[]} />

      <header className="mx-auto w-full max-w-3xl px-5 pb-2 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] sm:px-8 sm:pt-7">
        {LANDING.brand && (
          <p className="font-ln-serif text-[22px] font-light leading-none tracking-[0.04em] sm:text-[26px]">{LANDING.brand}</p>
        )}
        {(LANDING.advisors || LANDING.brokerage) && (
          <p className="mt-1.5 text-[8px] font-medium uppercase tracking-[0.25em] text-ln-body sm:text-[9px]">
            {[LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ")}
          </p>
        )}
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-5 pb-12 pt-6 sm:px-8 sm:pt-10">
        <Link href="/legends" data-track="legend-all" className="mb-5 inline-flex min-h-[44px] items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-ln-body hover:text-ln-gold">
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.5} />
          {t("legend.all")}
        </Link>
        <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-ln-bronze">{legend.eyebrow}</p>
        <h1 className="mt-3 font-ln-serif text-[40px] font-light leading-[0.98] tracking-[-0.02em] sm:text-[56px]">{legend.title}</h1>
        <p className="mt-4 text-[17px] leading-7 text-ln-body sm:text-[19px]">{legend.dek}</p>

        {/* eslint-disable-next-line @next/next/no-img-element -- plain <img> across the site: no `sharp`, so next/image would optimise nothing. */}
        <img
          src={legend.hero.src}
          alt={legend.hero.alt}
          width={864}
          height={1080}
          decoding="async"
          className="mt-7 aspect-[4/5] w-full max-w-md border border-ln-line object-cover"
        />

        {legend.watch.length > 0 && (
          <div className="mt-5">
            <p className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-bronze">{t("legend.watch")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {legend.watch.map((w) => (
                <a
                  key={w.network}
                  href={w.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-track={`legend-watch-${w.network.toLowerCase()}`}
                  className="inline-flex items-center gap-1.5 border border-ln-line-strong px-3 py-2 text-[12px] uppercase tracking-[0.16em] hover:bg-ln-cream"
                >
                  {w.network}
                  <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.5} />
                </a>
              ))}
            </div>
          </div>
        )}

        <ol className="mt-10 space-y-8">
          {legend.facts.map((f, i) => (
            <li key={i} className="border-l-2 border-ln-gold pl-4">
              {f.legend && (
                <p className="text-[15px] leading-6 text-ln-body">
                  <span className="mr-2 text-[10px] font-medium uppercase tracking-[0.22em] text-ln-bronze">{t("legend.legendLabel")}</span>
                  <span className="italic">{f.legend}</span>
                </p>
              )}
              <p className={`${f.legend ? "mt-2" : ""} text-[17px] leading-7`}>
                {f.legend && (
                  <span className="mr-2 text-[10px] font-medium uppercase tracking-[0.22em] text-ln-bronze">{t("legend.recordLabel")}</span>
                )}
                {f.record}
              </p>
              <p className="mt-1.5 text-[12px] leading-5 text-ln-body">
                {f.sources.map((s, j) => (
                  <span key={s.url + j}>
                    {j > 0 && " · "}
                    <a href={s.url} target="_blank" rel="noopener noreferrer" className="underline decoration-ln-line-strong underline-offset-2">
                      {s.name}
                    </a>
                  </span>
                ))}
              </p>
            </li>
          ))}
        </ol>

        {legend.visit && (
          <a
            href={legend.visit.url}
            target="_blank"
            rel="noopener noreferrer"
            data-track={`legend-visit-${legend.slug}`}
            className="mt-8 inline-flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.22em] text-ln-bronze"
          >
            {legend.visit.label}
            <ArrowUpRight aria-hidden="true" className="h-4 w-4" strokeWidth={1.5} />
          </a>
        )}

        <section className="mt-12">
          <h2 className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-bronze">{t("legend.photos")}</h2>
          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            {legend.photos.map((p) => (
              <figure key={p.src}>
                {/* eslint-disable-next-line @next/next/no-img-element -- see the hero note. */}
                <img src={p.src} alt={p.alt} loading="lazy" decoding="async" className="w-full border border-ln-line" />
                <figcaption className="mt-2 text-[13px] leading-5 text-ln-body">
                  {p.caption}{" "}
                  <a href={p.page} target="_blank" rel="noopener noreferrer" className="text-[11px] underline underline-offset-2">
                    {p.credit} · {p.licence}
                  </a>
                </figcaption>
              </figure>
            ))}
          </div>
        </section>

        <section className="mt-14">
          <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-ln-bronze">{t("legend.next.eyebrow")}</p>
          <h2 className="mt-2 font-ln-serif text-[34px] font-light leading-none sm:text-[44px]">{t("legend.next.title")}</h2>
          <p className="mt-3 text-[15px] leading-6 text-ln-body">{t("legend.next.intro")}</p>
          <nav aria-label={t("start.actions.label")} className="mt-6 grid border-b border-l border-ln-line-strong sm:grid-cols-3">
            <Link href={links.calculator} data-track="legend-calculator" aria-label={t("start.buy.aria")} className={`${cell} bg-ln-paper hover:bg-ln-cream`}>
              <span className="flex items-start justify-between text-[10px] font-medium uppercase tracking-[0.24em] text-ln-bronze">
                {t("start.buy.number")}
                <Calculator aria-hidden="true" className="h-5 w-5 text-ln-gold" strokeWidth={1.5} />
              </span>
              <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05] text-ln-dark">{t("start.buy.title")}</span>
            </Link>
            <Link href={links.consult} data-track="legend-sell-value" aria-label={t("start.sell.aria")} className={`${cell} bg-ln-stone hover:bg-ln-tint`}>
              <span className="flex items-start justify-between text-[10px] font-medium uppercase tracking-[0.24em] text-ln-dark">
                {t("start.sell.number")}
                <House aria-hidden="true" className="h-5 w-5 text-ln-gold" strokeWidth={1.5} />
              </span>
              <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05] text-ln-dark">{t("start.sell.title")}</span>
            </Link>
            {phone ? (
              <a href={`tel:${phone}`} data-track="legend-call" aria-label={t("start.talk.callAria")} className={`${cell} bg-ln-dark text-ln-cream hover:bg-ln-night`}>
                <span className="flex items-start justify-between text-[10px] font-medium uppercase tracking-[0.24em] text-ln-canvas/65">
                  {t("start.talk.number")}
                  <Phone aria-hidden="true" className="h-5 w-5 text-ln-canvas/75" strokeWidth={1.5} />
                </span>
                <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05]">{t("start.talk.title")}</span>
                <span className="mt-2 text-[14px] tracking-[0.08em] text-ln-canvas/85">{readableUsPhone(LANDING.phone)}</span>
              </a>
            ) : (
              <Link href={links.consult} data-track="legend-contact" aria-label={t("start.talk.contactAria")} className={`${cell} bg-ln-dark text-ln-cream hover:bg-ln-night`}>
                <span className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-canvas/65">{t("start.talk.number")}</span>
                <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05]">{t("start.talk.title")}</span>
              </Link>
            )}
          </nav>
        </section>

        <p className="mt-10 text-[11px] leading-5 text-ln-body">{LEGEND_MODEL_NOTE}</p>
      </main>

      <footer className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-2 border-t border-ln-line px-5 py-6 text-[10px] uppercase tracking-[0.16em] text-ln-body sm:px-8">
        <Link href="/legends" data-track="legend-more" className="underline underline-offset-4 hover:text-ln-gold">{t("legend.more")}</Link>
        {(LANDING.brokerage || LANDING.address) && <span>{[LANDING.brokerage, LANDING.address].filter(Boolean).join(" · ")}</span>}
      </footer>
    </div>
  );
}

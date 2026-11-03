"use client";

import { ArrowRight, Phone } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { LandingTracker } from "@/components/landing/LandingTracker";
import { StartActions, attributedStartLinks, type StartActionsSearchParams } from "@/components/landing/StartActions";
import { useI18n } from "@/lib/i18n";
import { LANDING, dialable, readableUsPhone } from "@/lib/landing";
import {
  LEGEND_AREA,
  LEGEND_AREAS,
  LEGEND_FEATURED,
  LEGEND_MODEL_NOTE,
  LEGENDS,
  legendNumber,
  legendStats,
  seriesStats,
  type Legend,
  type LegendArea,
} from "@/lib/legends";

/** "Denver, decoded · Colfax Avenue" → "Colfax Avenue": the index already says
 *  "Denver, decoded" once, at the top. */
function place(eyebrow: string): string {
  const parts = eyebrow.split(" · ");
  return parts.length > 1 ? parts.slice(1).join(" · ") : eyebrow;
}

/** The archives named under the list. Each is cited by at least one legend in
 *  `lib/legends.ts` (counted on 2-nov-2026); text, not logos — no permission
 *  to show their marks. */
const ARCHIVES = [
  "Denver Public Library",
  "History Colorado",
  "Colorado Encyclopedia",
  "National Register of Historic Places",
  "National Park Service",
];

/** Where the "your house" card sits in the list: after this many legends. */
const YOURS_AFTER = 5;

type Filter = "all" | LegendArea;

/**
 * `/legends`, the index of the series (13-oct-2026; v2 on 2-nov-2026).
 *
 * v2, approved by the owner from the design canvas, after a look at series
 * pages that read as publications (The Pudding, 99% Invisible, Retro Report)
 * and at real-estate brands that publish (The Agency, Sotheby's): every legend
 * numbered and with the size of its record (sources, archive photographs),
 * the most watched one featured, a filter by place, a compact list on a phone
 * (the v1 page was ~15,900 px tall there), the sell offer as one quiet line on
 * top, a card in the list ("No. 21 · Your address") and the full Start-here
 * band after the list, where an editorial page puts its pitch.
 */
export function LegendsIndex({ searchParams = {} }: { searchParams?: StartActionsSearchParams }) {
  const { t } = useI18n();
  const links = attributedStartLinks(searchParams, "legends");
  const phone = dialable(LANDING.phone);
  const stats = seriesStats();
  const [filter, setFilter] = useState<Filter>("all");

  const featured = LEGENDS.find((l) => l.slug === LEGEND_FEATURED);
  const newestFirst = useMemo(() => [...LEGENDS].reverse(), []);
  const list = filter === "all"
    ? newestFirst.filter((l) => l.slug !== featured?.slug)
    : newestFirst.filter((l) => LEGEND_AREA[l.slug] === filter);
  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: LEGENDS.length, downtown: 0, mountains: 0, offlimits: 0, parks: 0 };
    for (const l of LEGENDS) c[LEGEND_AREA[l.slug]] += 1;
    return c;
  }, []);

  const meta = (legend: Legend) => {
    const s = legendStats(legend);
    return [
      t("legends.meta.sources", { n: s.sources }),
      t(s.photos === 1 ? "legends.meta.photo" : "legends.meta.photos", { n: s.photos }),
    ].join(" · ");
  };
  const number = (legend: Legend) => t("legends.number", { n: String(legendNumber(legend.slug)).padStart(2, "0") });
  const wrap = "mx-auto w-full max-w-[1200px] px-5 sm:px-10 xl:px-0";
  const eyebrow = "text-[10px] font-medium uppercase tracking-[0.22em] text-ln-bronze";

  const yours = (
    <li key="yours" className="border-t border-ln-line sm:border-t-0">
      <Link href={links.consult} data-track="legends-yours" className="-mx-3 my-1.5 grid grid-cols-[92px_minmax(0,1fr)] gap-3.5 rounded bg-ln-tint px-3 py-4 sm:mx-0 sm:my-0 sm:flex sm:flex-col sm:gap-2 sm:bg-transparent sm:p-0">
        <span className="flex h-[115px] w-[92px] flex-col items-center justify-center rounded-sm border border-dashed border-ln-bronze font-ln-serif lining-nums text-[30px] text-ln-bronze sm:aspect-[4/5] sm:h-auto sm:w-full sm:items-start sm:justify-end sm:gap-2 sm:bg-ln-tint sm:p-5">
          <span className="sm:text-[64px] sm:leading-none lg:text-[80px]">{LEGENDS.length + 1}</span>
          <span className="hidden text-[22px] leading-[1.1] text-ln-ink sm:block">{t("legends.yours.lead")}</span>
        </span>
        <span className="flex min-w-0 flex-col gap-1.5">
          <span className={eyebrow}>{t("legends.yours.eyebrow", { n: LEGENDS.length + 1 })}</span>
          <span className="font-ln-serif text-[20px] leading-[1.1] sm:text-[22px] lg:text-[23px]">
            <span className="sm:hidden">{t("legends.yours.lead")} </span>{t("legends.yours.title")}
          </span>
          <span className="hidden text-[14px] leading-6 text-ln-body lg:block">{t("legends.yours.body")}</span>
          <span className="text-[12px] font-semibold sm:border-t sm:border-ln-line sm:pt-2">{t("legends.yours.action")} →</span>
        </span>
      </Link>
    </li>
  );

  return (
    <div className="eko-landing flex min-h-[100svh] flex-col bg-ln-canvas font-ln-sans text-ln-ink" lang="en">
      <LandingTracker variant="legends" sections={[]} />

      <header className="border-b border-ln-hair pt-[env(safe-area-inset-top,0px)]">
        <div className={`${wrap} flex items-center justify-between gap-4 py-3.5 sm:py-6`}>
          <Link href="/" data-track="legends-home" className="flex flex-col gap-1">
            <span className="font-ln-serif text-[21px] leading-none tracking-[0.03em] sm:text-[26px]">{LANDING.brand || t("legends.home")}</span>
            {(LANDING.advisors || LANDING.brokerage) && (
              <span className="text-[8px] font-medium uppercase tracking-[0.24em] text-ln-body sm:text-[9px]">
                {[LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ")}
              </span>
            )}
          </Link>
          <nav aria-label={t("legends.nav.label")} className="flex items-center gap-6 text-[12px] uppercase tracking-[0.14em] lg:gap-8">
            <span aria-current="page" className="hidden border-b border-ln-ink pb-0.5 md:inline">{t("legends.eyebrow")}</span>
            <Link href="/#about" className="hidden text-ln-body hover:text-ln-ink lg:inline">{t("landing.menu.about")}</Link>
            <Link href="/#guides" className="hidden text-ln-body hover:text-ln-ink lg:inline">{t("landing.menu.guides")}</Link>
            {phone && (
              <a href={`tel:${phone}`} data-track="legends-header-call" aria-label={t("start.talk.callAria")} className="flex h-11 w-11 items-center justify-center rounded-full border border-ln-line-strong md:hidden">
                <Phone aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.5} />
              </a>
            )}
            {phone && (
              <a href={`tel:${phone}`} data-track="legends-header-call" className="hidden text-ln-body hover:text-ln-ink xl:inline">{readableUsPhone(LANDING.phone)}</a>
            )}
            <Link href={links.consult} data-track="legends-header-sell" className="hidden min-h-[44px] items-center rounded-sm bg-ln-ink px-4 text-ln-cream hover:bg-ln-dark md:inline-flex">
              {t("legends.nav.cta")}
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <section className={`${wrap} grid gap-8 border-b border-ln-hair pb-6 pt-6 sm:pb-8 sm:pt-10 lg:grid-cols-[1.15fr_1fr] lg:items-center lg:gap-16 lg:border-b-0 lg:pb-10 lg:pt-14`}>
          <div className="flex flex-col gap-3 sm:gap-4">
            <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-ln-bronze sm:text-[11px]">{t("legends.series")}</p>
            <h1 className="font-ln-serif text-[38px] font-light leading-[0.98] tracking-[-0.02em] [text-wrap:balance] sm:text-[58px] lg:text-[76px] lg:leading-[0.94]">{t("legends.title")}</h1>
            <p className="max-w-xl text-[15px] leading-6 text-ln-body sm:text-[17px] sm:leading-7 lg:text-[18px]">{t("legends.intro")}</p>
            <dl className="mt-1 flex gap-5 sm:gap-8 lg:mt-2 lg:border-t lg:border-ln-hair lg:pt-4">
              {([["legends", stats.legends], ["sources", stats.sources], ["photos", stats.photos]] as const).map(([key, value]) => (
                <div key={key} className="flex flex-col-reverse">
                  <dt className="text-[10px] uppercase tracking-[0.14em] text-ln-body">{t(`legends.stats.${key}`)}</dt>
                  <dd className="font-ln-serif text-[26px] font-medium leading-none lining-nums sm:text-[34px] lg:text-[40px]">{value}</dd>
                </div>
              ))}
            </dl>
            <Link href={links.consult} data-track="legends-quiet-sell" className="mt-2 flex min-h-[48px] items-center justify-between gap-3 rounded-sm bg-ln-dark px-4 text-[14px] text-ln-cream hover:bg-ln-night md:hidden">
              <span>{t("legends.quiet.lead")} <b className="font-semibold">{t("legends.quiet.action")}</b></span>
              <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={1.6} />
            </Link>
          </div>

          {featured && (
            <Link href={`/legends/${featured.slug}`} data-track={`legends-open-${featured.slug}`} className="group grid gap-3 sm:grid-cols-2 sm:gap-7 sm:rounded sm:border sm:border-ln-hair sm:bg-ln-paper sm:p-5 lg:flex lg:flex-col lg:border-0 lg:bg-transparent lg:p-0">
              <span className="relative block">
                {/* eslint-disable-next-line @next/next/no-img-element -- static legend art, same as the cards below. */}
                <img src={featured.hero.src} alt={featured.hero.alt} width={864} height={1080} decoding="async" className="aspect-[4/5] w-full rounded-sm object-cover lg:aspect-[5/4]" />
                <span className="absolute left-3 top-3 rounded-sm bg-ln-cream px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-ln-ink">{t("legends.featured")}</span>
              </span>
              <span className="flex flex-col justify-center gap-2.5">
                <span className={eyebrow}>{number(featured)} · {place(featured.eyebrow)}</span>
                <span className="font-ln-serif text-[28px] leading-[1.05] group-hover:text-ln-bronze sm:text-[36px] lg:text-[32px]">{featured.title}</span>
                <span className="text-[14px] leading-6 text-ln-body sm:text-[15px] lg:hidden">{featured.dek}</span>
                <span className="text-[12px] text-ln-body sm:border-t sm:border-ln-hair sm:pt-2.5">{meta(featured)}</span>
              </span>
            </Link>
          )}
        </section>

        <div className={`${wrap} flex items-center justify-between gap-4 py-3.5 lg:border-y lg:border-ln-hair lg:py-4`}>
          <div role="group" aria-label={t("legends.filter.label")} className="-mx-5 flex gap-2 overflow-x-auto px-5 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
            {(["all", ...LEGEND_AREAS] as Filter[]).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={filter === key}
                data-track={`legends-filter-${key}`}
                onClick={() => setFilter(key)}
                className={`inline-flex min-h-[38px] shrink-0 items-center gap-1.5 rounded-full px-4 text-[13px] transition-colors ${
                  filter === key ? "bg-ln-ink text-ln-cream" : "border border-ln-line-strong text-ln-ink hover:bg-ln-tint"
                }`}
              >
                {t(`legends.area.${key}`)} <span className="opacity-70">{counts[key]}</span>
              </button>
            ))}
          </div>
          <span className="hidden shrink-0 text-[12px] uppercase tracking-[0.12em] text-ln-body sm:inline">{t("legends.sort")}</span>
        </div>

        <ul className={`${wrap} grid pb-4 sm:grid-cols-3 sm:gap-x-6 sm:gap-y-10 sm:pt-6 lg:grid-cols-4 lg:gap-x-7`}>
          {list.flatMap((legend, i) => {
            const item = (
              <li key={legend.slug} className="border-t border-ln-line sm:border-t-0">
                <Link href={`/legends/${legend.slug}`} data-track={`legends-open-${legend.slug}`} className="group grid grid-cols-[92px_minmax(0,1fr)] items-start gap-3.5 py-3.5 sm:flex sm:flex-col sm:gap-2 sm:py-0">
                  <img
                    src={legend.hero.src}
                    alt={legend.hero.alt}
                    width={864}
                    height={1080}
                    loading="lazy"
                    decoding="async"
                    className="h-[115px] w-[92px] rounded-sm object-cover sm:aspect-[4/5] sm:h-auto sm:w-full"
                  />
                  <span className="flex min-w-0 flex-col gap-1.5">
                    <span className={eyebrow}>{number(legend)} · {place(legend.eyebrow)}</span>
                    <span className="font-ln-serif text-[20px] leading-[1.1] group-hover:text-ln-bronze sm:text-[22px] lg:text-[23px]">{legend.title}</span>
                    <span className="hidden text-[14px] leading-6 text-ln-body lg:block">{legend.dek}</span>
                    <span className="text-[11px] text-ln-body sm:border-t sm:border-ln-line sm:pt-2">{meta(legend)}</span>
                  </span>
                </Link>
              </li>
            );
            return i === YOURS_AFTER - 1 || (i === list.length - 1 && list.length < YOURS_AFTER) ? [item, yours] : [item];
          })}
        </ul>

        <section aria-labelledby="legends-start" className={`${wrap} mt-6 sm:mt-10`}>
          <div className="-mx-2 grid gap-4 rounded-md bg-ln-dark px-4 py-5 text-ln-cream sm:mx-0 sm:p-7 lg:grid-cols-[1fr_3.4fr] lg:items-stretch lg:gap-4 lg:p-9">
            <div className="flex flex-col gap-1.5 lg:pr-3.5">
              <p className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-stone">{t("legends.start.eyebrow")}</p>
              <h2 id="legends-start" className="font-ln-serif text-[30px] font-light leading-none sm:text-[38px] lg:text-[44px]">{t("legend.next.title")}</h2>
              <p className="text-[13px] leading-5 text-ln-stone">{t("legend.next.intro")}</p>
            </div>
            <StartActions links={links} track="legends" variant="band" />
          </div>
        </section>

        <section className={`${wrap} grid gap-2 pt-8 sm:gap-7 sm:pt-11 lg:grid-cols-[1fr_2.2fr] lg:gap-10`}>
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-ln-bronze">{t("legends.archives.title")}</p>
          <div className="flex flex-col gap-2.5">
            <p className="font-ln-serif text-[18px] italic leading-[1.35] text-ln-ink-soft sm:text-[21px] lg:text-[24px]">{ARCHIVES.join(" · ")}</p>
            <p className="text-[11px] leading-5 text-ln-body sm:text-[12px]">{LEGEND_MODEL_NOTE}</p>
          </div>
        </section>
      </main>

      <footer className="mt-8 border-t border-ln-hair">
        <div className={`${wrap} flex flex-wrap items-center justify-between gap-2 py-6 text-[10px] uppercase tracking-[0.14em] text-ln-body`}>
          <Link href="/" className="underline underline-offset-4 hover:text-ln-gold">{LANDING.brand || t("legends.home")}</Link>
          {(LANDING.brokerage || LANDING.address) && <span>{[LANDING.brokerage, LANDING.address].filter(Boolean).join(" · ")}</span>}
        </div>
      </footer>
    </div>
  );
}

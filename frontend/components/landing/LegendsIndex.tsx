"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";

import { LandingTracker } from "@/components/landing/LandingTracker";
import { useI18n } from "@/lib/i18n";
import { LANDING } from "@/lib/landing";
import { LEGEND_MODEL_NOTE, LEGENDS } from "@/lib/legends";

/** "Denver, decoded · Colfax Avenue" → "Colfax Avenue": the index already says
 *  "Denver, decoded" once, at the top. */
function place(eyebrow: string): string {
  const parts = eyebrow.split(" · ");
  return parts.length > 1 ? parts.slice(1).join(" · ") : eyebrow;
}

/**
 * `/legends`, the one page that lists every legend page (13-oct-2026).
 *
 * The owner looked at the home and found nothing leading to the pages the
 * videos had been sending people to; each was reachable only by typing the
 * address a video ends on. This page is that list, in `LEGENDS` order, and the
 * home links it from the nav, the phone menu, the guides section and the
 * footer. Same chrome as `Legend.tsx`, so arriving from one page to the other
 * reads as the same publication.
 */
export function LegendsIndex() {
  const { t } = useI18n();

  return (
    <div className="eko-landing flex min-h-[100svh] flex-col bg-ln-canvas font-ln-sans text-ln-ink" lang="en">
      <LandingTracker variant="legends" sections={[]} />

      <header className="mx-auto w-full max-w-5xl px-5 pb-2 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] sm:px-8 sm:pt-7">
        {LANDING.brand && (
          <p className="font-ln-serif text-[22px] font-light leading-none tracking-[0.04em] sm:text-[26px]">{LANDING.brand}</p>
        )}
        {(LANDING.advisors || LANDING.brokerage) && (
          <p className="mt-1.5 text-[8px] font-medium uppercase tracking-[0.25em] text-ln-body sm:text-[9px]">
            {[LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ")}
          </p>
        )}
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-5 pb-12 pt-6 sm:px-8 sm:pt-10">
        <Link href="/" data-track="legends-home" className="mb-5 inline-flex min-h-[44px] items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-ln-body hover:text-ln-gold">
          <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.5} />
          {t("legends.home")}
        </Link>
        <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-ln-bronze">{t("legends.eyebrow")}</p>
        <h1 className="mt-3 max-w-3xl font-ln-serif text-[40px] font-light leading-[0.98] tracking-[-0.02em] sm:text-[56px]">{t("legends.title")}</h1>
        <p className="mt-4 max-w-2xl text-[17px] leading-7 text-ln-body sm:text-[19px]">{t("legends.intro")}</p>

        <ul className="mt-10 grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
          {LEGENDS.map((legend) => (
            <li key={legend.slug} className="border-t border-ln-line-strong pt-5">
              <Link href={`/legends/${legend.slug}`} data-track={`legends-open-${legend.slug}`} className="group flex flex-col">
                <img
                  src={legend.hero.src}
                  alt={legend.hero.alt}
                  width={864}
                  height={1080}
                  loading="lazy"
                  decoding="async"
                  className="aspect-[4/5] w-full border border-ln-line object-cover"
                />
                <p className="mt-4 text-[10px] font-medium uppercase tracking-[0.3em] text-ln-bronze">{place(legend.eyebrow)}</p>
                <h2 className="mt-2 font-ln-serif text-[26px] font-light leading-[1.1] group-hover:text-ln-bronze">{legend.title}</h2>
                <p className="mt-2 text-[15px] leading-6 text-ln-body">{legend.dek}</p>
                <span className="mt-4 inline-flex min-h-[44px] items-center gap-2 self-start text-[11px] font-medium uppercase tracking-[0.18em] text-ln-bronze group-hover:text-ln-gold">
                  {t("legends.read")}
                  <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.5} />
                </span>
              </Link>
            </li>
          ))}
        </ul>

        <p className="mt-14 max-w-3xl text-[11px] leading-5 text-ln-body">{LEGEND_MODEL_NOTE}</p>
      </main>

      <footer className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-2 border-t border-ln-line px-5 py-6 text-[10px] uppercase tracking-[0.16em] text-ln-body sm:px-8">
        <Link href="/" className="underline underline-offset-4 hover:text-ln-gold">{LANDING.brand || t("legends.home")}</Link>
        {(LANDING.brokerage || LANDING.address) && <span>{[LANDING.brokerage, LANDING.address].filter(Boolean).join(" · ")}</span>}
      </footer>
    </div>
  );
}

"use client";

import { ArrowUpRight, Calculator, House, Phone } from "lucide-react";

import { LandingTracker } from "@/components/landing/LandingTracker";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { collectAttribution, withAttribution } from "@/lib/capture";
import { useI18n } from "@/lib/i18n";
import { LANDING, dialable } from "@/lib/landing";

type StartSearchValue = string | string[] | undefined;
export type StartSearchParams = Record<string, StartSearchValue>;

function attributedLinks(searchParams: StartSearchParams) {
  const attribution = collectAttribution({
    get(key) {
      const value = searchParams[key];
      return Array.isArray(value) ? (value[0] ?? null) : (value ?? null);
    },
  });
  if (!attribution.landing_variant) attribution.landing_variant = "start";
  return {
    calculator: withAttribution("/calculator", attribution),
    consult: withAttribution("/#consult", attribution),
  };
}

export function Start({ searchParams = {} }: { searchParams?: StartSearchParams }) {
  const { lang, t } = useI18n();
  const links = attributedLinks(searchParams);
  const phone = dialable(LANDING.phone);
  const contactHref = phone ? `tel:${phone}` : links.consult;

  return (
    <div
      className="eko-landing flex min-h-[100svh] flex-col bg-ln-canvas font-ln-sans text-ln-ink"
      lang={lang}
    >
      <LandingTracker variant="start" sections={[]} trackScroll={false} />

      <header className="mx-auto flex w-full max-w-7xl items-start justify-between gap-4 px-5 pb-2 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] sm:px-8 sm:pb-4 sm:pt-7 lg:px-12">
        <div className="min-w-0 pt-2">
          {LANDING.brand && (
            <p className="truncate font-ln-serif text-[22px] font-light leading-none tracking-[0.04em] sm:text-[26px]">
              {LANDING.brand}
            </p>
          )}
          {(LANDING.advisors || LANDING.brokerage) && (
            <p className="mt-1.5 truncate text-[8px] font-medium uppercase tracking-[0.25em] text-ln-muted sm:text-[9px]">
              {[LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
        <span className="[&_button]:text-ln-body [&_button:hover]:bg-ln-ink/5 [&_button:hover]:text-ln-ink">
          <LanguageSwitcher />
        </span>
      </header>

      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-5 pb-9 pt-6 sm:px-8 sm:pb-12 sm:pt-10 lg:px-12 lg:pb-16 lg:pt-14">
        <div className="max-w-3xl">
          <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-ln-bronze">
            {t("start.eyebrow")}
          </p>
          <h1 className="mt-3 max-w-2xl font-ln-serif text-[44px] font-light leading-[0.94] tracking-[-0.025em] text-ln-ink sm:mt-4 sm:text-[64px] lg:text-[76px]">
            {t("start.title")}
          </h1>
          <p className="mt-3 max-w-xl text-[15px] leading-6 text-ln-body sm:mt-5 sm:text-[18px] sm:leading-7">
            {t("start.intro")}
          </p>
        </div>

        <nav
          aria-label={t("start.actions.label")}
          className="mt-7 grid border-b border-l border-ln-line-strong sm:mt-10 lg:mt-14 lg:grid-cols-3"
        >
          <a
            href={links.calculator}
            data-track="start-calculator"
            aria-label={t("start.buy.aria")}
            className="group flex min-h-[160px] flex-col border-r border-t border-ln-line-strong bg-ln-paper p-5 transition-colors hover:bg-ln-cream focus-visible:z-10 sm:p-6 lg:min-h-[290px] lg:p-8"
          >
            <div className="flex items-start justify-between gap-4">
              <span className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-bronze">
                {t("start.buy.number")}
              </span>
              <Calculator aria-hidden="true" className="h-5 w-5 text-ln-gold" strokeWidth={1.5} />
            </div>
            <div className="mt-4 grid flex-1 grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-4 lg:mt-9 lg:flex lg:flex-col">
              <h2 className="max-w-xs font-ln-serif text-[27px] font-light leading-[1.02] text-ln-dark sm:text-[31px] lg:text-[34px]">
                {t("start.buy.title")}
              </h2>
              <div className="flex min-w-0 flex-col">
                <p className="max-w-sm text-[13px] leading-5 text-ln-body sm:text-[14px] sm:leading-6 lg:mt-4">
                  {t("start.buy.body")}
                </p>
                <span className="mt-3 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.22em] text-ln-bronze lg:mt-auto lg:pt-7">
                  {t("start.action")}
                  <ArrowUpRight aria-hidden="true" className="h-4 w-4" strokeWidth={1.5} />
                </span>
              </div>
            </div>
          </a>

          <a
            href={links.consult}
            data-track="start-sell-value"
            aria-label={t("start.sell.aria")}
            className="group flex min-h-[160px] flex-col border-r border-t border-ln-line-strong bg-ln-stone p-5 transition-colors hover:bg-ln-tint focus-visible:z-10 sm:p-6 lg:min-h-[290px] lg:p-8"
          >
            <div className="flex items-start justify-between gap-4">
              <span className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-bronze">
                {t("start.sell.number")}
              </span>
              <House aria-hidden="true" className="h-5 w-5 text-ln-gold" strokeWidth={1.5} />
            </div>
            <div className="mt-4 grid flex-1 grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-4 lg:mt-9 lg:flex lg:flex-col">
              <h2 className="max-w-xs font-ln-serif text-[27px] font-light leading-[1.02] text-ln-dark sm:text-[31px] lg:text-[34px]">
                {t("start.sell.title")}
              </h2>
              <div className="flex min-w-0 flex-col">
                <p className="max-w-sm text-[13px] leading-5 text-ln-body sm:text-[14px] sm:leading-6 lg:mt-4">
                  {t("start.sell.body")}
                </p>
                <span className="mt-3 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.22em] text-ln-bronze lg:mt-auto lg:pt-7">
                  {t("start.action")}
                  <ArrowUpRight aria-hidden="true" className="h-4 w-4" strokeWidth={1.5} />
                </span>
              </div>
            </div>
          </a>

          <a
            href={contactHref}
            data-track={phone ? "start-call" : "start-contact"}
            aria-label={phone ? t("start.talk.callAria") : t("start.talk.contactAria")}
            className="group flex min-h-[160px] flex-col border-r border-t border-ln-line-strong bg-ln-dark p-5 text-ln-cream transition-colors hover:bg-ln-night focus-visible:z-10 sm:p-6 lg:min-h-[290px] lg:p-8"
          >
            <div className="flex items-start justify-between gap-4">
              <span className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-canvas/65">
                {t("start.talk.number")}
              </span>
              <Phone aria-hidden="true" className="h-5 w-5 text-ln-canvas/75" strokeWidth={1.5} />
            </div>
            <div className="mt-4 grid flex-1 grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-4 lg:mt-9 lg:flex lg:flex-col">
              <h2 className="max-w-xs font-ln-serif text-[27px] font-light leading-[1.02] sm:text-[31px] lg:text-[34px]">
                {t("start.talk.title")}
              </h2>
              <div className="flex min-w-0 flex-col">
                <p className="max-w-sm text-[13px] leading-5 text-ln-canvas/70 sm:text-[14px] sm:leading-6 lg:mt-4">
                  {phone ? t("start.talk.phoneBody") : t("start.talk.fallbackBody")}
                </p>
                {phone && (
                  <p className="mt-1 text-[13px] tracking-[0.08em] text-ln-canvas/85 sm:text-[14px]">
                    {LANDING.phone}
                  </p>
                )}
                <span className="mt-3 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.22em] text-ln-canvas/80 lg:mt-auto lg:pt-7">
                  {phone ? t("start.callAction") : t("start.action")}
                  <ArrowUpRight aria-hidden="true" className="h-4 w-4" strokeWidth={1.5} />
                </span>
              </div>
            </div>
          </a>
        </nav>
      </main>

      <footer className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-2 border-t border-ln-line px-5 py-6 text-[10px] uppercase tracking-[0.16em] text-ln-muted sm:px-8 lg:px-12">
        <span>{t("start.footer")}</span>
        {(LANDING.brokerage || LANDING.address) && (
          <span>{[LANDING.brokerage, LANDING.address].filter(Boolean).join(" · ")}</span>
        )}
      </footer>
    </div>
  );
}

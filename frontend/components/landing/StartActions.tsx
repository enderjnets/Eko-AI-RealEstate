"use client";

import { Calculator, House, Phone } from "lucide-react";
import Link from "next/link";

import { collectAttribution, withAttribution } from "@/lib/capture";
import { useI18n } from "@/lib/i18n";
import { LANDING, dialable, readableUsPhone } from "@/lib/landing";

type SearchValue = string | string[] | undefined;
export type StartActionsSearchParams = Record<string, SearchValue>;

/** The UTM the short path put on the URL travels into the calculator and the
 *  consult form, so a lead from a legend video or the Instagram bio is still
 *  credited to it. `variant` only fills in when the URL carried none. */
export function attributedStartLinks(searchParams: StartActionsSearchParams, variant: string) {
  const attribution = collectAttribution({
    get(key) {
      const value = searchParams[key];
      return Array.isArray(value) ? (value[0] ?? null) : (value ?? null);
    },
  });
  if (!attribution.landing_variant) attribution.landing_variant = variant;
  return {
    calculator: withAttribution("/calculator", attribution),
    consult: withAttribution("/#consult", attribution),
  };
}

/**
 * The three ways out of a legend page — sell, buy, talk — shared by every
 * legend page and the `/legends` index (2-nov-2026).
 *
 * Sell comes first since that day. The Instagram audience the legends built is
 * 87% 35+ and 41% in five metro cities: people who mostly already own a home
 * here. `track` prefixes the `data-track` names so each page keeps the event
 * names it already had (`legend-sell-value`, `legend-calculator`…).
 */
export function StartActions({ links, track }: { links: { calculator: string; consult: string }; track: string }) {
  const { t } = useI18n();
  const phone = dialable(LANDING.phone);
  const cell = "flex min-h-[132px] flex-col border-r border-t border-ln-line-strong p-5 transition-colors sm:p-6";

  return (
    <nav aria-label={t("start.actions.label")} className="mt-6 grid border-b border-l border-ln-line-strong sm:grid-cols-3">
      <Link href={links.consult} data-track={`${track}-sell-value`} aria-label={t("start.sell.aria")} className={`${cell} bg-ln-stone hover:bg-ln-tint`}>
        <span className="flex items-start justify-between text-[10px] font-medium uppercase tracking-[0.24em] text-ln-dark">
          {t("start.sell.number")}
          <House aria-hidden="true" className="h-5 w-5 text-ln-gold" strokeWidth={1.5} />
        </span>
        <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05] text-ln-dark">{t("start.sell.title")}</span>
      </Link>
      <Link href={links.calculator} data-track={`${track}-calculator`} aria-label={t("start.buy.aria")} className={`${cell} bg-ln-paper hover:bg-ln-cream`}>
        <span className="flex items-start justify-between text-[10px] font-medium uppercase tracking-[0.24em] text-ln-bronze">
          {t("start.buy.number")}
          <Calculator aria-hidden="true" className="h-5 w-5 text-ln-gold" strokeWidth={1.5} />
        </span>
        <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05] text-ln-dark">{t("start.buy.title")}</span>
      </Link>
      {phone ? (
        <a href={`tel:${phone}`} data-track={`${track}-call`} aria-label={t("start.talk.callAria")} className={`${cell} bg-ln-dark text-ln-cream hover:bg-ln-night`}>
          <span className="flex items-start justify-between text-[10px] font-medium uppercase tracking-[0.24em] text-ln-canvas/65">
            {t("start.talk.number")}
            <Phone aria-hidden="true" className="h-5 w-5 text-ln-canvas/75" strokeWidth={1.5} />
          </span>
          <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05]">{t("start.talk.title")}</span>
          <span className="mt-2 text-[14px] tracking-[0.08em] text-ln-canvas/85">{readableUsPhone(LANDING.phone)}</span>
        </a>
      ) : (
        <Link href={links.consult} data-track={`${track}-contact`} aria-label={t("start.talk.contactAria")} className={`${cell} bg-ln-dark text-ln-cream hover:bg-ln-night`}>
          <span className="text-[10px] font-medium uppercase tracking-[0.24em] text-ln-canvas/65">{t("start.talk.number")}</span>
          <span className="mt-3 font-ln-serif text-[24px] font-light leading-[1.05]">{t("start.talk.title")}</span>
        </Link>
      )}
    </nav>
  );
}

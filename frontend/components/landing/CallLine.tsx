"use client";

/**
 * "Or just call us — (720) 824-9313", for the pages that have a form and no
 * phone.
 *
 * **Written from production, on 18-sep-2026.** Over fourteen days, 48 sessions
 * reached `calculator_result` — the highest-intent thing this site can record.
 * Of those 48: one started the form, **zero clicked a phone, and zero clicked a
 * CTA**. Forty-five of them landed straight on `/calculator`, so they never saw
 * the home page, which is the only page carrying both a phone and a form.
 * Those zero phone clicks are not indifference: there was no phone on the page
 * to click.
 *
 * **The number is rendered as TEXT, not only as a link, and that is the whole
 * design.** Thirty-six of those 48 sessions were on desktop, where `tel:` does
 * nothing a person can use — they have to read the digits and dial them on the
 * handset in their other hand. A button labelled "call us" is useless there.
 * The anchor stays for the twelve on a phone, where tapping is the point.
 *
 * `data-track` is what makes the click show up as `tel_click`: the delegated
 * listener reads the `href`, and `trackedAnchorEvent` classifies anything
 * starting `tel:` as a call. So the pages that adopt this line also start
 * answering the question that produced it.
 */

import { Phone } from "lucide-react";

import { LANDING, dialable } from "@/lib/landing";
import { useI18n } from "@/lib/i18n";

/**
 * `+17208249313` → `(720) 824-9313`.
 *
 * Shipped unformatted first, and it undercut the only reason the digits are on
 * the page: somebody on a desktop has to READ them and key them into a handset,
 * and an unbroken run of eleven characters is what makes a person mistype the
 * last four. Anything that is not a plain US number is printed exactly as
 * configured — a guess at grouping a number we do not recognise is worse than
 * showing what the operator typed.
 */
export function readableUsPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  const local = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  if (local.length !== 10) return raw;
  return `(${local.slice(0, 3)}) ${local.slice(3, 6)}-${local.slice(6)}`;
}

export function CallLine({
  where,
  tone = "dark",
}: {
  /** Goes into the event's `where`, so the funnel can tell the pages apart. */
  where: string;
  /** `dark` sits on the cream-on-night panels; `light` on the canvas pages. */
  tone?: "dark" | "light";
}) {
  const { t } = useI18n();
  if (!LANDING.phone) return null;

  const muted = tone === "dark" ? "text-ln-canvas/70" : "text-ln-muted";
  const strong = tone === "dark" ? "text-ln-cream" : "text-ln-body";

  return (
    <p className={`mt-6 text-[13px] leading-[1.7] ${muted}`}>
      {t("landing.call.or")}{" "}
      <a
        href={`tel:${dialable(LANDING.phone)}`}
        data-track={where}
        className={`inline-flex min-h-[44px] items-center gap-2 font-medium underline underline-offset-4 ${strong} hover:opacity-80`}
      >
        <Phone className="h-3.5 w-3.5" aria-hidden />
        {readableUsPhone(LANDING.phone)}
      </a>
    </p>
  );
}

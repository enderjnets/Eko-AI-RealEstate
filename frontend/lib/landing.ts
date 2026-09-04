/**
 * Content the public landing renders about a real business: who the advisors
 * are, which brokerage they hang their licence with, how to reach them.
 *
 * All of it comes from the environment because none of it can be invented. A
 * phone number, a years-in-business count or a client testimonial that we made
 * up is not a placeholder — on a page advertising a licensed real-estate
 * brokerage it is false advertising, which Colorado regulates and the FTC
 * enforces. So every field defaults to absent, and each section that depends on
 * one renders nothing rather than something plausible.
 *
 * These are NEXT_PUBLIC_* and therefore inlined at BUILD time, like the
 * Turnstile site key. Changing one needs a frontend rebuild, not a restart.
 * They must be referenced as full literals for Next to substitute them.
 */

export interface Testimonial {
  quote: string;
  attribution: string;
}

function clean(value: string | undefined): string {
  return (value || "").trim();
}

/**
 * Testimonials arrive as a JSON array so that shipping none — the default — is
 * the same code path as shipping three. Malformed JSON yields an empty list:
 * a broken env var must cost the section, not the page.
 */
export function parseTestimonials(raw: string): Testimonial[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item) => {
      if (typeof item !== "object" || item === null) return [];
      const quote = clean((item as Record<string, unknown>).quote as string);
      const attribution = clean((item as Record<string, unknown>).attribution as string);
      return quote && attribution ? [{ quote, attribution }] : [];
    });
  } catch {
    return [];
  }
}

const brand = clean(process.env.NEXT_PUBLIC_LANDING_BRAND);
const advisors = clean(process.env.NEXT_PUBLIC_LANDING_ADVISORS);
const brokerage = clean(process.env.NEXT_PUBLIC_LANDING_BROKERAGE);
const address = clean(process.env.NEXT_PUBLIC_LANDING_ADDRESS);
const phone = clean(process.env.NEXT_PUBLIC_LANDING_PHONE);
const sms = clean(process.env.NEXT_PUBLIC_LANDING_SMS);
const email = clean(process.env.NEXT_PUBLIC_LANDING_EMAIL);
const years = clean(process.env.NEXT_PUBLIC_LANDING_YEARS);
const markets = clean(process.env.NEXT_PUBLIC_LANDING_MARKETS);
const portrait = clean(process.env.NEXT_PUBLIC_LANDING_PORTRAIT);
const bookingUrl = clean(process.env.NEXT_PUBLIC_LANDING_BOOKING_URL);
const instagram = clean(process.env.NEXT_PUBLIC_LANDING_INSTAGRAM);
const youtube = clean(process.env.NEXT_PUBLIC_LANDING_YOUTUBE);
const tiktok = clean(process.env.NEXT_PUBLIC_LANDING_TIKTOK);
const testimonials = parseTestimonials(clean(process.env.NEXT_PUBLIC_LANDING_TESTIMONIALS));

export const LANDING = {
  brand,
  advisors,
  brokerage,
  address,
  phone,
  sms,
  email,
  years,
  markets,
  portrait,
  bookingUrl,
  instagram,
  youtube,
  tiktok,
  testimonials,

  /** The stat strip is all-or-nothing: one lonely number reads as an omission. */
  hasStats: Boolean(years && markets),
  hasAnyChannel: Boolean(phone || sms || email),
  /** The footer row disappears entirely rather than showing one lone icon
      of a channel nobody has: same rule as the stat strip. */
  socials: [
    { key: "instagram" as const, url: instagram },
    { key: "youtube" as const, url: youtube },
    { key: "tiktok" as const, url: tiktok },
  ].filter((s) => Boolean(s.url)),
} as const;

/**
 * How this site names itself in public — the browser tab, the card someone
 * sees when the link is pasted into a chat, the label on an iPhone home
 * screen. ONE derivation, imported by both public pages.
 *
 * It used to be two: `app/page.tsx` built it inline and
 * `app/contact/layout.tsx` built it again under a comment claiming they were
 * "the same source, so the two never drift apart". They were already two
 * sources; this is that comment made true.
 *
 * The brand leads because it is what the visitor was following when they got
 * here — they came from a video posted by the brand, not by a person, and a
 * page that never says the brand's name reads as the wrong address. The design
 * writes it "Brand · Advisors, Brokerage", so the separator after the brand is
 * a comma and without a brand it stays the middot this site shipped with.
 * Every part is optional: with nothing configured these are the same neutral
 * strings as before.
 */
const people = [advisors, brokerage].filter(Boolean).join(brand ? ", " : " \u00b7 ");

export const publicName = [brand, people].filter(Boolean).join(" \u00b7 ");

/** The <title> and og:title. With a brand it is the design's own title. */
export const publicTitle = brand
  ? publicName
  : publicName
    ? `${publicName} \u2014 Colorado real estate`
    : "Colorado real estate";

/** Short enough for a home-screen label, where a full title is truncated. */
export const homeScreenName = brand || publicName || "Colorado real estate";

/**
 * `tel:` and `sms:` refuse anything but digits and a leading `+`. A number
 * typed for humans ("(303) 359-5110") produces a link that silently does
 * nothing on a phone, which is the one device that matters here.
 */
export function dialable(value: string): string {
  // Stop at the first letter. "(303) 555-0192 ext. 12" would otherwise become
  // 30355501922 — a different, probably real, number that the phone dials
  // without complaint. Anything after a word is an instruction to a human,
  // not part of the number.
  const beforeWords = value.split(/[a-zA-Z]/)[0];
  const digits = beforeWords.replace(/[^\d+]/g, "");
  return digits.startsWith("+") ? "+" + digits.slice(1).replace(/\+/g, "") : digits;
}

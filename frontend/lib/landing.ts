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
const testimonials = parseTestimonials(clean(process.env.NEXT_PUBLIC_LANDING_TESTIMONIALS));

export const LANDING = {
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
  testimonials,

  /** The stat strip is all-or-nothing: one lonely number reads as an omission. */
  hasStats: Boolean(years && markets),
  hasAnyChannel: Boolean(phone || sms || email),
} as const;

/**
 * `tel:` and `sms:` refuse anything but digits and a leading `+`. A number
 * typed for humans ("(303) 359-5110") produces a link that silently does
 * nothing on a phone, which is the one device that matters here.
 */
export function dialable(value: string): string {
  const digits = value.replace(/[^\d+]/g, "");
  return digits.startsWith("+") ? "+" + digits.slice(1).replace(/\+/g, "") : digits;
}

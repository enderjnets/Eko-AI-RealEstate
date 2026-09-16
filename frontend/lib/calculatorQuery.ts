/**
 * What `/calculator` should already know when somebody arrives from a video.
 *
 * ── The measurement ──────────────────────────────────────────────────────
 * Eleven Shorts (pieces 47-57) send people to `/calculator`, and five of them
 * make a specific promise in the caption: *"At $2,600 a month, going from
 * $40,000 saved to $80,000 moves the ceiling from $343,000 to $378,000"*.
 *
 * Of the 28 sessions YouTube has sent the site, **23 were a single event with
 * 0% scroll in an ordinary browser** — someone arrived, saw one screen, and
 * left without moving.
 *
 * What they saw explains it. `rentRaw` and `savingsRaw` both start as empty
 * strings, and `result` is null until rent is above zero *and* savings has
 * actually been typed. So a video that names a number lands on a page that
 * names none: it asks two questions first. The visitor was promised an answer
 * and met a form.
 *
 * ── What this fixes, and what it deliberately does not ───────────────────
 * A tagged link can carry the video's own figures, and then the page opens on
 * the answer it promised — the existing `resultInView` effect even brings it
 * onto the screen. Nothing here invents a number: every value comes from the
 * URL that the caption wrote.
 *
 * In particular this never supplies a **savings** figure of its own. The page
 * treats an untouched savings field as "not yet" rather than "$0" on purpose,
 * because $0 produces a floor answer nobody asked for. A link that carries
 * only rent seeds only rent, and the page still waits — one question instead
 * of two, and no figure that was never promised.
 *
 * Read from `window.location.search` by a mount effect rather than through
 * `useSearchParams`, for the reason `LandingTracker` already documents: that
 * hook opts the route out of static rendering unless the whole page sits
 * behind a Suspense boundary, and this page is indexed.
 */

import { LIMITS, type Credit } from "@/lib/calculator";

/** The text fields and the credit selector, as the page holds them. */
export interface CalculatorSeed {
  /** Goes straight into `rentRaw`. Absent when the URL said nothing usable. */
  rent?: string;
  /** Goes straight into `savingsRaw`. Never invented — only ever from the URL. */
  savings?: string;
  credit?: Credit;
}

const CREDITS: ReadonlyArray<Credit> = ["excellent", "good", "fair"];

/**
 * One money parameter, using the page's own field rules: digits and one dot,
 * anything else stripped, zero and nonsense rejected, and clamped to what the
 * server would accept so the page never shows a figure the lead cannot carry.
 *
 * Returns the **normalised string**, not a number: it is written into a text
 * input, and what the visitor reads in the field has to be the same figure the
 * arithmetic used.
 */
function money(raw: string | null, max: number): string | undefined {
  if (raw === null) return undefined;
  const n = Number(raw.replace(/[^0-9.]/g, ""));
  if (!Number.isFinite(n) || n <= 0) return undefined;
  return String(Math.min(n, max));
}

/**
 * What to put in the fields, given a query string.
 *
 * An empty object means "change nothing" — the page keeps the blank fields it
 * has today, so a visit with no parameters behaves exactly as it did before.
 */
export function calculatorSeed(search: string): CalculatorSeed {
  const q = new URLSearchParams(search);
  const seed: CalculatorSeed = {};

  const rent = money(q.get("rent"), LIMITS.rent);
  if (rent !== undefined) seed.rent = rent;

  const savings = money(q.get("savings"), LIMITS.savings);
  if (savings !== undefined) seed.savings = savings;

  const credit = q.get("credit");
  if (credit !== null && (CREDITS as readonly string[]).includes(credit)) {
    seed.credit = credit as Credit;
  }

  return seed;
}

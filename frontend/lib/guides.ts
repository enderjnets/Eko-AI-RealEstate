/**
 * The guides and tools the brand publishes, as one list.
 *
 * Until v0.91.0 `/fall` and `/calculator` were reachable only by whoever had
 * the link from a reel's caption: the home page — the one address every
 * video sends people to — linked to neither. Measured on the live site on
 * 7-sep-2026, the complete list of hrefs on `/` was three anchors, three
 * social profiles, the phone and the staff sign-in.
 *
 * This list is the single source the home reads: the "Guides" section, the
 * footer and the tests all iterate it. Adding a piece is adding a row here
 * plus its three i18n strings (`landing.guides.<key>.title|body|cta`, both
 * languages) — `guides.test.ts` refuses a row that lacks any of them.
 *
 * `href` MUST be a public path (`lib/hosts.ts` PUBLIC_PATHS). On the brand
 * host the middleware 308s every other path to the panel's login screen, so
 * a guide listed here with a non-public route would send every visitor who
 * taps it to an internal sign-in — the exact failure `/fall` shipped with
 * before it was added to that list. The test checks it so nobody has to
 * remember.
 *
 * Ordered by topic, not by format: the visitor is asking "how do I buy" or
 * "where do I go this weekend", not "do you have a tool or a guide". That is
 * the NN/g finding behind the whole section (format-based navigation), and
 * it is why `topic` is a field and the format is a small label.
 */

export type GuideKind = "guide" | "tool";
export type GuideTopic = "buying" | "selling" | "colorado";

export interface GuideEntry {
  /** i18n suffix: `landing.guides.<key>.title|body|cta`. */
  key: string;
  /** Same-origin public path — see the module note. */
  href: string;
  kind: GuideKind;
  topic: GuideTopic;
  /**
   * Set when the destination exists in ONE language only, so the link can
   * say so (`hrefLang`) and the Spanish copy can warn. `/fall` is English by
   * design — a Denver-local guide for a Denver-local audience — and the
   * Spanish visitor who taps "Leer la guía" deserves to know before, not
   * after. Omitted when the page follows the visitor's language.
   */
  lang?: "en";
}

export const GUIDES: readonly GuideEntry[] = [
  { key: "calculator", href: "/calculator", kind: "tool", topic: "buying" },
  { key: "fall", href: "/fall", kind: "guide", topic: "colorado", lang: "en" },
];

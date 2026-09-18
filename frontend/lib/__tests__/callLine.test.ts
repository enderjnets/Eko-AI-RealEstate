import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The phone on the two pages that had a form and no phone.
 *
 * Written from fourteen days of production, on 18-sep-2026. Of the 48 sessions
 * that reached `calculator_result` — the highest-intent event this site
 * records — one started the form, zero clicked a CTA and **zero clicked a
 * phone**. Forty-five of the 48 landed directly on `/calculator`, so they never
 * passed the home page, which was the only page carrying both doors. The zero
 * was not indifference; there was nothing on the page to click.
 */

const read = (...parts: string[]) =>
  readFileSync(join(__dirname, "..", "..", ...parts), "utf8");

const component = read("components", "landing", "CallLine.tsx");
const calculator = read("app", "calculator", "page.tsx");
const fall = read("app", "fall", "page.tsx");
const i18n = read("lib", "i18n.tsx");

describe("the call line", () => {
  it("is on both pages that had a form and no phone", () => {
    for (const [name, source] of [
      ["calculator", calculator],
      ["fall", fall],
    ] as const) {
      expect(source, `${name} does not import it`).toMatch(
        /import \{ CallLine \} from "@\/components\/landing\/CallLine"/,
      );
      expect(source, `${name} imports it and never renders it`).toMatch(
        /<CallLine\s/,
      );
    }
  });

  it("prints the number as text and not only as a link", () => {
    // The load-bearing half. Thirty-six of those 48 sessions were on desktop,
    // where tapping a `tel:` link does nothing a person can use — they read
    // the digits and dial them on the handset in their hand. A button that
    // says "call us" and hides the number is useless to three quarters of the
    // people this line exists for.
    //
    // Mutation this catches: replacing `{LANDING.phone}` with a translated
    // label. The anchor still works on a phone and the page looks finished,
    // and the majority of visitors are left with nothing to dial.
    expect(component).toMatch(/>\s*\{LANDING\.phone\}/);
  });

  it("still links, because the twelve on a phone are the ones who tap", () => {
    expect(component).toMatch(/href=\{`tel:\$\{dialable\(LANDING\.phone\)\}`\}/);
  });

  it("is tracked, so the zero that produced it can be answered", () => {
    // `trackedAnchorEvent` classifies any `tel:` href as `tel_click`, but only
    // when the anchor carries a `data-track`. Without it the click is invisible
    // and the next person reads the same zero and draws the same wrong
    // conclusion.
    expect(component).toMatch(/data-track=\{where\}/);
    expect(calculator).toMatch(/<CallLine where="calculator"/);
    expect(fall).toMatch(/<CallLine where="fall"/);
  });

  it("renders nothing at all when no number is configured", () => {
    // An install without a phone must not show "Or just call us:" followed by
    // a blank, which is worse than no line.
    expect(component).toMatch(/if \(!LANDING\.phone\) return null;/);
  });

  it("says its label in both languages", () => {
    // `i18nParity` already asserts the two dictionaries have the same keys.
    // This asserts the key this component actually calls exists at all — the
    // pair of checks that catches a renamed key, which parity alone cannot.
    expect(component).toMatch(/t\("landing\.call\.or"\)/);
    expect(i18n.match(/"landing\.call\.or":/g)).toHaveLength(2);
  });
});

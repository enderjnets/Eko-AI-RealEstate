import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { VALUE_HREF, consultIntent, withAttribution } from "../capture";

const read = (...p: string[]) => readFileSync(join(__dirname, "..", "..", ...p), "utf8");
const params = (q: string) => new URLSearchParams(q);

describe("a sell button opens the form as a valuation (5-nov-2026)", () => {
  // Measured over 30 days: the one visitor who pressed "What is your home worth
  // today?" landed under "Your search, our shortlist" with no chip picked and no
  // address field, and left the site ten seconds later.
  it("reads only the exact intent", () => {
    expect(consultIntent(params("intent=value"))).toBe("value");
    expect(consultIntent(params("intent=VALUE"))).toBeNull();
    expect(consultIntent(params("intent=buy"))).toBeNull();
    expect(consultIntent(params(""))).toBeNull();
  });

  it("keeps the intent and the anchor when attribution is added", () => {
    expect(withAttribution(VALUE_HREF, { utm_source: "instagram", landing_variant: "legends" })).toBe(
      "/?intent=value&utm_source=instagram&landing_variant=legends#consult",
    );
  });

  it("every sell button uses the valuation link, and talk keeps the plain one", () => {
    const actions = read("components", "landing", "StartActions.tsx");
    expect(actions.match(/href=\{links\.value\} data-track=\{`\$\{track\}-sell-value`\}/g)).toHaveLength(2);
    expect(actions.match(/href=\{links\.consult\} data-track=\{`\$\{track\}-contact`\}/g)).toHaveLength(2);
    const index = read("components", "landing", "LegendsIndex.tsx");
    for (const name of ["legends-yours", "legends-header-sell", "legends-quiet-sell"]) {
      expect(index).toContain(`href={links.value} data-track="${name}"`);
    }
    expect(read("components", "landing", "Start.tsx")).toMatch(/href=\{links\.value\}\s+data-track="start-sell-value"/);
  });

  it("the form starts on Valuing and the section asks the seller's question", () => {
    expect(read("components", "landing", "ConsultForm.tsx")).toMatch(/consultIntent\(params\) === "value"[\s\S]{0,120}setGoal/);
    const i18n = read("lib", "i18n.tsx");
    for (const key of ["landing.consult.valueTitleA", "landing.consult.valueTitleItalic", "landing.consult.valueBody"]) {
      expect(i18n.match(new RegExp(`"${key.replace(/\./g, "\\.")}"`, "g"))).toHaveLength(2);
    }
  });
});

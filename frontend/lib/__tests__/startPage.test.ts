import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  join(__dirname, "..", "..", "components", "landing", "Start.tsx"),
  "utf8",
);

describe("the social entry hub", () => {
  it("offers exactly three tracked choices with a phone fallback", () => {
    // Buy and sell always render; the source contains both mutually exclusive
    // talk branches (telephone and internal contact), so four declarations
    // still produce exactly three cards at runtime.
    expect(source.match(/data-track=/g)).toHaveLength(4);
    expect(source).toMatch(
      /\{phone \? \([\s\S]*start-call[\s\S]*\) : \([\s\S]*start-contact/,
    );
    for (const identifier of [
      "start-calculator",
      "start-sell-value",
      "start-call",
      "start-contact",
    ]) {
      expect(source.match(new RegExp(`\"${identifier}\"`, "g"))).toHaveLength(1);
    }
    expect(source).toContain("LANDING.phone");
  });

  it("preserves attribution and uses the shared public-page controls", () => {
    expect(source).toContain("withAttribution");
    expect(source).toContain('import Link from "next/link"');
    expect(source.match(/<Link\b/g)).toHaveLength(3);
    expect(source).toMatch(/<a\s+href=\{`tel:\$\{phone\}`\}/);
    expect(source).toContain("<LanguageSwitcher />");
    expect(source).toContain(
      '<LandingTracker variant="start" sections={[]} trackScroll={false} />',
    );
  });
});

describe("sell comes first (2-nov-2026)", () => {
  // The Instagram audience the legends built is 87% 35+ and 41% in five metro
  // cities: mostly people who already own a home. The owner chose to lead with
  // selling, on /start, on every legend page and on the /legends index.
  const read = (...p: string[]) => readFileSync(join(__dirname, "..", "..", ...p), "utf8");

  it("on /start the sell card comes before the buy card", () => {
    expect(source.indexOf('"start-sell-value"')).toBeLessThan(source.indexOf('"start-calculator"'));
  });

  it("the shared block puts sell before buy, and both legend pages use it", () => {
    const actions = read("components", "landing", "StartActions.tsx");
    expect(actions.indexOf("-sell-value`}")).toBeLessThan(actions.indexOf("-calculator`}"));
    expect(read("components", "landing", "Legend.tsx")).toContain('<StartActions links={links} track="legend" />');
    const index = read("components", "landing", "LegendsIndex.tsx");
    expect(index).toContain('<StartActions links={links} track="legends" variant="band" />');
    // v2 (2-nov-2026, approved from the design canvas): the full block goes
    // after the list, where an editorial page puts its pitch; the top keeps a
    // quiet sell line and the list a "your house" card.
    expect(index.indexOf("<StartActions")).toBeGreaterThan(index.indexOf("list.flatMap("));
    expect(index.indexOf('data-track="legends-quiet-sell"')).toBeLessThan(index.indexOf("list.flatMap("));
    expect(index).toContain('data-track="legends-yours"');
    expect(read("components", "landing", "StartActions.tsx").match(/-sell-value`\}/g)).toHaveLength(2);
  });

  it("the numbers on the cards follow the new order", () => {
    const i18n = read("lib", "i18n.tsx");
    expect(i18n).toContain('"start.sell.number": "01 · Sell"');
    expect(i18n).toContain('"start.buy.number": "02 · Buy"');
    expect(i18n).toContain('"start.sell.number": "01 · Vender"');
    expect(i18n).toContain('"start.buy.number": "02 · Comprar"');
  });
});

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

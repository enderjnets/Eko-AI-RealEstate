import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  join(__dirname, "..", "..", "components", "landing", "Start.tsx"),
  "utf8",
);

describe("the social entry hub", () => {
  it("offers exactly three tracked choices with a phone fallback", () => {
    expect(source.match(/data-track=/g)).toHaveLength(3);
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
    expect(source).toContain("<LanguageSwitcher />");
    expect(source).toContain(
      '<LandingTracker variant="start" sections={[]} trackScroll={false} />',
    );
  });
});

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * "The two of us" carries the profile Natalia approved on 30-sep, in both
 * languages, in place of the two paragraphs we had written for them.
 * Source-reading, like landingHero: there is no DOM in this suite.
 */

const root = join(__dirname, "..", "..");
const landing = readFileSync(join(root, "components", "landing", "Landing.tsx"), "utf8");
const i18n = readFileSync(join(root, "lib", "i18n.tsx"), "utf8");

const KEYS = ["landing.two.team", "landing.two.natalia", "landing.two.robbie"];

describe("the two of us is their own profile", () => {
  it("renders the team line and both bios", () => {
    for (const key of KEYS) expect(landing).toContain(`t("${key}")`);
    expect(landing).not.toMatch(/landing\.two\.p[12]/);
  });

  it("has every bio in English and Spanish", () => {
    for (const key of KEYS) expect(i18n.split(`"${key}":`).length - 1).toBe(2);
  });

  it("says what Natalia approved, and not what we wrote before", () => {
    expect(i18n).toContain("with their head office in Aspen");
    expect(i18n).toContain("She has been licensed since 2007.");
    expect(i18n).toContain("photography, cooking for friends");
    expect(i18n).toContain("3 years as a counselor at Veterans Affairs");
    expect(i18n).not.toContain("we are in the car most weeks");
  });
});

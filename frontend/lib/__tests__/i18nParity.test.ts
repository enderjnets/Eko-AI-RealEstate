import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Two failures this catches, both of which ship silently:
 *
 * - A key used in a component but present in neither dictionary. `t()` returns
 *   the key itself, so the UI renders "call.outcome.no_answer" as a button
 *   label and nothing errors.
 * - A key added to English and forgotten in Spanish. The page then reads half
 *   in each language for every Spanish-speaking user, which on a bilingual
 *   product aimed at Denver is the audience that matters most.
 */

const REPO = join(__dirname, "..", "..");
const source = readFileSync(join(REPO, "lib", "i18n.tsx"), "utf8");

function dictKeys(name: "EN" | "ES"): Set<string> {
  const start = source.indexOf(`const ${name}: Record<string, string> = {`);
  expect(start, `${name} dictionary not found`).toBeGreaterThan(-1);
  const end = source.indexOf("\n};", start);
  const body = source.slice(start, end);
  return new Set([...body.matchAll(/^\s{2}"([^"]+)":/gm)].map((m) => m[1]));
}

const EN = dictKeys("EN");
const ES = dictKeys("ES");

describe("i18n dictionaries", () => {
  it("read a plausible number of keys — otherwise this test proves nothing", () => {
    expect(EN.size).toBeGreaterThan(100);
    expect(ES.size).toBeGreaterThan(100);
  });

  it("has the same keys in English and Spanish", () => {
    const missingEs = [...EN].filter((k) => !ES.has(k)).sort();
    const missingEn = [...ES].filter((k) => !EN.has(k)).sort();
    expect({ missingFromSpanish: missingEs, missingFromEnglish: missingEn }).toEqual({
      missingFromSpanish: [],
      missingFromEnglish: [],
    });
  });

  it("never renders an untranslated value by leaving one empty", () => {
    const empties = [...source.matchAll(/^\s{2}"([^"]+)":\s*"",?$/gm)].map((m) => m[1]);
    expect(empties).toEqual([]);
  });

  it("defines every literal key the app asks for", () => {
    // The negative lookbehind matters: without it `createElement("script")`
    // and `split("-")` match as t() calls, and the test reports keys nobody
    // ever used while missing the ones that matter.
    const pattern = /(?<![A-Za-z0-9_.$])t\(\s*"([^"]+)"\s*\)/g;
    const used = new Set<string>();
    for (const file of sourceFiles()) {
      for (const m of readFileSync(file, "utf8").matchAll(pattern)) used.add(m[1]);
    }
    expect(used.size).toBeGreaterThan(100);
    expect([...used].filter((k) => !EN.has(k)).sort()).toEqual([]);
  });
});

function sourceFiles(): string[] {
  const { readdirSync, statSync } = require("node:fs") as typeof import("node:fs");
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (full.endsWith(".tsx")) out.push(full);
    }
  };
  walk(join(REPO, "app"));
  walk(join(REPO, "components"));
  return out;
}

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { GUIDES } from "../guides";
import { isPublicPath } from "../hosts";

/**
 * Three ways the guides section can ship broken, none of which errors:
 *
 * - a piece whose route is not in PUBLIC_PATHS: on the brand host every tap
 *   308s to the panel's login screen, which is how `/fall` first shipped;
 * - a piece with its strings in English only: `t()` returns the raw key, so
 *   the Spanish page prints "landing.guides.fall.cta" as a button label;
 * - the section rendered but not linked: the nav, the phone menu and the
 *   footer are three separate lists in Landing.tsx, and a change that drops
 *   one of them still compiles and still passes every other test.
 *
 * No jsdom here, by the repo's standing decision (vitest.config.ts), so the
 * page is checked as source, the way `track.test.ts` and `i18nParity` do.
 */

const REPO = join(__dirname, "..", "..");
const read = (p: string) => readFileSync(join(REPO, p), "utf8");
const landing = read("components/landing/Landing.tsx");
const i18n = read("lib/i18n.tsx");

function dictKeys(name: "EN" | "ES"): Set<string> {
  const start = i18n.indexOf(`const ${name}: Record<string, string> = {`);
  expect(start, `${name} dictionary not found`).toBeGreaterThan(-1);
  const end = i18n.indexOf("\n};", start);
  const body = i18n.slice(start, end);
  return new Set([...body.matchAll(/^\s{2}"([^"]+)":/gm)].map((m) => m[1]));
}

describe("GUIDES, the list the home reads", () => {
  it("names the two pages the videos already promise", () => {
    const hrefs = GUIDES.map((g) => g.href);
    expect(hrefs).toContain("/fall");
    expect(hrefs).toContain("/calculator");
  });

  it("only lists public paths — anything else lands on the panel's login", () => {
    for (const { href } of GUIDES) {
      expect(href.startsWith("/") && !href.startsWith("//"), href).toBe(true);
      expect(isPublicPath(href), `${href} is not in PUBLIC_PATHS`).toBe(true);
    }
  });

  it("has unique keys and only the kinds and topics the strings exist for", () => {
    const keys = GUIDES.map((g) => g.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const { kind, topic } of GUIDES) {
      expect(["guide", "tool"]).toContain(kind);
      expect(["buying", "selling", "colorado"]).toContain(topic);
    }
  });

  it("has a title, a body and a call to action for every piece, in both languages", () => {
    const EN = dictKeys("EN");
    const ES = dictKeys("ES");
    const missing: string[] = [];
    for (const { key, kind, topic } of GUIDES) {
      for (const k of [
        `landing.guides.${key}.title`,
        `landing.guides.${key}.body`,
        `landing.guides.${key}.cta`,
        `landing.guides.kind.${kind}`,
        `landing.guides.topic.${topic}`,
      ]) {
        if (!EN.has(k)) missing.push(`EN ${k}`);
        if (!ES.has(k)) missing.push(`ES ${k}`);
      }
    }
    expect(missing).toEqual([]);
  });
});

describe("the home links the guides from every place a visitor looks", () => {
  it("has the section, mounted between the markets and the form", () => {
    expect(landing).toContain('<section id="guides"');
    // lastIndexOf: a docblock higher up mentions "<main>" in prose.
    const main = landing.slice(landing.lastIndexOf("<main>"), landing.lastIndexOf("</main>"));
    expect(main).toMatch(/<Markets \/>\s*<Guides \/>\s*<Consult \/>/);
  });

  it("points at it from the desktop nav AND the phone menu", () => {
    // Two, not "at least one": the desktop links are hidden below `md`, so a
    // phone visitor with only the nav link could not reach the section at all
    // — which is what shipped for Markets and About in v0.69.0.
    // The nav writes it as a JSX attribute, the menu as an object field; the
    // two spellings are counted separately so a dropped one is named.
    const navLinks = landing.match(/href="#guides"/g) ?? [];
    const menuLinks = landing.match(/href:\s*"#guides"/g) ?? [];
    expect({ nav: navLinks.length, menu: menuLinks.length }).toEqual({ nav: 1, menu: 1 });
    expect(landing).toMatch(/\{\s*href:\s*"#guides",\s*label:\s*t\("landing\.menu\.guides"\)/);
    expect(landing).toMatch(/<a\b[^>]*href="#guides"[^>]*>\s*\{t\("landing\.nav\.guides"\)\}/);
  });

  it("renders the same list in the section and in the footer", () => {
    const iterations = landing.match(/GUIDES\.map\(/g) ?? [];
    expect(iterations.length).toBe(2);
    const footer = landing.slice(landing.indexOf("<footer"), landing.indexOf("</footer>"));
    expect(footer).toContain("GUIDES.map(");
  });

  it("links to the entry's own href, in the card and in the footer", () => {
    // Iterating GUIDES proves nothing about where the links go: a card that
    // wrote href={`/guide/${key}`} would iterate the list and still send
    // every tap on the brand host to the panel's login. One link per card
    // (the 44px call to action) plus one per entry in the footer.
    // Counted inside the section and inside the footer, not across the file:
    // the phone menu binds `href={href}` too, for its own list.
    const section = landing.slice(landing.indexOf("function Guides()"), landing.indexOf("function Consult()"));
    const footer = landing.slice(landing.indexOf("<footer"), landing.indexOf("</footer>"));
    expect(section.match(/href=\{href\}/g)?.length).toBe(1);
    expect(footer.match(/href=\{href\}/g)?.length).toBe(1);
    expect(section.match(/hrefLang=\{lang\}/g)?.length).toBe(1);
    expect(footer.match(/hrefLang=\{lang\}/g)?.length).toBe(1);
  });

  it("has a label for the panel's 'how far they read' card, in both languages", () => {
    // `guides` is stored for every visitor; without this key the panel would
    // either skip the row or print the raw name.
    expect(dictKeys("EN").has("section.guides")).toBe(true);
    expect(dictKeys("ES").has("section.guides")).toBe(true);
  });

  it("is a section the tracker reports and the server keeps", () => {
    const tracker = read("components/landing/LandingTracker.tsx");
    const def = tracker.match(/const SECTIONS[^=]*=\s*\[([^\]]*)\]/);
    expect(def?.[1]).toContain('"guides"');
    const landingPy = readFileSync(join(REPO, "..", "backend", "app", "models", "landing.py"), "utf8");
    const tuple = landingPy.match(/LANDING_SECTIONS = \(([^)]*)\)/);
    expect(tuple?.[1]).toContain('"guides"');
  });
});

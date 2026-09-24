import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The v6 hero is a film the scroll engine drives, and two things would undo
 * that silently — no red test, no console error, just a page behaving like
 * the design's opposite:
 *
 *  - a `loop` or `autoPlay` attribute on the <video>. The engine owns the
 *    playhead and deliberately never loops (the clip cannot; see
 *    LandingEffects.tsx). Either attribute is honoured by the browser before
 *    the engine gets a say.
 *  - a later caption rendering visible. Three of the four captions share one
 *    absolutely-positioned box; before hydration and with JS off, only their
 *    initial classes keep them from stacking, and only `invisible` keeps the
 *    consult buttons out of the Tab order while they cannot be seen.
 *
 * Source-reading, like landingConfigWiring: there is no DOM in this suite.
 * Comments are stripped first so a mention in prose cannot fool the match.
 */

const here = join(__dirname, "..", "..", "components", "landing");
const stripComments = (s: string) =>
  s
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

const landing = stripComments(readFileSync(join(here, "Landing.tsx"), "utf8"));
const effects = stripComments(readFileSync(join(here, "LandingEffects.tsx"), "utf8"));

describe("the hero video is the engine's to drive", () => {
  const video = landing.match(/<video[\s\S]*?>/g) ?? [];

  it("has exactly one hero video", () => {
    expect(video).toHaveLength(1);
    expect(video[0]).toContain('data-hero-video="1"');
  });

  it("carries neither autoPlay nor loop", () => {
    expect(video[0]).not.toMatch(/\bautoPlay\b/);
    expect(video[0]).not.toMatch(/\bloop\b/);
  });

  it("is never looped by the engine either", () => {
    expect(effects).not.toMatch(/\.loop\s*=\s*true/);
  });
});

/**
 * The film is 16:9, and a phone held upright shows a quarter of its width,
 * blown up — Demetra's "adjust aspect for iPhone" (23-sep). Portrait screens
 * get their own 9:16 flight instead. `<source media>` picks the file; `poster`
 * has no media attribute, so the portrait still is swapped in on mount, from
 * the same query, or a phone would wait for the film on a cropped landscape
 * still.
 */
describe("a portrait screen gets a portrait film", () => {
  const PUBLIC = join(__dirname, "..", "..", "public", "landing");
  const sources = [...landing.matchAll(/<source\s[^>]*>/g)].map((m) => m[0]);
  const query = landing.match(/const PORTRAIT = "([^"]+)";/)?.[1];

  it("offers the vertical file first, only to portrait screens", () => {
    expect(query).toBe("(max-aspect-ratio: 4/5)");
    expect(sources).toHaveLength(2);
    expect(sources[0]).toContain('src="/landing/casa-hero-vertical.mp4"');
    expect(sources[0]).toMatch(/media=\{PORTRAIT\}/);
    expect(sources[1]).toContain('src="/landing/casa-hero.mp4"');
    expect(sources[1]).not.toMatch(/\bmedia=/);
  });

  it("swaps in the portrait poster from the same query", () => {
    expect(landing).toMatch(/matchMedia\(PORTRAIT\)\.matches/);
    expect(landing).toContain('"/landing/hero-poster-vertical.jpg"');
  });

  it("ships both portrait files, the still at 9:16", () => {
    const mp4 = readFileSync(join(PUBLIC, "casa-hero-vertical.mp4"));
    expect(mp4.subarray(4, 8).toString("ascii")).toBe("ftyp");
    const jpg = readFileSync(join(PUBLIC, "hero-poster-vertical.jpg"));
    // The first baseline or progressive frame header holds height, then width.
    let i = 2;
    while (i < jpg.length && !(jpg[i] === 0xff && (jpg[i + 1] === 0xc0 || jpg[i + 1] === 0xc2))) {
      i += 2 + jpg.readUInt16BE(i + 2);
    }
    expect([jpg.readUInt16BE(i + 7), jpg.readUInt16BE(i + 5)]).toEqual([720, 1280]);
  });
});

describe("only the opening caption is visible before the engine runs", () => {
  // The class of each data-cap element, with the `${aside}` template resolved.
  const asideClass = landing.match(/const aside =\s*"([^"]+)"/)?.[1] ?? "";
  const caps = [
    ...landing.matchAll(/data-cap="([^"]+)"[\s\S]*?className=(?:"([^"]+)"|\{`([^`]+)`\})/g),
  ].map((m) => ({
    window: m[1],
    className: (m[2] ?? m[3] ?? "").replace("${aside}", asideClass),
  }));

  it("finds the design's five caption windows", () => {
    expect(caps.map((c) => c.window)).toEqual(["0,0.22", "0.27,0.49", "0.53,0.75", "0.79,1", "0,0.14"]);
  });

  it("starts every later caption hidden, unclickable and out of the Tab order", () => {
    for (const c of caps) {
      // Windows that open at p=0 are the ones on screen at the top of the page.
      const opener = c.window.startsWith("0,");
      for (const cls of ["opacity-0", "invisible", "pointer-events-none"]) {
        expect(
          c.className.split(/\s+/).includes(cls),
          `${c.window} ${opener ? "must not" : "must"} carry ${cls}`,
        ).toBe(!opener);
      }
    }
  });
});

/**
 * deploy-v6's engine is the specification, and three of its mechanisms were
 * quietly replaced by v4 constants or by inventions of mine when the file was
 * converted to React. Each is cheap to undo by accident and none of them shows
 * up as an error — only as a page that behaves a little worse than the design.
 */
describe("the engine is deploy-v6's, not a paraphrase of it", () => {
  it("skips the reveal blur on a coarse pointer", () => {
    const blurs = [...effects.matchAll(/el\.style\.filter = "blur\(/g)];
    expect(blurs.length).toBeGreaterThan(0);
    const guarded = [...effects.matchAll(/if \(!coarse\) el\.style\.filter = "blur\(/g)];
    expect(guarded).toHaveLength(blurs.length);
    expect(effects).toMatch(/matchMedia\("\(pointer: coarse\)"\)/);
  });

  it("drives the playhead at the design's two speeds, with its 400ms hold", () => {
    expect(effects).toMatch(/d > 1\.6 \? 2 : d < 0\.9 \? 1 : v\.playbackRate/);
    expect(effects).toMatch(/now - v\.__rt > 400/);
    // One assignment only: a rate recomputed per frame is what this replaced.
    expect([...effects.matchAll(/v\.playbackRate = /g)]).toHaveLength(1);
  });

  it("carries the fallback for a stage whose sticky did not stick", () => {
    // Measured, not assumed: with body{overflow-x:hidden} injected at runtime
    // the stage without this sits at -878/-1755/-2808px instead of 0.
    expect(effects).toMatch(/host\.__js = Math\.abs\(sr\.top\) > 3/);
    expect(effects).toMatch(/stage\.style\.position = "absolute"/);
  });
});

/**
 * The phone had no navigation at all in v0.69.0 — the four links are md:inline
 * — so the overlay is the only way into the page from a phone. It has to sit
 * outside the hero: `[data-pin-stage]` is overflow-hidden and the engine's
 * sticky fallback puts `will-change: transform` on it, and either makes the
 * stage a containing block for position:fixed, which would crop the overlay
 * to the film. Nesting it back inside would look right in a desktop browser
 * and be broken exactly where it is the only navigation there is.
 */
describe("the phone's navigation exists, and lives outside the film", () => {
  const root = landing.slice(landing.indexOf("export function Landing()"));

  it("renders the menu as a sibling of <main>, never inside the hero", () => {
    const main = root.indexOf("</main>");
    const menu = root.indexOf("<MobileMenu");
    expect(main).toBeGreaterThan(-1);
    expect(menu).toBeGreaterThan(main);
  });

  it("covers the screen and offers the design's four destinations", () => {
    expect(landing).toMatch(/role="dialog"[\s\S]{0,400}?className="fixed inset-0/);
    for (const href of ["#about", "#how", "#markets", "#consult"]) {
      expect(landing).toContain(`{ href: "${href}"`);
    }
  });

  it("is opened by a control that says what it does", () => {
    expect(landing).toMatch(/aria-controls="landing-menu"/);
    expect(landing).toMatch(/aria-expanded=\{menuOpen\}/);
    expect(landing).toMatch(/aria-modal="true"/);
  });
});

/**
 * The brand has to be ON the page, not only in the URL. This is the defect
 * v0.70.0 shipped: the header and the mobile menu each rendered the advisors
 * where the design puts the brand, so a visitor coming from the brand's video
 * saw a page that never said its name.
 */
describe("the brand is on the page", () => {
  it("has one wordmark, used by both the header and the menu", () => {
    expect(landing).toMatch(/function Wordmark\(/);
    expect([...landing.matchAll(/<Wordmark\b/g)]).toHaveLength(2);
  });

  it("leads that wordmark with the brand and not with the advisors", () => {
    const body = landing.slice(landing.indexOf("function Wordmark("));
    expect(body).toMatch(/const lead = LANDING\.brand \|\| LANDING\.advisors;/);
  });

  it("names the brand in the footer line too", () => {
    expect(landing).toMatch(/\[LANDING\.brand, LANDING\.advisors, t\("landing\.footer\.role"\)/);
  });

  it("offers a hero sentence that names it, with a fallback that does not", () => {
    // One string with a {brand} hole would read " is Natalia & Robbie" on an
    // install that never configured a brand.
    expect(landing).toMatch(/landing\.hero\.bodyBranded/);
    expect(landing).toMatch(/landing\.hero\.body"\)/);
  });
});

describe("the footer's staff link does not prefetch across origins", () => {
  it("is a plain anchor on the derived href, not a next/link", () => {
    expect(landing).toMatch(/<a\s+href=\{STAFF_LOGIN_HREF\}/);
    expect(landing).not.toMatch(/from "next\/link"/);
  });
});

/**
 * "One file" is case-file jargon, and a first-time visitor read it as nothing
 * (external review, 24-sep-2026). The idea is the same two people on both ends
 * of a move, which the words now say.
 */
describe("the page says 'one team', not case-file jargon", () => {
  const i18n = readFileSync(join(__dirname, "..", "i18n.tsx"), "utf8");
  const value = (key: string, lang: "EN" | "ES") => {
    const start = i18n.indexOf(`const ${lang}: Record<string, string> = {`);
    const body = i18n.slice(start, i18n.indexOf("\n};", start));
    return body.match(new RegExp(`"${key.replace(/\./g, "\\.")}":\\s*"([^"]+)"`))?.[1];
  };

  it("in English", () => {
    expect(value("landing.hero.who.titleItalic", "EN")).toBe("One team");
    expect(value("landing.how.oneFile.title", "EN")).toBe("Two markets, one team");
  });

  it("in Spanish", () => {
    expect(value("landing.hero.who.titleItalic", "ES")).toBe("Un solo equipo");
    expect(value("landing.how.oneFile.title", "ES")).toBe("Dos mercados, un equipo");
  });
});

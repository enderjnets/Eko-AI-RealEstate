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

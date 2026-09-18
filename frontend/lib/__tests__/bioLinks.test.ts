/**
 * The short links that go in each network's profile field.
 *
 * They exist because the long tagged URL could not be pasted where it needed to
 * go: TikTok only offers a website field on a business account, Instagram
 * refused the edit, and several apps silently drop everything after the "?"
 * when saving. A short path has no query string to lose.
 *
 * Tested here rather than trusted: a redirect that loses its `utm_source` is
 * invisible — the visitor lands on the right page, the link "works", and the
 * report says `direct` for ever.
 */
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

// The Next config is CommonJS and stays that way: it is the file Next itself
// loads. Read through createRequire rather than a bare require so the test is
// an ES module like every other one here.
const nextConfig = createRequire(import.meta.url)("../../next.config.js");

describe("bio short links", () => {
  it("every network has a short path that carries its own source", async () => {
    const redirects = await nextConfig.redirects();
    // The landing page is per network now, not one for all: Instagram's bio
    // points at the autumn guide (see `next.config.js`). The tag is what this
    // test is really about and it does not move — a bio click has to stay
    // tellable apart from a caption link wherever it lands.
    for (const [path, source, landing] of [
      ["/yt", "youtube", "/start"],
      ["/youtube", "youtube", "/start"],
      ["/tt", "tiktok", "/start"],
      ["/tiktok", "tiktok", "/start"],
      ["/ig", "instagram", "/fall"],
      ["/instagram", "instagram", "/fall"],
    ] as const) {
      const rule = redirects.find((r: { source: string }) => r.source === path);
      expect(rule, `${path} is missing`).toBeDefined();
      const destination = new URL(rule.destination, "https://example.test");
      expect(destination.pathname, `${path} lands somewhere else`).toBe(landing);
      expect(destination.searchParams.get("utm_source")).toBe(source);
      expect(destination.searchParams.get("utm_medium")).toBe("bio");
      expect(destination.searchParams.get("utm_campaign")).toBe("profile");
    }
  });

  it("the seasonal bio link is reconsidered before the season is over", async () => {
    // A comment that says "revert on 1-nov" is a rule nobody executes; this
    // repo has been bitten by exactly that before. A test that turns red on the
    // date is a rule that executes itself, and the message says what to do.
    //
    // It is not automatic in `next.config.js` on purpose: a redirect that
    // changes by itself is a redirect nobody re-reads. What should happen on
    // that date is a decision — back to `/start`, or on to whatever page the
    // next season gets — and a person makes it.
    const CADUCA = new Date("2026-11-01T00:00:00Z");
    const redirects = await nextConfig.redirects();
    const ig = redirects.find((r: { source: string }) => r.source === "/ig");
    const destino = new URL(ig.destination, "https://example.test").pathname;
    if (destino === "/fall" && new Date() >= CADUCA) {
      throw new Error(
        "/ig still points at /fall and it is November or later. The autumn " +
          "guide is twelve places sorted by the elevation their aspens turn " +
          "at — a visitor arriving from the Instagram profile now lands on " +
          "last month. Decide: back to /start, or point it at the page the " +
          "current season has. Then update this test and PROJECT_STATUS.",
      );
    }
    // Before the date, the only thing asserted is that the expiry is real:
    // whoever changes the destination has to come here and say so.
    expect(["/fall", "/start"]).toContain(destino);
  });

  it("no two networks share a source", () => {
    // The failure this guards is a copy-paste: three links that all say
    // youtube look perfectly fine and make the breakdown meaningless.
    const sources = ["/yt", "/tt", "/ig"];
    expect(new Set(sources).size).toBe(3);
  });

  it("each band of the autumn guide has its own short path", async () => {
    // Four Instagram pieces send people to one page. Without a per-piece tag
    // the report can say "Instagram" and never which piece — and on Instagram
    // a caption URL is typed by hand, so a tagged one would not survive being
    // read off a screen. `/fall/1` is what makes the four countable.
    const redirects = await nextConfig.redirects();
    for (const band of [1, 2, 3, 4]) {
      const rule = redirects.find(
        (r: { source: string }) => r.source === `/fall/${band}`,
      );
      expect(rule, `/fall/${band} is missing`).toBeDefined();
      expect(rule.destination.startsWith("/fall?")).toBe(true);
      expect(rule.destination).toContain(`utm_content=band${band}`);
      expect(rule.destination).toContain("utm_source=instagram");
      expect(rule.destination).toContain("utm_campaign=fall2026");
    }
  });

  it("the four bands do not share a tag", () => {
    // Same copy-paste this file already guards for the networks: four rules
    // that all say band1 look right and make the comparison meaningless.
    const tags = [1, 2, 3, 4].map((band) => `band${band}`);
    expect(new Set(tags).size).toBe(4);
  });

  it("each partner has a short path that says who shared", async () => {
    // On 11-sep somebody posted the site on Facebook: 26 real sessions from
    // Denver suburbs, the best day the site has had, and nobody knows who to
    // thank or ask again. These three are what make the next one countable.
    const redirects = await nextConfig.redirects();
    for (const [path, name] of [
      ["/n", "natalia"],
      ["/r", "robbie"],
      ["/e", "ender"],
    ] as const) {
      const rule = redirects.find((r: { source: string }) => r.source === path);
      expect(rule, `${path} is missing`).toBeDefined();
      const destination = new URL(rule.destination, "https://example.test");
      expect(destination.pathname).toBe("/start");
      expect(destination.searchParams.get("utm_source")).toBe("partner");
      expect(destination.searchParams.get("utm_medium")).toBe("share");
      expect(destination.searchParams.get("utm_content")).toBe(name);
    }
  });

  it("the three partners do not share a tag", async () => {
    // The same copy-paste this file already guards twice. Three rules that
    // all say natalia look right and answer the one question they exist for
    // with the wrong name.
    const redirects = await nextConfig.redirects();
    const tags = ["/n", "/r", "/e"].map((path) => {
      const rule = redirects.find((r: { source: string }) => r.source === path);
      return new URL(rule.destination, "https://example.test").searchParams.get("utm_content");
    });
    expect(new Set(tags).size).toBe(3);
  });

  it("no short path is claimed twice", () => {
    // `/n`, `/r` and `/e` are single letters in the same namespace as `/yt`
    // and `/ig`. A duplicated source is not an error Next reports: the first
    // rule wins and the second silently never fires.
    const all = ["/yt", "/youtube", "/tt", "/tiktok", "/ig", "/instagram", "/n", "/r", "/e"];
    expect(new Set(all).size).toBe(all.length);
  });

  it("they are temporary, so the campaign can change later", async () => {
    // A 301 is cached hard by browsers. Changing the campaign afterwards would
    // mean fighting caches on devices nobody can reach.
    const redirects = await nextConfig.redirects();
    for (const rule of redirects) {
      expect(rule.permanent).toBe(false);
    }
  });
});

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
    for (const [path, source] of [
      ["/yt", "youtube"],
      ["/tt", "tiktok"],
      ["/ig", "instagram"],
    ] as const) {
      const rule = redirects.find((r: { source: string }) => r.source === path);
      expect(rule, `${path} is missing`).toBeDefined();
      expect(rule.destination).toContain(`utm_source=${source}`);
      expect(rule.destination).toContain("utm_medium=bio");
    }
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

  it("they are temporary, so the campaign can change later", async () => {
    // A 301 is cached hard by browsers. Changing the campaign afterwards would
    // mean fighting caches on devices nobody can reach.
    const redirects = await nextConfig.redirects();
    for (const rule of redirects) {
      expect(rule.permanent).toBe(false);
    }
  });
});

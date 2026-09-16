import { describe, expect, it } from "vitest";

import { PUBLIC_PATHS } from "../hosts";
import { sitemapUrls } from "../sitemap";

const BRAND = "https://www.denverhomestory.com";

describe("the sitemap", () => {
  it("lists every public page as an absolute URL on the brand domain", () => {
    const urls = sitemapUrls(BRAND, PUBLIC_PATHS).map((e) => e.url);
    expect(urls).toContain(`${BRAND}/`);
    expect(urls).toContain(`${BRAND}/calculator`);
    expect(urls).toContain(`${BRAND}/start`);
    expect(urls).toContain(`${BRAND}/contact`);
    expect(urls).toContain(`${BRAND}/fall`);
    expect(urls).toHaveLength(PUBLIC_PATHS.length);
  });

  it("never doubles the slash on the home page", () => {
    // `${origin}${"/"}` is the obvious implementation and it emits
    // "https://host//", which is a different URL to a crawler.
    expect(sitemapUrls(BRAND, ["/"])[0].url).toBe(`${BRAND}/`);
  });

  it("yields nothing at all when the brand domain is not configured", () => {
    // The rule `lib/hosts.ts` sets for every value in it: unset means do
    // nothing, never guess. A sitemap built on a guessed origin either points
    // at a dead domain or invites Google to index the operator panel.
    expect(sitemapUrls("", PUBLIC_PATHS)).toEqual([]);
    expect(sitemapUrls("   ", PUBLIC_PATHS)).toEqual([]);
  });

  it("tolerates a brand URL saved with a trailing slash", () => {
    expect(sitemapUrls(`${BRAND}/`, ["/calculator"])[0].url).toBe(`${BRAND}/calculator`);
  });

  it("never publishes a brief link, whatever else changes", () => {
    // The one that would actually cost something. A brief URL carries the
    // token that IS the credential for a partner's private answers; listing
    // one hands it to every crawler. This passes today because the entries are
    // derived from PUBLIC_PATHS rather than retyped, and it is here to fail
    // loudly on the day somebody adds a hand-kept list.
    const urls = sitemapUrls(BRAND, PUBLIC_PATHS).map((e) => e.url);
    for (const url of urls) {
      expect(url).not.toContain("/brief");
    }
    expect(PUBLIC_PATHS).not.toContain("/brief");
  });

  it("does not list the operator panel's pages", () => {
    const urls = sitemapUrls(BRAND, PUBLIC_PATHS).map((e) => e.url).join(" ");
    for (const panel of ["/leads", "/inbox", "/settings", "/login", "/analytics", "/console"]) {
      expect(urls).not.toContain(panel);
    }
  });

  it("puts the page the videos point at above the seasonal one", () => {
    // Eleven Shorts send people to /calculator and Google has never seen it.
    // /fall stops being true in December.
    const by = Object.fromEntries(
      sitemapUrls(BRAND, PUBLIC_PATHS).map((e) => [e.url, e.priority]),
    );
    expect(by[`${BRAND}/calculator`]).toBeGreaterThan(by[`${BRAND}/fall`]);
    expect(by[`${BRAND}/`]).toBe(1);
  });

  it("gives an unranked public page neutral values rather than dropping it", () => {
    // A page added to PUBLIC_PATHS must appear even if nobody updated the
    // weights. Being listed is the point; the weights are a hint Google is
    // free to ignore.
    const entry = sitemapUrls(BRAND, ["/guides"])[0];
    expect(entry.url).toBe(`${BRAND}/guides`);
    expect(entry.priority).toBe(0.5);
    expect(entry.changeFrequency).toBe("monthly");
  });
});

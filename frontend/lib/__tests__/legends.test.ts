import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { LEGEND_MODEL_NOTE, LEGENDS, legendBySlug } from "../legends";

// Same reading of the config as `bioLinks.test.ts`: the file Next loads.
const nextConfig = createRequire(import.meta.url)("../../next.config.js");
const PUBLIC = resolve(__dirname, "../../public");

// The short paths the videos say. A video that ends with an address and has no
// page would send the viewer to the menu the owner already called wrong.
const SPOKEN = ["colfax", "cheesman", "mollybrown"] as const;

function everyString(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(everyString);
  if (value && typeof value === "object") return Object.values(value).flatMap(everyString);
  return [];
}

describe("legend pages", () => {
  it("every spoken short path has a page", () => {
    for (const slug of SPOKEN) expect(legendBySlug(slug), slug).toBeDefined();
    expect(new Set(LEGENDS.map((l) => l.slug)).size).toBe(LEGENDS.length);
  });

  it("every line of the record names where it comes from", () => {
    for (const legend of LEGENDS) {
      expect(legend.facts.length, legend.slug).toBeGreaterThanOrEqual(4);
      for (const fact of legend.facts) {
        expect(fact.sources.length, fact.record).toBeGreaterThan(0);
        for (const s of fact.sources) {
          expect(s.name.trim(), fact.record).not.toBe("");
          expect(s.url, s.name).toMatch(/^https:\/\//);
        }
      }
    }
  });

  it("photographs are public domain or CC BY, credited, and on disk", () => {
    const allowed = new Set(["Public domain", "CC0", "CC BY 2.0", "CC BY 4.0"]);
    for (const legend of LEGENDS) {
      expect(existsSync(resolve(PUBLIC, `.${legend.hero.src}`)), legend.hero.src).toBe(true);
      expect(legend.hero.alt.trim()).not.toBe("");
      for (const p of legend.photos) {
        expect(allowed.has(p.licence), `${p.src}: ${p.licence}`).toBe(true);
        expect(p.credit.trim(), p.src).not.toBe("");
        expect(p.alt.trim(), p.src).not.toBe("");
        expect(p.page, p.src).toMatch(/^https:\/\//);
        expect(existsSync(resolve(PUBLIC, `.${p.src}`)), p.src).toBe(true);
      }
    }
  });

  it("says nothing about a neighbourhood and calls nothing haunted (Fair Housing)", () => {
    // A street, a park and a museum. "Cheesman Park" is also the name of a
    // neighbourhood, which is exactly why the copy may describe the park and
    // never the area, its homes or the people who live there.
    const banned = /\b(haunted|ghosts?|spooky|unsafe|safe|crime|dangerous|neighbou?rhoods?|capitol hill|residents?)\b/i;
    for (const legend of LEGENDS) {
      for (const text of everyString(legend)) expect(text, legend.slug).not.toMatch(banned);
    }
    expect(LEGEND_MODEL_NOTE).not.toMatch(banned);
  });

  it("the short paths land on /start or on their own page, with the same tags either way", async () => {
    const redirects = await nextConfig.redirects();
    for (const slug of SPOKEN) {
      const rule = redirects.find((r: { source: string }) => r.source === `/${slug}`);
      expect(rule, slug).toBeDefined();
      const to = new URL(rule.destination, "https://example.test");
      expect(["/start", `/legends/${slug}`], slug).toContain(to.pathname);
      expect(to.searchParams.get("utm_source")).toBe("video");
      expect(to.searchParams.get("utm_medium")).toBe("spoken");
      expect(to.searchParams.get("utm_campaign")).toBe("legends");
      expect(to.searchParams.get("utm_content")).toBe(slug);
    }
  });

  it("is served on the brand domain and kept out of the sitemap", async () => {
    const hosts = await import("../hosts");
    for (const slug of SPOKEN) expect(hosts.isPublicPath(`/legends/${slug}`), slug).toBe(true);
    // With a brand domain set, or the sitemap is empty and this would pass for
    // the wrong reason.
    vi.resetModules();
    process.env.NEXT_PUBLIC_BRAND_URL = "https://www.example.test";
    try {
      const sitemap = (await import("../../app/sitemap")).default;
      const urls = sitemap().map((e) => e.url);
      expect(urls).toContain("https://www.example.test/start");
      expect(urls.join(" ")).not.toContain("/legends");
    } finally {
      delete process.env.NEXT_PUBLIC_BRAND_URL;
      vi.resetModules();
    }
  });

  it("each page stays out of search while it is being looked at", async () => {
    const { generateMetadata, generateStaticParams } = await import("../../app/legends/[slug]/page");
    expect(generateStaticParams().map((p: { slug: string }) => p.slug).sort()).toEqual(
      LEGENDS.map((l) => l.slug).sort(),
    );
    for (const legend of LEGENDS) {
      const meta = generateMetadata({ params: { slug: legend.slug } });
      expect(meta.robots, legend.slug).toMatchObject({ index: false });
      expect(meta.alternates?.canonical).toBe(`/legends/${legend.slug}`);
    }
  });
});

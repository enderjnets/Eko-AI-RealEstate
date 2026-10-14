import { afterEach, describe, expect, it, vi } from "vitest";

const BRAND = {
  NEXT_PUBLIC_LANDING_BRAND: "Denver Home Story",
  NEXT_PUBLIC_LANDING_ADVISORS: "Natalia & Robbie",
  NEXT_PUBLIC_LANDING_BROKERAGE: "Engel & Völkers",
  NEXT_PUBLIC_LANDING_ADDRESS: "533 E Hopkins Ave, Ste 101, Aspen, CO 81611",
  NEXT_PUBLIC_LANDING_PHONE: "+17208249313",
  NEXT_PUBLIC_LANDING_INSTAGRAM: "https://www.instagram.com/denverhomestory/",
};

async function load(env: Record<string, string>) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) process.env[k] = v;
  return import("../structuredData");
}

afterEach(() => {
  for (const k of Object.keys(BRAND)) delete process.env[k];
  vi.resetModules();
});

describe("structured data", () => {
  it("splits a printed US address, and refuses one it cannot read rather than guess", async () => {
    const { postalAddress } = await load({});
    expect(postalAddress("533 E Hopkins Ave, Ste 101, Aspen, CO 81611")).toMatchObject({
      streetAddress: "533 E Hopkins Ave, Ste 101",
      addressLocality: "Aspen",
      addressRegion: "CO",
      postalCode: "81611",
    });
    expect(postalAddress("somewhere in Colorado")).toBeNull();
  });

  it("describes the agent with exactly what the page prints, and nothing without a brand", async () => {
    const sd = await load(BRAND);
    const data = sd.agentJsonLd("https://www.example.test") as { "@graph": Record<string, unknown>[] };
    const agent = data["@graph"][0];
    expect(agent).toMatchObject({
      "@type": "RealEstateAgent",
      name: "Denver Home Story",
      telephone: "+17208249313",
      parentOrganization: { name: "Engel & Völkers" },
      sameAs: ["https://www.instagram.com/denverhomestory/"],
    });
    expect((agent.address as Record<string, string>).addressLocality).toBe("Aspen");
    expect(sd.agentJsonLd("")).toBeNull();
    for (const k of Object.keys(BRAND)) delete process.env[k];
    const bare = await load({});
    expect(bare.agentJsonLd("https://www.example.test")).toBeNull();
  });

  it("cites every source a legend page prints, once each", async () => {
    const sd = await load(BRAND);
    const { LEGENDS } = await import("../legends");
    for (const legend of LEGENDS) {
      const data = sd.legendJsonLd(legend, "https://www.example.test") as { "@graph": Record<string, unknown>[] };
      const article = data["@graph"][0];
      const cited = (article.citation as { url: string }[]).map((c) => c.url);
      const printed = new Set(legend.facts.flatMap((f) => f.sources.map((s) => s.url)));
      expect(new Set(cited), legend.slug).toEqual(printed);
      expect(cited.length, legend.slug).toBe(printed.size);
      expect(article.headline).toBe(legend.title);
      expect(article.url).toBe(`https://www.example.test/legends/${legend.slug}`);
      // No date: the legends do not record one, and a build date is not a publication date.
      expect(article).not.toHaveProperty("datePublished");
    }
  });

  it("cannot be closed early by a value that contains </script>", async () => {
    const { jsonLdScript } = await load({});
    expect(jsonLdScript({ name: "</script><script>alert(1)</script>" })).not.toContain("</script>");
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { dialable, parseTestimonials } from "../landing";

describe("dialable", () => {
  it("strips the punctuation a human number is written with", () => {
    expect(dialable("(303) 359-5110")).toBe("3033595110");
  });

  it("keeps a leading + so an international number still dials", () => {
    expect(dialable("+1 303-359-5110")).toBe("+13033595110");
  });

  it("drops a + that is not the country prefix", () => {
    // tel: treats a stray + as malformed and the link quietly does nothing.
    expect(dialable("+1 303+359+5110")).toBe("+13033595110");
  });

  it("survives an empty value rather than producing 'tel:'", () => {
    expect(dialable("")).toBe("");
  });

  it("stops at an extension instead of dialling a different number", () => {
    // Merging the extension makes 30355501922 — eleven digits, plausibly
    // someone else's line, and the phone dials it without complaint.
    expect(dialable("(303) 555-0192 ext. 12")).toBe("3035550192");
    expect(dialable("303-555-0192 x12")).toBe("3035550192");
  });
});

describe("parseTestimonials", () => {
  it("returns none when nothing is configured — the default", () => {
    expect(parseTestimonials("")).toEqual([]);
  });

  it("returns none rather than throwing on malformed JSON", () => {
    // A broken env var must cost the section, never the whole page.
    expect(parseTestimonials("[{quote:")).toEqual([]);
  });

  it("returns none when the JSON is valid but not a list", () => {
    expect(parseTestimonials('{"quote":"a","attribution":"b"}')).toEqual([]);
  });

  it("keeps only entries that carry both a quote and an attribution", () => {
    const raw = JSON.stringify([
      { quote: "They priced it right.", attribution: "Seller · Cherry Creek" },
      { quote: "No attribution here" },
      { attribution: "No quote here" },
      { quote: "   ", attribution: "Blank quote" },
      "not an object",
      null,
    ]);
    expect(parseTestimonials(raw)).toEqual([
      { quote: "They priced it right.", attribution: "Seller · Cherry Creek" },
    ]);
  });

  it("trims the values it keeps", () => {
    const raw = JSON.stringify([{ quote: "  Quoted.  ", attribution: "  Buyer  " }]);
    expect(parseTestimonials(raw)).toEqual([{ quote: "Quoted.", attribution: "Buyer" }]);
  });
});

/**
 * The footer's channel row obeys the rule the whole page obeys: a fact that
 * was not configured does not appear. Worth a test and not an eyeball, because
 * the failure is an empty circle linking to nowhere — which looks like a bug in
 * the brand, on the brand's own page.
 */
describe("LANDING.socials", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  const load = async () => {
    vi.resetModules();
    return (await import("../landing")).LANDING.socials;
  };

  it("lists only the channels that were configured, in the design's order", async () => {
    vi.stubEnv("NEXT_PUBLIC_LANDING_INSTAGRAM", "https://instagram.test/x");
    vi.stubEnv("NEXT_PUBLIC_LANDING_YOUTUBE", "");
    vi.stubEnv("NEXT_PUBLIC_LANDING_TIKTOK", "https://tiktok.test/x");
    expect((await load()).map((s) => s.key)).toEqual(["instagram", "tiktok"]);
  });

  it("is empty when none is set, so the row disappears instead of emptying", async () => {
    vi.stubEnv("NEXT_PUBLIC_LANDING_INSTAGRAM", "");
    vi.stubEnv("NEXT_PUBLIC_LANDING_YOUTUBE", "");
    vi.stubEnv("NEXT_PUBLIC_LANDING_TIKTOK", "");
    expect(await load()).toEqual([]);
  });

  it("ignores a value that is only whitespace", async () => {
    vi.stubEnv("NEXT_PUBLIC_LANDING_INSTAGRAM", "   ");
    vi.stubEnv("NEXT_PUBLIC_LANDING_YOUTUBE", "");
    vi.stubEnv("NEXT_PUBLIC_LANDING_TIKTOK", "");
    expect(await load()).toEqual([]);
  });
});

/**
 * How the site names itself in public. v0.70.0 shipped with the string
 * "Denver Home Story" appearing ZERO times on the page — the wordmark, the
 * title and the footer all named the advisors instead — so a visitor arriving
 * from the brand's own video had nothing telling them they were in the right
 * place. These pin both directions: the brand leads when configured, and
 * nothing changes for an install that has none.
 */
describe("the public name", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  const load = async (env: Record<string, string>) => {
    vi.resetModules();
    for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
    return await import("../landing");
  };

  const AGENCY = {
    NEXT_PUBLIC_LANDING_ADVISORS: "Natalia & Robbie",
    NEXT_PUBLIC_LANDING_BROKERAGE: "Engel & Völkers Aspen",
  };

  it("leads with the brand, and the people follow it", async () => {
    const m = await load({ ...AGENCY, NEXT_PUBLIC_LANDING_BRAND: "Denver Home Story" });
    expect(m.publicName).toBe("Denver Home Story · Natalia & Robbie, Engel & Völkers Aspen");
    expect(m.publicTitle).toBe("Denver Home Story · Natalia & Robbie, Engel & Völkers Aspen");
    expect(m.homeScreenName).toBe("Denver Home Story");
  });

  it("without a brand is exactly what the page shipped with", async () => {
    const m = await load({ ...AGENCY, NEXT_PUBLIC_LANDING_BRAND: "" });
    expect(m.publicName).toBe("Natalia & Robbie · Engel & Völkers Aspen");
    expect(m.publicTitle).toBe("Natalia & Robbie · Engel & Völkers Aspen — Colorado real estate");
    expect(m.homeScreenName).toBe("Natalia & Robbie · Engel & Völkers Aspen");
  });

  it("with nothing configured at all still names something", async () => {
    const m = await load({
      NEXT_PUBLIC_LANDING_BRAND: "",
      NEXT_PUBLIC_LANDING_ADVISORS: "",
      NEXT_PUBLIC_LANDING_BROKERAGE: "",
    });
    expect(m.publicName).toBe("");
    expect(m.publicTitle).toBe("Colorado real estate");
    expect(m.homeScreenName).toBe("Colorado real estate");
  });
});

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

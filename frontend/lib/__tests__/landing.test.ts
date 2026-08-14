import { describe, expect, it } from "vitest";
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

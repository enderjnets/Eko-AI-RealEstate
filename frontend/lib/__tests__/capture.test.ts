import { describe, expect, it } from "vitest";

import { UTM_KEYS, collectAttribution } from "../capture";

function params(values: Record<string, string>) {
  return { get: (k: string) => (k in values ? values[k] : null) };
}

describe("collectAttribution", () => {
  it("keeps the whitelisted keys", () => {
    const out = collectAttribution(
      params({ utm_source: "tiktok", utm_content: "denver-washpark-01" }),
    );
    expect(out).toEqual({
      utm_source: "tiktok",
      utm_content: "denver-washpark-01",
    });
  });

  it("ignores anything not on the whitelist", () => {
    // The server drops these anyway; not sending them keeps arbitrary
    // visitor-controlled text off the wire entirely.
    const out = collectAttribution(
      params({ utm_source: "tiktok", evil: "<script>", note: "hello" }),
    );
    expect(out).toEqual({ utm_source: "tiktok" });
  });

  it("drops empty and whitespace-only values", () => {
    // `?utm_source=` would otherwise make every "does this lead have a source"
    // query answer yes for a lead that has none.
    const out = collectAttribution(params({ utm_source: "  ", utm_medium: "" }));
    expect(out).toEqual({});
  });

  it("trims values", () => {
    expect(collectAttribution(params({ utm_source: " tiktok " }))).toEqual({
      utm_source: "tiktok",
    });
  });

  it("records the referrer when there is one", () => {
    const out = collectAttribution(params({}), "https://www.tiktok.com/");
    expect(out).toEqual({ referrer: "https://www.tiktok.com/" });
  });

  it("omits the referrer key entirely when there is none", () => {
    expect(collectAttribution(params({}), "")).toEqual({});
    expect(collectAttribution(params({}), null)).toEqual({});
    expect(collectAttribution(params({}))).toEqual({});
  });

  it("covers every key the backend whitelists", () => {
    // If the backend gains an attribution key and this list does not, the page
    // silently stops forwarding it and the data is simply absent — no error,
    // no warning, just a column of nulls nobody notices for a quarter.
    const backendKeys = [
      "utm_source",
      "utm_medium",
      "utm_campaign",
      "utm_content",
      "utm_term",
      "gclid",
      "fbclid",
      "landing_variant",
      "tier",
      "referrer", // set from document.referrer, not from the query string
    ];
    expect([...UTM_KEYS, "referrer"].sort()).toEqual(backendKeys.sort());
  });
});

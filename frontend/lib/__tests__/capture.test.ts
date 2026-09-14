import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { UTM_KEYS, collectAttribution, withAttribution } from "../capture";

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
    // Read out of the backend source, not re-typed here. A hardcoded copy of
    // the list would be two copies of the same belief: add a key to the
    // backend and BOTH stay stale together, the page silently stops forwarding
    // it, and the symptom is a column of nulls nobody notices for a quarter.
    const source = readFileSync(
      join(__dirname, "../../../backend/app/services/capture.py"),
      "utf8",
    );
    const block = source.match(
      /ATTRIBUTION_KEYS = frozenset\(\s*\{([\s\S]*?)\}\s*\)/,
    );
    expect(block, "ATTRIBUTION_KEYS not found in capture.py").toBeTruthy();
    const backendKeys = [...block![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(backendKeys.length).toBeGreaterThan(5); // the regex really matched

    // `referrer` is on both sides but comes from document.referrer rather than
    // the query string, so the page collects it outside UTM_KEYS.
    expect([...UTM_KEYS, "referrer"].sort()).toEqual([...backendKeys].sort());
  });
});

describe("withAttribution", () => {
  it("adds only trimmed attribution keys", () => {
    expect(
      withAttribution("/calculator", {
        utm_source: " instagram ",
        utm_content: "piece-42",
        referrer: "https://instagram.com/",
        unknown: "ignored",
      }),
    ).toBe("/calculator?utm_source=instagram&utm_content=piece-42");
  });

  it("preserves an existing query and fragment", () => {
    expect(
      withAttribution("/?mode=sell#consult", {
        utm_source: "youtube",
        landing_variant: "start",
      }),
    ).toBe("/?mode=sell&utm_source=youtube&landing_variant=start#consult");
  });

  it("leaves telephone links unchanged", () => {
    expect(withAttribution("tel:+13035550101", { utm_source: "tiktok" })).toBe(
      "tel:+13035550101",
    );
  });

  it("leaves email links unchanged", () => {
    expect(
      withAttribution("mailto:team@example.com", { utm_source: "tiktok" }),
    ).toBe("mailto:team@example.com");
  });

  it("leaves unattributed links unchanged", () => {
    expect(withAttribution("/calculator", {})).toBe("/calculator");
  });

  it("percent-encodes attribution values", () => {
    expect(
      withAttribution("/calculator", {
        utm_source: "instagram reels/cañon",
      }),
    ).toBe("/calculator?utm_source=instagram+reels%2Fca%C3%B1on");
  });

  it("limits each attribution value to 200 characters", () => {
    expect(
      withAttribution("/calculator", { utm_content: "x".repeat(201) }),
    ).toBe(`/calculator?utm_content=${"x".repeat(200)}`);
  });

  it("drops empty attribution values", () => {
    expect(withAttribution("/calculator", { utm_medium: "   " })).toBe(
      "/calculator",
    );
  });

  it("replaces an existing allowed key without duplicating it", () => {
    const href = withAttribution(
      "/calculator?utm_source=old&utm_source=older&mode=buy",
      { utm_source: "tiktok" },
    );

    expect(href).toBe("/calculator?utm_source=tiktok&mode=buy");
    expect(href.match(/utm_source=/g)).toHaveLength(1);
  });
});

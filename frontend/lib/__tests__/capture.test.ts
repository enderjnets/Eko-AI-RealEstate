import { readFileSync } from "node:fs";
import { join } from "node:path";

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

/**
 * The two pure pieces the publish queue added to the client.
 *
 * There is no jsdom in this repo, so the component that shows a countdown is
 * verified in a browser. What CAN be pinned here is the arithmetic it prints
 * and the URL it asks for — and both have a way of going quietly wrong.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { timeUntil } from "@/lib/format";
import { contentApi } from "@/lib/api";

describe("timeUntil", () => {
  // Frozen. `timeUntil` reads the clock when it runs, so between building the
  // ISO string and reading it back the real clock advances a millisecond and
  // "in 2 d 3 h" becomes "in 2 d 2 h". A test that fails once a run is worse
  // than no test: it teaches people to re-run until it is green.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const at = (ms: number) => new Date(Date.now() + ms).toISOString();

  it("counts days, hours and minutes, in both languages", () => {
    expect(timeUntil(at(2 * 86400_000 + 3 * 3600_000), "en")).toBe("in 2 d 3 h");
    expect(timeUntil(at(2 * 86400_000 + 3 * 3600_000), "es")).toBe("en 2 d 3 h");
    expect(timeUntil(at(4 * 3600_000 + 12 * 60_000), "en")).toBe("in 4 h 12 min");
    expect(timeUntil(at(4 * 3600_000 + 12 * 60_000), "es")).toBe("en 4 h 12 min");
    expect(timeUntil(at(12 * 60_000), "en")).toBe("in 12 min");
    expect(timeUntil(at(12 * 60_000), "es")).toBe("en 12 min");
  });

  it("drops a zero remainder instead of printing 'in 2 d 0 h'", () => {
    expect(timeUntil(at(2 * 86400_000), "en")).toBe("in 2 d");
    expect(timeUntil(at(4 * 3600_000), "en")).toBe("in 4 h");
  });

  it("says 'now' for anything already past instead of going negative", () => {
    // The reconciler runs on a tick, so a slot whose hour has come sits in the
    // past for a few minutes. "in -3 min" would read as a bug.
    expect(timeUntil(at(-3 * 60_000), "en")).toBe("now");
    expect(timeUntil(at(-3 * 60_000), "es")).toBe("ahora");
    expect(timeUntil(at(-9 * 86400_000), "en")).toBe("now");
  });

  it("has something to say about a row that was never scheduled", () => {
    expect(timeUntil(null, "en")).toBe("—");
  });
});

describe("contentApi.list", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const urls: string[] = [];
  const stubFetch = () => {
    urls.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return new Response("[]", {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );
  };

  it("repeats the parameter so several statuses reach one tab", async () => {
    stubFetch();
    await contentApi.list(["approved", "publishing"]);
    expect(urls[0]).toContain("status=approved");
    expect(urls[0]).toContain("status=publishing");
  });

  it("keeps the single-value contract that predates the queue", async () => {
    stubFetch();
    await contentApi.list("rejected");
    expect(urls[0]).toContain("?status=rejected");
    expect(urls[0]).not.toContain("&status=");
  });

  it("asks for everything when no status is given", async () => {
    stubFetch();
    await contentApi.list();
    expect(urls[0]).not.toContain("status=");
  });
});

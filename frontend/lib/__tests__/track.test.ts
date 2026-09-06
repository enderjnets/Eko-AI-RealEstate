/**
 * The tracker's rules, tested without a browser.
 *
 * There is no jsdom in this repo, which is why `lib/track.ts` holds everything
 * that decides something and `LandingTracker.tsx` holds only the plumbing that
 * attaches it to the DOM. Every rule below is one a report depends on: what
 * gets sent, how often, what is deduplicated, and the two cases where the
 * tracker must send nothing at all.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  ATTRIBUTION_STORAGE_KEY,
  MAX_PER_BATCH,
  SESSION_STORAGE_KEY,
  Tracker,
  beaconSender,
  newSessionKey,
  persistAttribution,
  sectionWasSeen,
  sessionKey,
  storedAttribution,
  trackingAllowed,
  type TrackerOptions,
} from "../track";

function memoryStorage(seed: Record<string, string> = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

/** Instagram's and TikTok's embedded browsers do this rather than return null. */
const hostileStorage = {
  getItem() {
    throw new Error("blocked");
  },
  setItem() {
    throw new Error("blocked");
  },
};

function params(query: Record<string, string>) {
  return { get: (k: string) => query[k] ?? null };
}

function collector() {
  const sent: string[] = [];
  return { sent, send: (body: string) => (sent.push(body), true) };
}

function tracker(over: Partial<TrackerOptions> = {}) {
  const c = collector();
  return {
    sent: c.sent,
    t: new Tracker({ session: "a".repeat(32), path: "/", send: c.send, ...over }),
  };
}

describe("session key", () => {
  it("is 32 hex characters", () => {
    expect(newSessionKey()).toMatch(/^[0-9a-f]{32}$/);
  });

  it("is created once and then reused for the tab", () => {
    const s = memoryStorage();
    const first = sessionKey(s);
    expect(sessionKey(s)).toBe(first);
    expect(s.dump()[SESSION_STORAGE_KEY]).toBe(first);
  });

  it("replaces a stored value that is not a session key", () => {
    // Storage is writable by anything else on the origin, and the server pins
    // the shape — a junk value would make every beacon a 400.
    const s = memoryStorage({ [SESSION_STORAGE_KEY]: "../../etc/passwd" });
    expect(sessionKey(s)).toMatch(/^[0-9a-f]{32}$/);
  });

  it("survives a browser with no crypto at all", () => {
    // The failure this guards is not a bad key: it is `sessionKey` catching a
    // throw and calling the thrower again, so the exception escapes the effect
    // and takes the landing page down with it. Analytics must never be able to
    // break the page it measures.
    const real = globalThis.crypto;
    try {
      // @ts-expect-error — deliberately removing it
      delete globalThis.crypto;
      expect(newSessionKey()).toMatch(/^[0-9a-f]{32}$/);
      expect(sessionKey(hostileStorage)).toMatch(/^[0-9a-f]{32}$/);
    } finally {
      Object.defineProperty(globalThis, "crypto", { value: real, configurable: true });
    }
  });

  it("survives storage that throws instead of returning null", () => {
    expect(sessionKey(hostileStorage)).toMatch(/^[0-9a-f]{32}$/);
    expect(sessionKey(null)).toMatch(/^[0-9a-f]{32}$/);
  });
});

describe("attribution", () => {
  it("remembers the first touch so it survives navigating the page", () => {
    const s = memoryStorage();
    const first = persistAttribution(params({ utm_source: "tiktok" }), "", s);
    expect(first).toEqual({ utm_source: "tiktok" });
    // Later, with the query string gone, it is still TikTok that sent them.
    expect(persistAttribution(params({}), "", s)).toEqual({ utm_source: "tiktok" });
  });

  it("does not let a reload overwrite where they came from", () => {
    const s = memoryStorage();
    persistAttribution(params({ utm_source: "youtube" }), "", s);
    expect(persistAttribution(params({ utm_source: "tiktok" }), "", s)).toEqual({
      utm_source: "youtube",
    });
  });

  it("stores the referrer when the platform stripped the query string", () => {
    const s = memoryStorage();
    const got = persistAttribution(params({}), "https://www.tiktok.com/@x", s);
    expect(got.referrer).toBe("https://www.tiktok.com/@x");
  });

  it("writes nothing when the visit carries no attribution at all", () => {
    const s = memoryStorage();
    expect(persistAttribution(params({}), "", s)).toEqual({});
    expect(s.dump()[ATTRIBUTION_STORAGE_KEY]).toBeUndefined();
  });

  it("filters what it reads back to the same whitelist the server enforces", () => {
    const s = memoryStorage({
      [ATTRIBUTION_STORAGE_KEY]: JSON.stringify({ utm_source: "tiktok", evil: "x" }),
    });
    expect(storedAttribution(s)).toEqual({ utm_source: "tiktok" });
  });

  it("survives junk in storage", () => {
    expect(storedAttribution(memoryStorage({ [ATTRIBUTION_STORAGE_KEY]: "{{{" }))).toEqual({});
    expect(storedAttribution(memoryStorage({ [ATTRIBUTION_STORAGE_KEY]: "[1,2]" }))).toEqual({});
    expect(storedAttribution(hostileStorage)).toEqual({});
  });
});

describe("Global Privacy Control", () => {
  it("is honoured", () => {
    expect(trackingAllowed({ globalPrivacyControl: true })).toBe(false);
  });

  it("does not read absence as refusal", () => {
    expect(trackingAllowed({})).toBe(true);
    expect(trackingAllowed(undefined)).toBe(true);
    expect(trackingAllowed({ globalPrivacyControl: false })).toBe(true);
  });

  it("means the tracker sends nothing at all", () => {
    const { t, sent } = tracker({ allowed: false });
    t.record("page_view");
    t.record("cta_click");
    t.scrolled(100);
    t.section("about");
    t.flush();
    expect(sent).toEqual([]);
  });
});

describe("what gets sent, and when", () => {
  it("holds a page view and sends a tap immediately", () => {
    // A visitor who taps "call" is on their way out of the page; a queued
    // batch would never leave.
    const { t, sent } = tracker();
    t.record("page_view");
    expect(sent).toHaveLength(0);
    t.record("tel_click", { where: "hero" });
    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]);
    expect(body.events.map((e: { t: string }) => e.t)).toEqual(["page_view", "tel_click"]);
    expect(body.events[1].meta).toEqual({ where: "hero" });
  });

  it("carries the contract the server validates", () => {
    const { t, sent } = tracker({
      form: "a-form-key",
      lang: "es",
      screenW: 390,
      utm: { utm_source: "tiktok" },
      referrer: "https://www.tiktok.com/",
      path: "/",
    });
    t.record("form_submit");
    const body = JSON.parse(sent[0]);
    expect(Object.keys(body).sort()).toEqual(
      ["events", "form", "lang", "path", "referrer", "screen_w", "session", "utm"].sort(),
    );
    expect(body.session).toMatch(/^[0-9a-f]{32}$/);
  });

  it("omits what it has nothing to say about", () => {
    // `extra="forbid"` on the server rejects a key it does not know, and a
    // null is not the same as an absent field.
    const { t, sent } = tracker();
    t.record("form_submit");
    expect(Object.keys(JSON.parse(sent[0])).sort()).toEqual(["events", "path", "session"]);
  });

  it("never sends more events than the server accepts", () => {
    const { t, sent } = tracker();
    for (let i = 0; i < MAX_PER_BATCH + 3; i++) t.record("page_view");
    t.flush();
    for (const body of sent) {
      expect(JSON.parse(body).events.length).toBeLessThanOrEqual(MAX_PER_BATCH);
    }
    const total = sent.reduce((n, b) => n + JSON.parse(b).events.length, 0);
    expect(total).toBe(MAX_PER_BATCH + 3);
  });

  it("sends nothing when there is nothing to send", () => {
    const { t, sent } = tracker();
    t.flush();
    expect(sent).toEqual([]);
  });
});

describe("deduplication", () => {
  it("reports each scroll depth once, and only the ones crossed", () => {
    const { t, sent } = tracker();
    t.scrolled(30);
    t.scrolled(40);
    t.scrolled(60);
    t.flush();
    const marks = JSON.parse(sent[0]).events.map((e: { meta: { pct: number } }) => e.meta.pct);
    expect(marks).toEqual([25, 50]);
  });

  it("reports a section once however many times it re-enters view", () => {
    const { t, sent } = tracker();
    t.section("about");
    t.section("about");
    t.section("markets");
    t.flush();
    const sections = JSON.parse(sent[0]).events.map(
      (e: { meta: { section: string } }) => e.meta.section,
    );
    expect(sections).toEqual(["about", "markets"]);
  });

  it("ignores a scroll position that is not a number", () => {
    const { t, sent } = tracker();
    t.scrolled(Number.NaN);
    t.scrolled(Number.POSITIVE_INFINITY);
    t.flush();
    expect(sent).toEqual([]);
  });
});

describe("the sender", () => {
  it("prefers sendBeacon with a text/plain body", () => {
    // A beacon carrying an application/json Blob is refused outright by
    // Chromium in some contexts, which is why the server parses by hand.
    const sendBeacon = vi.fn(() => true);
    const fetcher = vi.fn();
    const send = beaconSender("/u", { sendBeacon } as unknown as Navigator, fetcher as never);
    expect(send("{}")).toBe(true);
    expect(fetcher).not.toHaveBeenCalled();
    expect((sendBeacon.mock.calls[0] as unknown[])[1]).toBeInstanceOf(Blob);
    expect(((sendBeacon.mock.calls[0] as unknown[])[1] as Blob).type).toBe("text/plain");
  });

  it("falls back to fetch when the beacon is refused or absent", () => {
    const fetcher = vi.fn(() => Promise.resolve(new Response()));
    const refused = beaconSender("/u", { sendBeacon: () => false } as unknown as Navigator, fetcher as never);
    expect(refused("{}")).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((fetcher.mock.calls[0] as unknown[])[1]).toMatchObject({
      method: "POST",
      keepalive: true,
    });

    const absent = beaconSender("/u", {} as Navigator, fetcher as never);
    expect(absent("{}")).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not throw when there is no way to send at all", () => {
    expect(beaconSender("/u", undefined, undefined)("{}")).toBe(true);
  });
});

describe("wiring", () => {
  const read = (p: string) =>
    readFileSync(join(process.cwd(), p), "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

  it("mounts the tracker outside the pinned hero", () => {
    // Same trap the mobile menu documents: the hero is `position: sticky` with
    // `overflow: hidden` and acquires `will-change: transform`, so anything
    // inside it gets a containing block it did not ask for. Asserted on the
    // ROOT component's body — file order is not nesting, and the pin host
    // lives in `Hero`, several hundred lines earlier.
    const src = read("components/landing/Landing.tsx");
    const root = src.slice(src.indexOf("export function Landing()"));
    expect(root).toContain("<LandingTracker />");
    expect(root).not.toContain("data-pin-host");
    // A sibling of <main>, like the menu: outside the sections, not between
    // them, so nothing in the page tree can move it.
    expect(root.indexOf("<LandingTracker />")).toBeLessThan(root.indexOf("<main>"));
  });

  it("removes every listener it adds", () => {
    // An inline arrow cannot be removed, so a listener bound that way outlives
    // the effect while holding a tracker that has already been torn down —
    // and each remount adds another. Counting is crude and catches exactly
    // this, which is the mistake that actually gets made.
    const src = read("components/landing/LandingTracker.tsx");
    const added = (src.match(/addEventListener\(/g) ?? []).length;
    const removed = (src.match(/removeEventListener\(/g) ?? []).length;
    expect(added).toBeGreaterThan(0);
    expect(removed).toBe(added);
  });

  it("agrees with the server about how many events fit in a batch", () => {
    // Two constants in two languages that must hold the same number: over it,
    // every batch is a 400 and the table quietly stays empty.
    const server = readFileSync(
      join(process.cwd(), "..", "backend", "app", "api", "v1", "public.py"),
      "utf8",
    );
    const declared = server.match(/^EVENTS_MAX_PER_BATCH = (\d+)/m);
    expect(declared).not.toBeNull();
    expect(Number(declared![1])).toBe(MAX_PER_BATCH);
  });

  it("labels every anchor the tracker reports on", () => {
    // Without `data-track` every tap reads as "somebody clicked call", and
    // which control works is the question this page exists to answer.
    const src = read("components/landing/Landing.tsx");
    const anchors = src.match(/<a\b[^>]*?(?:href="#consult"|href=\{`tel:)/gs) ?? [];
    expect(anchors.length).toBeGreaterThanOrEqual(5);
    const labelled = src.match(/data-track="/g) ?? [];
    expect(labelled.length).toBe(anchors.length);
  });

  it("sends the session id with the lead, so the visit joins the funnel", () => {
    const src = read("components/landing/ConsultForm.tsx");
    expect(src).toMatch(/session_id:\s*sessionId/);
    expect(src).toMatch(/getTracker\(\)\?\.record\("form_submit"\)/);
    expect(src).toMatch(/getTracker\(\)\?\.record\("form_error"/);
    expect(src).toMatch(/onFocusCapture=\{onFirstTouch\}/);
  });

  it("prefers the remembered first touch over an empty query string", () => {
    const src = read("components/landing/ConsultForm.tsx");
    const stored = src.indexOf("storedAttribution(storage)");
    const current = src.indexOf("...collected");
    expect(stored).toBeGreaterThan(-1);
    // Spread later wins, so the CURRENT url still beats what was remembered.
    expect(current).toBeGreaterThan(stored);
  });
});

describe("sectionWasSeen", () => {
  // Measured against production with Safari's own engine on an iPhone 13
  // (viewport 664px): #about is 1249px tall and #how 1259px, so the most
  // either can ever intersect is 0.53 of itself. Under the old 0.5 threshold
  // they counted only when almost perfectly centred, and in a real pass over
  // the page neither was ever reported. The funnel then said people left
  // before those sections when they had read straight through them.
  const PHONE = 664;

  it("counts a section taller than the screen once it fills half the screen", () => {
    expect(sectionWasSeen(332, 1249, PHONE)).toBe(true);
    expect(sectionWasSeen(331, 1249, PHONE)).toBe(false);
  });

  it("counts a section shorter than the screen at half of itself", () => {
    // Half the screen is unreachable for a 300px block; requiring it would
    // trade one blind spot for another.
    expect(sectionWasSeen(150, 300, PHONE)).toBe(true);
    expect(sectionWasSeen(149, 300, PHONE)).toBe(false);
  });

  it("does not count a section barely on screen", () => {
    expect(sectionWasSeen(40, 1249, PHONE)).toBe(false);
  });

  it("survives the degenerate numbers a browser can hand it", () => {
    expect(sectionWasSeen(0, 1249, PHONE)).toBe(false);
    expect(sectionWasSeen(100, 0, PHONE)).toBe(false);
    expect(sectionWasSeen(100, 1249, 0)).toBe(false);
    expect(sectionWasSeen(Number.NaN, 1249, PHONE)).toBe(false);
  });

  it("the four real sections all become reachable on the smallest phone", () => {
    // Heights read off the live page. Under the old rule #about and #how
    // topped out at 0.53 of themselves; here every one of them is reachable
    // because the screen, not the block, sets the bar.
    for (const height of [1249, 1259, 742, 1020]) {
      const mostVisible = Math.min(height, PHONE);
      expect(sectionWasSeen(mostVisible, height, PHONE)).toBe(true);
    }
  });
});

describe("the calculator's own funnel step", () => {
  it("sends calculator_result at once, with its meta", () => {
    // Whoever sees their number may leave in the same second; a queued batch
    // would never leave with them.
    const { t, sent } = tracker();
    t.record("page_view");
    expect(sent).toHaveLength(0);
    t.record("calculator_result", { price_k: 310, capped: "rent", credit: "good" });
    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]);
    expect(body.events.map((e: { t: string }) => e.t)).toEqual(["page_view", "calculator_result"]);
    expect(body.events[1].meta).toEqual({ price_k: 310, capped: "rent", credit: "good" });
  });
});

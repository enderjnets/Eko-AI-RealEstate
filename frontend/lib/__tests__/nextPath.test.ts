import { describe, expect, it, beforeEach, afterEach } from "vitest";

import {
  currentNext,
  isSafeNext,
  navigationChangesRoute,
  nextPathname,
  rememberNext,
  takeNext,
} from "@/lib/nextPath";

/**
 * `next` is the one value in this app that decides where a freshly signed-in
 * session is sent. It arrives in a URL anybody can write, so the tests that
 * matter most here are the rejections: an accepted `//evil.example` is an open
 * redirect on the page that has just handled a password.
 *
 * There is no jsdom in this suite (see `vitest.config.ts`), so the storage is a
 * hand-rolled double. That is not a shortcut — it is what lets the last two
 * tests exist at all: a real `sessionStorage` cannot be asked to throw, and
 * throwing is exactly what it does in a browser set to block site data.
 */

class FakeStorage {
  map = new Map<string, string>();
  throwOn: "none" | "get" | "set" = "none";
  getItem(k: string): string | null {
    if (this.throwOn === "get") throw new Error("blocked");
    return this.map.has(k) ? (this.map.get(k) as string) : null;
  }
  setItem(k: string, v: string): void {
    if (this.throwOn === "set") throw new Error("blocked");
    this.map.set(k, v);
  }
  removeItem(k: string): void {
    this.map.delete(k);
  }
}

function install(fake: FakeStorage | undefined) {
  Object.defineProperty(globalThis, "sessionStorage", {
    value: fake,
    configurable: true,
    writable: true,
  });
}

describe("isSafeNext", () => {
  it("accepts the panel paths the notice links to", () => {
    expect(isSafeNext("/leads/12")).toBe(true);
    expect(isSafeNext("/leads/12?tab=timeline")).toBe(true);
    expect(isSafeNext("/leads/12#note-3")).toBe(true);
    // A hyphen is an ordinary path character; an over-broad "no punctuation"
    // rule would quietly reject half the routes this exists to preserve.
    expect(isSafeNext("/content-studio")).toBe(true);
  });

  it("refuses anything that could name another origin", () => {
    expect(isSafeNext("https://evil.example")).toBe(false);
    expect(isSafeNext("//evil.example")).toBe(false);
    expect(isSafeNext("/\\evil.example")).toBe(false);
    expect(isSafeNext("javascript:alert(1)")).toBe(false);
    expect(isSafeNext("leads/12")).toBe(false);
  });

  it("refuses the login pages themselves, which would bounce forever", () => {
    expect(isSafeNext("/login")).toBe(false);
    expect(isSafeNext("/login?next=/leads/1")).toBe(false);
    expect(isSafeNext("/register")).toBe(false);
  });

  it("refuses the login pages SPELLED differently, because the router does not", () => {
    // The string is not the route. `/leads/../login` is `/login` once the
    // browser is done with it, and comparing the raw string sees three
    // different values where the router sees one.
    expect(isSafeNext("/leads/../login")).toBe(false);
    expect(isSafeNext("/./login")).toBe(false);
    expect(isSafeNext("/login/")).toBe(false);
    // Next routes case-sensitively, so this is a 404 rather than the login
    // page — but a destination that 404s is not a destination either.
    expect(isSafeNext("/LOGIN")).toBe(false);
  });

  it("refuses whitespace, empties and absurd lengths", () => {
    expect(isSafeNext("/leads/12 x")).toBe(false);
    expect(isSafeNext("/leads/12\n")).toBe(false);
    expect(isSafeNext("")).toBe(false);
    expect(isSafeNext(null)).toBe(false);
    expect(isSafeNext(undefined)).toBe(false);
    expect(isSafeNext("/" + "a".repeat(600))).toBe(false);
  });
});

describe("rememberNext / takeNext", () => {
  let fake: FakeStorage;

  beforeEach(() => {
    fake = new FakeStorage();
    install(fake);
  });

  afterEach(() => {
    install(undefined);
  });

  it("returns the destination once and then forgets it", () => {
    rememberNext("/leads/12");
    expect(takeNext()).toBe("/leads/12");
    // The second read is the point: a value left behind would redirect a LATER
    // sign-in to a lead nobody asked for.
    expect(takeNext()).toBe(null);
  });

  it("never stores an unsafe destination", () => {
    rememberNext("//evil.example");
    expect(takeNext()).toBe(null);
    expect(fake.map.size).toBe(0);
  });

  it("refuses a stored value that is not safe when read back", () => {
    // Written by something other than `rememberNext` — a stale key, or a script
    // on the same origin. Validated on the way out too, not only on the way in.
    fake.map.set("eko.next", "https://evil.example");
    expect(takeNext()).toBe(null);
  });

  it("survives a storage that throws on read", () => {
    fake.map.set("eko.next", "/leads/12");
    fake.throwOn = "get";
    expect(takeNext()).toBe(null);
  });

  it("survives a storage that throws on write, and one that is absent", () => {
    fake.throwOn = "set";
    expect(() => rememberNext("/leads/12")).not.toThrow();
    install(undefined);
    expect(() => rememberNext("/leads/12")).not.toThrow();
    expect(takeNext()).toBe(null);
  });
});

describe("currentNext", () => {
  afterEach(() => {
    Object.defineProperty(globalThis, "location", {
      value: undefined,
      configurable: true,
      writable: true,
    });
  });

  it("keeps the query string, because a lead link may carry one", () => {
    Object.defineProperty(globalThis, "location", {
      value: { search: "?tab=timeline" },
      configurable: true,
      writable: true,
    });
    expect(currentNext("/leads/12")).toBe("/leads/12?tab=timeline");
  });

  it("is the bare path when there is no location to read", () => {
    expect(currentNext("/leads/12")).toBe("/leads/12");
  });
});


describe("nextPathname / navigationChangesRoute", () => {
  it("resolves a destination to the route it actually lands on", () => {
    expect(nextPathname("/leads/12?tab=timeline#note-3")).toBe("/leads/12");
    expect(nextPathname("/leads/../leads/12")).toBe("/leads/12");
    expect(nextPathname("/./leads")).toBe("/leads");
    // Percent-encoding is NOT decoded into a path separator, so this stays one
    // opaque segment on our own origin rather than becoming another host.
    expect(nextPathname("/%2f%2fevil.example")).toBe("/%2f%2fevil.example");
  });

  it("returns null for anything that would leave this origin", () => {
    expect(nextPathname("https://evil.example/x")).toBe(null);
    expect(nextPathname("//evil.example")).toBe(null);
  });

  it("says a query-only difference does NOT change the route", () => {
    // This is the whole point. The guard waits for a re-render keyed on the
    // pathname; if it waits for one that will never come, the panel hangs on
    // "Checking session…". Reachable with no attacker: an agent opening any
    // tracked link to the panel while signed out.
    expect(navigationChangesRoute("/leads?utm_source=mail", "/leads")).toBe(false);
    expect(navigationChangesRoute("/leads#note-3", "/leads")).toBe(false);
    expect(navigationChangesRoute("/./leads", "/leads")).toBe(false);
    expect(navigationChangesRoute("/leads/12", "/leads")).toBe(true);
  });
});

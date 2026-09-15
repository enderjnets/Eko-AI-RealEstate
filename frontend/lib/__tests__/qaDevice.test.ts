/**
 * Marking our own browsers, so the funnel stops counting us as customers.
 *
 * Measured against production on 15-sep-2026: of 193 sessions on the landing
 * page, 104 came from Parker, Denver, Aurora and The Pinery — the two agents,
 * and us. The tempting fix is to drop those cities. It is also wrong, because
 * Denver is exactly where the real customers are, and a city has never been an
 * identity. So the device says so itself and keeps saying it.
 */

import { describe, expect, it } from "vitest";

import { QA_STORAGE_KEY, qaDevice } from "../track";

class FakeStore {
  constructor(public readonly data: Record<string, string> = {}) {}
  getItem(k: string) {
    return k in this.data ? this.data[k] : null;
  }
  setItem(k: string, v: string) {
    this.data[k] = v;
  }
}

/** A store that throws on every access, like some embedded browsers do. */
const hostile = {
  getItem(): string {
    throw new Error("no");
  },
  setItem(): void {
    throw new Error("no");
  },
};

const params = (qs: string) => new URLSearchParams(qs);

describe("recognising one of our own browsers", () => {
  it("marks the device on the way in, and remembers it", () => {
    const store = new FakeStore();
    expect(qaDevice(params("eko_qa=1"), store)).toBe(true);
    expect(store.data[QA_STORAGE_KEY]).toBe("1");
  });

  it("still knows on the next visit, with nothing in the address bar", () => {
    // The whole point. A session marker would forget as soon as the tab
    // closed, and we would be back to guessing by city.
    const store = new FakeStore({ [QA_STORAGE_KEY]: "1" });
    expect(qaDevice(params(""), store)).toBe(true);
    expect(qaDevice(params("utm_source=youtube"), store)).toBe(true);
  });

  it("can be undone, which is not decoration", () => {
    // Without this, tapping the link on a personal phone would throw that
    // phone's traffic away for good — and the only way back would be clearing
    // site data, which nobody is going to work out on their own.
    const store = new FakeStore({ [QA_STORAGE_KEY]: "1" });
    expect(qaDevice(params("eko_qa=0"), store)).toBe(false);
    expect(store.data[QA_STORAGE_KEY]).toBe("0");
    expect(qaDevice(params(""), store)).toBe(false);
  });

  it("leaves a stranger's browser alone", () => {
    expect(qaDevice(params(""), new FakeStore())).toBe(false);
    expect(
      qaDevice(params("utm_source=youtube&utm_content=piece-40"), new FakeStore()),
    ).toBe(false);
  });

  it("ignores a value that is neither on nor off", () => {
    // `?eko_qa=yes` is somebody guessing at the spelling. Guessing must not
    // mark a real visitor's browser forever.
    const store = new FakeStore();
    expect(qaDevice(params("eko_qa=yes"), store)).toBe(false);
    expect(store.data[QA_STORAGE_KEY]).toBeUndefined();
  });

  it("marks this visit even when the flag cannot be stored", () => {
    // Private windows and embedded browsers throw on write. The answer they
    // just asked for still holds for the visit in front of us.
    expect(qaDevice(params("eko_qa=1"), hostile)).toBe(true);
  });

  it("answers 'not ours' when storage cannot be read at all", () => {
    // The safe direction: counting one of our own visits as a visitor is a
    // number slightly too high. The opposite would silently delete a real
    // person from the funnel, which is the failure that cannot be noticed.
    expect(qaDevice(params(""), hostile)).toBe(false);
    expect(qaDevice(params(""), null)).toBe(false);
    expect(qaDevice(params(""), undefined)).toBe(false);
  });

  it("marks the device even with no storage to remember it in", () => {
    expect(qaDevice(params("eko_qa=1"), null)).toBe(true);
  });
});

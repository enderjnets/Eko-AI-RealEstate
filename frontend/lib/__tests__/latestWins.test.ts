import { describe, expect, it } from "vitest";
import { latestWins } from "../latestWins";

describe("latestWins", () => {
  it("lets a lone request through", () => {
    const gate = latestWins();
    expect(gate.start()()).toBe(true);
  });

  it("silences an older request that finishes last", () => {
    // The failure this exists for: cancel a visit (request A), book one from
    // the matched listings (request B), B answers first, then A lands and puts
    // the pre-booking list back on screen.
    const gate = latestWins();
    const a = gate.start();
    const b = gate.start();
    expect(b()).toBe(true);
    expect(a()).toBe(false);
  });

  it("keeps letting the newest through however many are in flight", () => {
    const gate = latestWins();
    const claims = [gate.start(), gate.start(), gate.start(), gate.start()];
    expect(claims.slice(0, 3).map((c) => c())).toEqual([false, false, false]);
    expect(claims[3]()).toBe(true);
  });

  it("stays true for the newest across repeated checks", () => {
    // `.then`, `.catch` and `.finally` each ask separately, so the answer has
    // to be stable rather than consumed by the first caller.
    const gate = latestWins();
    const mine = gate.start();
    expect([mine(), mine(), mine()]).toEqual([true, true, true]);
  });

  it("gives each gate its own sequence", () => {
    // One per component instance, so opening a second lead cannot silence the
    // first one's pending request.
    const one = latestWins();
    const two = latestWins();
    const first = one.start();
    two.start();
    expect(first()).toBe(true);
  });
});

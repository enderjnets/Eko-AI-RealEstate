import { describe, expect, it } from "vitest";

import { needsFallbackJump, resultInView } from "../resultInView";

/** The phone the failure was measured on, and where the figure landed. */
const PHONE = { viewportHeight: 844, top: 1073 };

const ask = (over: Partial<Parameters<typeof resultInView>[0]> = {}) =>
  resultInView({
    alreadyDone: false,
    hasResult: true,
    focusedIsTextField: false,
    ...PHONE,
    ...over,
  });

describe("bringing the calculator's answer onto the screen", () => {
  it("scrolls when the figure is below the fold — the measured failure", () => {
    // 1,073px on an 844px screen: 229px past the edge, and the page does not
    // move on its own. Tap, tap, nothing.
    expect(ask()).toEqual({ scroll: true, spend: true });
  });

  it("leaves a figure that is already on screen alone", () => {
    // The wide layout puts the result beside the inputs, at 106px. Yanking the
    // scroll of somebody who can already see the answer is worse than nothing.
    expect(ask({ top: 106, viewportHeight: 900 })).toEqual({ scroll: false, spend: true });
  });

  it("does it once, not on every recalculation", () => {
    // Otherwise moving a slider to read the assumptions drags the page back.
    expect(ask({ alreadyDone: true })).toEqual({ scroll: false, spend: false });
  });

  it("does nothing before there is a figure", () => {
    expect(ask({ hasResult: false })).toEqual({ scroll: false, spend: false });
  });

  it("never pulls the page while someone is typing", () => {
    // The savings field sits ABOVE the result. Scrolling would take what they
    // are typing off the screen — the fix becoming a worse bug.
    expect(ask({ focusedIsTextField: true }).scroll).toBe(false);
  });

  it("keeps its one shot while a field has focus", () => {
    // The half a plain boolean would have lost. "Not now" is not "never": the
    // tap that blurs the field is exactly the moment this is for, and spending
    // the shot on a keystroke would mean the answer never arrives.
    expect(ask({ focusedIsTextField: true }).spend).toBe(false);
    expect(ask({ focusedIsTextField: false }).spend).toBe(true);
  });

  it("treats a figure exactly at the fold as off screen", () => {
    // `top === viewportHeight` is the first pixel nobody can see. An
    // off-by-one here is a result sitting one row below the edge, which is the
    // whole bug in miniature.
    expect(ask({ top: 844 }).scroll).toBe(true);
    expect(ask({ top: 843 }).scroll).toBe(false);
  });

  it("treats a figure scrolled above the viewport as off screen too", () => {
    // Negative `top` means it is behind them. Rare, but "visible" must mean
    // visible, not "not below".
    expect(ask({ top: -200 }).scroll).toBe(true);
  });
});

describe("when the smooth scroll never happens", () => {
  it("jumps if nothing moved at all", () => {
    // Measured on production, Chrome 152, prefers-reduced-motion false:
    // `scrollIntoView({ behavior: "smooth" })` left scrollY at 0 while the
    // same call with "auto" moved it 954px. Without this, the whole v0.102.8
    // fix is inert in that browser and the figure stays off screen.
    expect(needsFallbackJump(0, 0)).toBe(true);
    expect(needsFallbackJump(320, 320)).toBe(true);
  });

  it("leaves it alone once the page is moving", () => {
    // The smooth scroll is working: it begins on the first frame, so any
    // movement at all means the browser took the request.
    expect(needsFallbackJump(0, 40)).toBe(false);
    expect(needsFallbackJump(0, 954)).toBe(false);
  });

  it("counts movement in either direction as the person taking over", () => {
    // Somebody who grabbed the page in those few frames has answered the
    // question themselves. Yanking the view somewhere else is worse than the
    // off-screen figure this exists to fix.
    expect(needsFallbackJump(500, 460)).toBe(false);
  });

  it("treats a sub-pixel difference as not having moved", () => {
    // Fractional scroll positions are ordinary on a scaled display; a
    // rounding artefact is not a scroll.
    expect(needsFallbackJump(0, 0.4)).toBe(true);
  });
});

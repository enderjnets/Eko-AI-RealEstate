/**
 * Whether the calculator should bring its own answer onto the screen.
 *
 * Measured against production on a 390x844 phone, 15-sep-2026: tapping the two
 * presets leaves `window.scrollY` at 0 while the figure lands at 1,073px — 229
 * past the bottom of the screen. The page does not move, so as far as the
 * person holding the phone is concerned, nothing happened. The funnel agrees
 * from the other side: of 43 sessions on `/calculator` in 28 days, **32 never
 * scrolled at all**, and 27 of those 32 did interact. They tapped, nothing
 * visibly changed, and they left without seeing the number the video promised.
 *
 * The decision lives here rather than inside the effect because the effect
 * cannot be tested — this app has `vitest` and no DOM — and four conditions
 * that nothing checks are four conditions that drift.
 */
export interface InViewQuestion {
  /** Already done once this page load. Answering "did anything happen" is a
   *  one-time job; repeating it on every recalculation fights a person who has
   *  scrolled away to read the assumptions. */
  alreadyDone: boolean;
  /** There is a figure to show. Below the floor there is nothing to scroll to. */
  hasResult: boolean;
  /** A text field has focus. Someone typing their savings has that field ABOVE
   *  the result; scrolling would pull what they are typing off the screen.
   *  Tapping a preset blurs it, which is the path this exists for. */
  focusedIsTextField: boolean;
  /** The result's top edge, relative to the viewport. */
  top: number;
  /** The viewport's height. */
  viewportHeight: number;
}

export interface InViewAnswer {
  /** Scroll it into view. */
  scroll: boolean;
  /** Spend the one shot. False while a field has focus, so the next keystroke
   *  — or the tap that blurs it — gets another chance. This is the half that a
   *  single boolean return would have lost: "do not scroll now" and "never
   *  scroll again" are different answers. */
  spend: boolean;
}

export function resultInView(q: InViewQuestion): InViewAnswer {
  if (q.alreadyDone || !q.hasResult) return { scroll: false, spend: false };
  if (q.focusedIsTextField) return { scroll: false, spend: false };

  // Already on screen — on a wide layout the result sits beside the inputs.
  // Hijacking the scroll of somebody who can see the answer is worse than
  // doing nothing, but the question is settled either way.
  const visible = q.top >= 0 && q.top < q.viewportHeight;
  return { scroll: !visible, spend: true };
}

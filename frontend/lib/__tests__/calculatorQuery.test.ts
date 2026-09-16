import { describe, expect, it } from "vitest";

import { LIMITS } from "../calculator";
import { calculatorSeed } from "../calculatorQuery";

describe("what /calculator reads from the link that sent someone", () => {
  it("carries the figure the video actually promised", () => {
    // Pieces 47-51 say "$2,600 a month" and "$40,000 saved" out loud. The
    // whole point is that the page opens on that answer instead of asking for
    // it back.
    expect(calculatorSeed("?rent=2600&savings=40000")).toEqual({
      rent: "2600",
      savings: "40000",
    });
  });

  it("changes nothing when the link carries nothing", () => {
    // The 212 sessions measured so far arrived without parameters. None of
    // them may behave differently than they do today.
    expect(calculatorSeed("")).toEqual({});
    expect(calculatorSeed("?")).toEqual({});
    expect(calculatorSeed("?utm_source=youtube&utm_medium=social")).toEqual({});
  });

  it("ignores a rent that is not a usable number", () => {
    // A caption gets retyped by hand and a truncated or mangled parameter is
    // the ordinary case, not the exotic one. Anything unusable leaves the
    // field blank, which is the behaviour the page already has.
    expect(calculatorSeed("?rent=abc")).toEqual({});
    expect(calculatorSeed("?rent=")).toEqual({});
  });

  it("reads a negative rent the same way the field would, not as a rejection", () => {
    // Worth pinning rather than leaving to chance, because it surprised the
    // first version of this test. The page's own `dollars()` strips every
    // character that is not a digit or a dot, so typing "-500" into the rent
    // field gives $500 — and this does the same, on purpose. One rule for the
    // field and the link, in one place. The visitor sees $500 in a field they
    // can correct, which is a better failure than a blank page.
    expect(calculatorSeed("?rent=-500").rent).toBe("500");
  });

  it("treats zero as nothing, never as an answer", () => {
    // `Number("0")` is finite and would sail through a laxer guard. Zero rent
    // produces no result at all, and zero savings produces a floor price the
    // visitor never asked to see.
    expect(calculatorSeed("?rent=0&savings=0")).toEqual({});
  });

  it("strips the formatting a caption would naturally carry", () => {
    // "$2,600" is how the number appears in the video and in the caption. A
    // link written by hand will sometimes keep the dollar sign and the comma.
    expect(calculatorSeed("?rent=%242%2C600").rent).toBe("2600");
  });

  it("clamps to what the server would accept, rather than refusing", () => {
    // The same bound the page's own field applies, so the figure shown is one
    // the lead can actually be stored with.
    expect(calculatorSeed(`?rent=${LIMITS.rent * 10}`).rent).toBe(String(LIMITS.rent));
    expect(calculatorSeed(`?savings=${LIMITS.savings * 10}`).savings).toBe(
      String(LIMITS.savings),
    );
  });

  it("never supplies savings on its own", () => {
    // The deliberate half. A link with only rent must not conjure a savings
    // figure: the page reads a blank savings field as "not yet", and any
    // number here would be one nobody promised.
    expect(calculatorSeed("?rent=2600")).toEqual({ rent: "2600" });
    expect(calculatorSeed("?rent=2600")).not.toHaveProperty("savings");
  });

  it("accepts only the three credit bands the calculator has", () => {
    expect(calculatorSeed("?credit=excellent").credit).toBe("excellent");
    expect(calculatorSeed("?credit=good").credit).toBe("good");
    expect(calculatorSeed("?credit=fair").credit).toBe("fair");
    expect(calculatorSeed("?credit=perfect")).toEqual({});
    expect(calculatorSeed("?credit=GOOD")).toEqual({});
  });

  it("reads the money parameters past the tracking ones", () => {
    // The real link has both, because the same URL has to tell us which video
    // it was AND what that video promised.
    expect(
      calculatorSeed(
        "?rent=2600&savings=40000&utm_source=youtube&utm_medium=social&utm_content=p47",
      ),
    ).toEqual({ rent: "2600", savings: "40000" });
  });

  it("works on a query string given without its question mark", () => {
    // `window.location.search` includes the "?", but a caller passing the bare
    // string is the easy mistake and it costs nothing to survive it.
    expect(calculatorSeed("rent=2600").rent).toBe("2600");
  });
});

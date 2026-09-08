import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { NAME_FIELD_MAX, NAME_MAX, fullName } from "../leadName";

/**
 * The server's cap, read from the server, not copied into a literal here.
 * Same trick `backend/tests/test_calculator_copy.py` uses in the other
 * direction. Copied, a backend that lowered MAX_NAME to 120 would leave this
 * file green while both public forms started 422-ing.
 */
function serverMaxName(): number {
  const src = readFileSync(join(process.cwd(), "../backend/app/services/capture.py"), "utf8");
  const m = src.match(/^MAX_NAME\s*=\s*(\d+)/m);
  expect(m, "MAX_NAME not found in capture.py — this test proves nothing without it").not.toBeNull();
  return Number(m![1]);
}

/**
 * The joining rule, on its own, because it is the only part of the two-field
 * name a test in this repo can execute: vitest here has no DOM by choice
 * (`vitest.config.ts`), so nothing renders a form and asserts what it sends.
 * Keeping the rule in a function instead of inline in each form is what makes
 * this testable at all — and what keeps `/contact` and `ConsultForm` from
 * drifting.
 */
describe("fullName", () => {
  it("joins the two halves with a single space", () => {
    expect(fullName("Ana", "Pérez")).toBe("Ana Pérez");
  });

  it("trims each half BEFORE joining, so stray spaces never double up", () => {
    // The failure this prevents is not cosmetic: the joined string is what the
    // agent reads in the notice and in the Inbox row, exactly as stored.
    expect(fullName("  Ana ", " Pérez  ")).toBe("Ana Pérez");
  });

  it("returns just the half that was filled in", () => {
    expect(fullName("Ana", "")).toBe("Ana");
    expect(fullName("", "Pérez")).toBe("Pérez");
    expect(fullName("Ana", "   ")).toBe("Ana");
  });

  it("returns an empty string when neither was, which the caller sends as undefined", () => {
    // This is the case that matters for capture: `required` lives in the
    // markup only, because the same endpoint serves another tenant's forms.
    // A submission with no name at all — a bot, JS off — must still become a
    // lead. Empty here becomes `undefined` at the call site, never `" "`.
    expect(fullName("", "")).toBe("");
    expect(fullName("  ", "  ")).toBe("");
  });

  it("keeps a compound surname in one field intact", () => {
    expect(fullName("Ana", "Pérez de la Rosa")).toBe("Ana Pérez de la Rosa");
  });

  it("caps the pair below what the server actually accepts", () => {
    const serverCap = serverMaxName();
    expect(NAME_MAX).toBe(serverCap);
    const longest = fullName("a".repeat(NAME_FIELD_MAX), "b".repeat(NAME_FIELD_MAX));
    expect(longest.length).toBe(NAME_FIELD_MAX * 2 + 1);
    expect(longest.length).toBeLessThanOrEqual(serverCap);
  });

  it("truncates anything longer, because the server REJECTS instead of trimming", () => {
    // `maxLength` on the input stops typing, pasting and autofill — measured —
    // but not a password manager assigning `input.value` directly, and
    // `validity.tooLong` stays false there. `PublicLeadIn.name` has
    // `max_length=MAX_NAME`, which pydantic rejects: a 422 that takes the
    // email, the phone, the TCPA consent and the calculator snapshot with it.
    const huge = fullName("a".repeat(500), "b".repeat(500));
    expect(huge.length).toBe(serverMaxName());
  });
});

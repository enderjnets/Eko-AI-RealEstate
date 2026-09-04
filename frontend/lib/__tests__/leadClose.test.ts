/**
 * Closing a deal, read off the source.
 *
 * The API now refuses `{status: "won"}` on its own with a 422 — a closed deal
 * has to say what kind it was. The old button sent exactly that and swallowed
 * failures into a catch, so without these the regression is invisible: the
 * button looks like it works and nothing is ever recorded.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { WON_KINDS } from "../api";

const read = (p: string) => readFileSync(join(process.cwd(), p), "utf8");

describe("closing a deal", () => {
  it("the button opens the dialog instead of patching straight to won", () => {
    const src = read("components/leads/LeadDetail.tsx");
    expect(src).toContain("<CloseDealDialog");
    expect(src).not.toMatch(/patch\(lead\.id,\s*\{\s*status:\s*"won"\s*\}\)/);
  });

  it("the patch it does send carries the kind", () => {
    const src = read("components/leads/LeadDetail.tsx");
    expect(src).toContain("won_kind: kind");
  });

  it("the dialog cannot be confirmed without a kind", () => {
    const src = read("components/leads/CloseDealDialog.tsx");
    expect(src).toContain("disabled={!kind");
  });

  it("offers every kind the backend accepts, and no others", () => {
    // Reading the constant rather than a copy: a kind the UI offers that the
    // API refuses is a dead option, and one it accepts but never offers is a
    // column that stays empty.
    expect([...WON_KINDS]).toEqual([
      "listing_sold",
      "buyer_purchase",
      "rental",
      "referral",
      "other",
    ]);
    const src = read("components/leads/CloseDealDialog.tsx");
    expect(src).toContain("WON_KINDS.map");
  });
});

describe("did the appointment happen", () => {
  it("asks only about visits already in the past", () => {
    // "Did it happen?" about tomorrow is a question nobody can answer, and the
    // API answers 409 for a visit that is no longer standing.
    const src = read("components/calendar/VisitsSection.tsx");
    expect(src).toContain("isPast(v.scheduled_at)");
    expect(src).toContain('handleOutcome(v.id, "completed")');
    expect(src).toContain('handleOutcome(v.id, "no_show")');
  });
});

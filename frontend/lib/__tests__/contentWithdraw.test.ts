/**
 * The withdraw button: taking a piece off the calendar for good.
 *
 * Reject cannot do it. A rejection is read by the correction sweep, which
 * rewrites and re-renders the piece and brings it back for approval, and a
 * queued piece cannot be rejected at all. On 23-sep-2026 three repeated rent
 * pieces had to leave October: one was approved, two were queued.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(join(process.cwd(), p), "utf8");

function dict(name: "EN" | "ES"): Record<string, string> {
  const source = read("lib/i18n.tsx");
  const start = source.indexOf(`const ${name}: Record<string, string> = {`);
  const body = source.slice(start, source.indexOf("\n};", start));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/^ {2}"([^"]+)": "((?:[^"\\]|\\.)*)"/gm)) {
    out[m[1]] = m[2];
  }
  return out;
}

const EN = dict("EN");
const ES = dict("ES");
const queue = read("components/content/ContentQueue.tsx");

describe("the withdraw button", () => {
  it("calls its own endpoint, not reject", () => {
    expect(read("lib/api.ts")).toMatch(
      /withdraw: \(id: number\) =>\s*api<ContentPiece>\(`\/v1\/content\/\$\{id\}\/withdraw`, \{\s*method: "POST"/,
    );
  });

  it("is labelled in both languages", () => {
    for (const key of ["content.withdraw", "content.withdrawConfirm", "content.withdrawHint"]) {
      expect(EN[key], key).toBeTruthy();
      expect(ES[key], key).toBeTruthy();
    }
    expect(ES["content.withdraw"]).toBe("Retirar");
  });

  it("says the piece does not come back, which is what separates it from reject", () => {
    expect(EN["content.withdrawHint"]).toMatch(/not .*rewritten|won't come back|will not come back/i);
    expect(ES["content.withdrawHint"]).toMatch(/no vuelve|no se reescribe/i);
  });

  it("is offered on a queued piece, the case reject refuses", () => {
    const block = queue.slice(queue.indexOf("canWithdraw"), queue.indexOf("canWithdraw") + 400);
    expect(block).toMatch(/"publishing"/);
    expect(block).not.toMatch(/"published"/);
    expect(queue).toContain('t("content.withdraw")');
  });
});

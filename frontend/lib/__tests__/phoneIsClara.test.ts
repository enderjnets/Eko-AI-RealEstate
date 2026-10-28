import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// The landing phone rings Clara, the VAPI assistant, not Natalia or Robbie.
// Until 28-oct-2026 /start said "Call now and reach a real person" and the home
// page "no assistant screening you" — on the one line where an assistant answers.
// Read as text, like landingHero.test.ts: the dictionaries are not exported.
const source = readFileSync(join(__dirname, "..", "i18n.tsx"), "utf8");

function value(key: string): string[] {
  const out: string[] = [];
  const re = new RegExp(`"${key.replace(/\./g, "\\.")}":\\s*"((?:[^"\\\\]|\\\\.)*)"`, "g");
  for (const m of source.matchAll(re)) out.push(m[1]);
  return out;
}

describe("the phone copy says who answers", () => {
  it("never promises a person on the line Clara answers", () => {
    const promise = /real person|you'll get a person|assistant screening|persona real|te atiende una persona|asistente que te filtre|contestan las mismas dos personas|the same two people answer/i;
    expect(source).not.toMatch(promise);
  });

  it("names the AI assistant wherever the call is offered, in both languages", () => {
    for (const key of ["start.talk.phoneBody", "landing.reach.body", "landing.form.thanksBody"]) {
      const both = value(key);
      expect(both, key).toHaveLength(2);
      expect(both[0], key).toMatch(/AI assistant/);
      expect(both[1], key).toMatch(/asistente con IA/);
    }
  });
});

/**
 * What the rebuild button promises about money.
 *
 * The hint used to say "the pictures are reused", and that was true of one
 * renderer. Since 10-sep-2026 this agency's render machine runs a different
 * engine, which builds from its own pipeline and pays for the pictures again —
 * measured on 12-sep: two Kling and two Pexels clips for one short.
 *
 * The page cannot tell which engine will run: it is an environment variable on
 * the render machine, and the claim call only carries the worker's name. So the
 * only honest wording is the expensive one. A tooltip that understates a charge
 * is worse than no tooltip, because somebody clicks on the strength of it.
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
    out[m[1]] = m[2].replace(/\\u([0-9a-fA-F]{4})/g, (_s, h) =>
      String.fromCharCode(parseInt(h, 16)),
    );
  }
  return out;
}

const EN = dict("EN");
const ES = dict("ES");

describe("the rebuild button's hint", () => {
  it("never promises the pictures come back free", () => {
    // The exact claim that was false. Matched on the idea rather than the old
    // sentence, so a reworded version of the same promise still fails.
    expect(EN["content.rebuildHint"]).not.toMatch(/pictures are reused|reuses the pictures/i);
    expect(ES["content.rebuildHint"]).not.toMatch(/im[áa]genes se reutilizan|reutiliza las im[áa]genes/i);
  });

  it("says the pictures usually cost too, in both languages", () => {
    // Not just "does not lie": it has to carry the warning. Deleting the
    // sentence altogether would pass the test above and leave the person with
    // no idea what the click costs.
    expect(EN["content.rebuildHint"]).toMatch(/usually the pictures/i);
    expect(ES["content.rebuildHint"]).toMatch(/tambi[ée]n las im[áa]genes/i);
  });

  it("still names the narration, which is the cost that is certain", () => {
    expect(EN["content.rebuildHint"]).toMatch(/narration/i);
    expect(ES["content.rebuildHint"]).toMatch(/narraci[óo]n/i);
  });

  it("is the text the button actually shows", () => {
    // A key nobody renders is a key that can say anything. This is the line
    // that ties the three assertions above to something a person sees.
    expect(read("components/content/ContentQueue.tsx")).toContain(
      't("content.rebuildHint")',
    );
  });
});

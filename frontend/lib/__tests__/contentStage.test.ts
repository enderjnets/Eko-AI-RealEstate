/**
 * Every render stage the worker reports has words in both languages.
 *
 * The console builds the key at run time — `content.stage.${stage}` — so the
 * parity test, which only sees literal `t("…")` calls, cannot catch a missing
 * one. On 23-sep-2026 the BitTrader engine reported "bittrader" and the card
 * read "content.stage.bittrader" for the whole eleven minutes of the render.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND = join(__dirname, "..", "..");
const WORKER = join(FRONTEND, "..", "worker");
const i18n = readFileSync(join(FRONTEND, "lib", "i18n.tsx"), "utf8");
const queue = readFileSync(join(FRONTEND, "components", "content", "ContentQueue.tsx"), "utf8");

function dictKeys(name: "EN" | "ES"): Set<string> {
  const start = i18n.indexOf(`const ${name}: Record<string, string> = {`);
  const body = i18n.slice(start, i18n.indexOf("\n};", start));
  return new Set([...body.matchAll(/^\s{2}"([^"]+)":/gm)].map((m) => m[1]));
}

// The three shapes a stage is reported in: `say("x", …)` in the in-house
// producer, `_say(report, "x", …)` in the BitTrader one, and
// `panel.progress(job["id"], "x", …)` in the loop that uploads the result.
const REPORTED = [
  /\bsay\(\s*"([a-z_]+)"/g,
  /\b_say\(\s*report,\s*"([a-z_]+)"/g,
  /\bprogress\(\s*job\["id"\],\s*"([a-z_]+)"/g,
];

function reportedStages(): Set<string> {
  const stages = new Set<string>();
  for (const file of readdirSync(WORKER).filter((f) => f.endsWith(".py"))) {
    const text = readFileSync(join(WORKER, file), "utf8");
    for (const pattern of REPORTED) {
      for (const m of text.matchAll(pattern)) stages.add(m[1]);
    }
  }
  return stages;
}

describe("render stages", () => {
  const stages = reportedStages();

  it("are read from the worker — otherwise this test proves nothing", () => {
    expect(stages).toContain("narrating");
    expect(stages).toContain("bittrader");
    expect(stages).toContain("finishing");
  });

  it("each have a label in English and in Spanish", () => {
    const en = dictKeys("EN");
    const es = dictKeys("ES");
    const missing = [...stages]
      .flatMap((s) => [
        en.has(`content.stage.${s}`) ? null : `EN content.stage.${s}`,
        es.has(`content.stage.${s}`) ? null : `ES content.stage.${s}`,
      ])
      .filter(Boolean);
    expect(missing).toEqual([]);
  });

  it("fall back to the generic line when the worker is newer than the console", () => {
    // The worker ships to the ROG on its own schedule, so a stage this build
    // has never heard of is a normal state, not a bug to render as a key.
    const block = queue.slice(queue.indexOf("function RenderProgress"), queue.indexOf("function PieceCard"));
    expect(block).toMatch(/!==\s*stageKey/);
    expect(block).toContain('t("content.awaitingVideo")');
  });
});

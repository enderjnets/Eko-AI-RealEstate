/**
 * What the console has to say about a correction, and about a standing rule.
 *
 * Two different failures are being guarded here.
 *
 * A piece the reviewer already rejected comes back into the queue looking like
 * a new one. Saying nothing is how somebody approves the same defect twice —
 * but saying "Regenerated after your rejection" is worse when the action was
 * `manual`, `given_up` or `superseded`, because in three of the six cases
 * nothing was regenerated at all.
 *
 * And a lesson is prepended to EVERY future draft. A complaint about one piece
 * ("repeats the days-on-market explanation already published in piece 10")
 * becomes a permanent instruction, and without this panel nothing anywhere
 * would say why the drafts changed. The piece it came from is on screen for
 * the same reason: it is what tells a person whether it was a rule or a
 * one-off.
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
const QUEUE = read("components/content/ContentQueue.tsx");
const API = read("lib/api.ts");

/** Every action the sweep can record, mirrored from `REJECTION_ACTIONS`. */
const ACTIONS = [
  "rebuild",
  "rematerialise",
  "rewrite",
  "manual",
  "given_up",
  "superseded",
];

describe("the correction line on a card", () => {
  it("has a sentence for every action the sweep can take, in both languages", () => {
    for (const action of ACTIONS) {
      const key = `content.correction.${action}`;
      expect(EN[key], `${key} missing from EN`).toBeTruthy();
      expect(ES[key], `${key} missing from ES`).toBeTruthy();
    }
  });

  it("does not claim a new video for the actions that made none", () => {
    // `manual`, `given_up` and `superseded` regenerate nothing. A line saying
    // otherwise sends somebody looking for a video that was never made.
    for (const action of ["manual", "given_up", "superseded"]) {
      expect(EN[`content.correction.${action}`]).not.toMatch(
        /made again|regenerated|rebuilt|written again/i,
      );
      expect(ES[`content.correction.${action}`]).not.toMatch(
        /volvió a montar|se rehizo|se escribió otra vez/i,
      );
    }
  });

  it("picks the sentence from the action rather than hard-coding one", () => {
    expect(QUEUE).toMatch(/t\(`content\.correction\.\$\{piece\.correction\.action\}`\)/);
  });

  it("is not hidden on the pieces that stayed rejected", () => {
    // `manual`, `given_up` and a superseded hand-edit all LEAVE the piece
    // rejected. Scoping the line to the other statuses hid it in exactly the
    // two cases where it is the only signal there is, and two of the six
    // sentences could never render at all. Checking that the six keys exist
    // does not catch that — the scope is what has to be asserted.
    const block = QUEUE.slice(
      QUEUE.indexOf("{piece.correction?.action"),
      QUEUE.indexOf("{rejecting ?"),
    );
    expect(block.length).toBeGreaterThan(0);
    expect(block).not.toMatch(/piece\.correction\?\.action && piece\.status !== "rejected"/);
    // The reason is dropped there instead, because the red line carries it.
    expect(block).toMatch(/piece\.status !== "rejected" && \(/);
  });

  it("never prints `finding`, which is a dictionary", () => {
    expect(QUEUE).not.toMatch(/correction\.finding/);
  });

  it("carries the whole correction shape from the backend", () => {
    // Scoped to the interface BODY. Searching the whole file for "  reason"
    // finds the same two-space-indented name in other interfaces, so the
    // assertion could not fail even if this one lost every field.
    const start = API.indexOf("export interface ContentCorrection {");
    expect(start).toBeGreaterThan(-1);
    const body = API.slice(start, API.indexOf("\n}", start));
    for (const field of ["reason", "category", "finding", "action"]) {
      expect(body, `${field} missing from ContentCorrection`).toContain(`${field}:`);
    }
  });
});

describe("the lessons panel", () => {
  it("says what a lesson does, in both languages", () => {
    for (const key of [
      "content.lessons.title",
      "content.lessons.hint",
      "content.lessons.from",
      "content.lessons.forget",
    ]) {
      expect(EN[key], `${key} missing from EN`).toBeTruthy();
      expect(ES[key], `${key} missing from ES`).toBeTruthy();
    }
    // The hint has to say the thing that makes this screen worth having: each
    // line goes into every future draft.
    expect(EN["content.lessons.hint"]).toMatch(/every new draft/i);
    expect(ES["content.lessons.hint"]).toMatch(/todos los borradores nuevos/i);
  });

  it("shows which piece a lesson came from", () => {
    expect(QUEUE).toMatch(/lesson\.source_piece_id/);
    expect(QUEUE).toMatch(/content\.lessons\.from/);
  });

  it("offers a way to take one back, and hides it from a viewer", () => {
    expect(QUEUE).toMatch(/contentApi\.forgetLesson\(lesson\.id\)/);
    expect(QUEUE).toMatch(/!readOnly && \(\s*<button/);
  });

  it("renders the text as text, never as markup", () => {
    // React escapes by default; what this forbids is somebody reaching for the
    // escape hatch on a field a person types.
    expect(QUEUE).not.toMatch(/dangerouslySetInnerHTML/);
  });

  it("does not empty the queue when its own request fails", () => {
    // The queue is the job. A lessons endpoint that 500s must leave the person
    // looking at their pieces, not at an error.
    expect(QUEUE).toMatch(/catch \{\s*setLessons\(\[\]\);/);
  });

  it("is wired into the queue and not merely defined", () => {
    expect(QUEUE).toMatch(/<Lessons readOnly=\{readOnly\} \/>/);
  });
});

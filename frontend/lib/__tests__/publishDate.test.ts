/**
 * The publish date on the card.
 *
 * Cheesman Park was cut for Halloween and approved on 11-oct-2026; with no way
 * to say "not before the 29th" it was queued for that same evening.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  canSetPublishDate,
  formatPublishDate,
  todayIn,
  waitsForItsDate,
} from "@/lib/publishDate";

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

describe("today, in the agency's zone", () => {
  it("is Denver's date, not the browser's or UTC's", () => {
    // 03:00 UTC on the 12th is still the evening of the 11th in Denver.
    const late = new Date("2026-10-12T03:00:00Z");
    expect(todayIn("America/Denver", late)).toBe("2026-10-11");
    expect(todayIn("UTC", late)).toBe("2026-10-12");
  });
});

describe("a dated piece", () => {
  it("waits only while its day is ahead", () => {
    expect(waitsForItsDate({ publish_window_start: "2026-10-29" }, "2026-10-11")).toBe(true);
    expect(waitsForItsDate({ publish_window_start: "2026-10-11" }, "2026-10-11")).toBe(false);
    expect(waitsForItsDate({ publish_window_start: null }, "2026-10-11")).toBe(false);
  });

  it("can be dated in every status but published, like the server", () => {
    expect(canSetPublishDate({ status: "publishing" })).toBe(true);
    expect(canSetPublishDate({ status: "approved" })).toBe(true);
    expect(canSetPublishDate({ status: "failed" })).toBe(true);
    expect(canSetPublishDate({ status: "published" })).toBe(false);
  });

  it("shows the calendar day it holds, never the day before", () => {
    // new Date("2026-10-29") is UTC midnight: the 28th in Denver.
    const en = formatPublishDate("2026-10-29", "en");
    expect(en).toContain("29");
    expect(en).not.toContain("28");
    expect(formatPublishDate("2026-10-29", "es")).toContain("29");
  });
});

describe("the wiring", () => {
  it("calls its own route with PUT, not the text edit", () => {
    expect(read("lib/api.ts")).toMatch(
      /setPublishDate: \(id: number, publishDate: string \| null\) =>\s*api<ContentPiece>\(`\/v1\/content\/\$\{id\}\/publish-date`, \{\s*method: "PUT"/,
    );
  });

  it("sits outside the text editor, so a queued piece can be dated", () => {
    const queue = read("components/content/ContentQueue.tsx");
    expect(queue).toContain("<PublishDate piece={piece} studio={studio} busy={busy} onSave={onSetPublishDate} />");
    expect(queue).toContain('t("content.publishWaits"');
  });

  it("is labelled in both languages", () => {
    const EN = dict("EN");
    const ES = dict("ES");
    for (const key of [
      "content.publishDate",
      "content.publishDateNone",
      "content.publishDateChange",
      "content.publishDateSave",
      "content.publishDateClear",
      "content.publishDateHint",
      "content.publishWaits",
    ]) {
      expect(EN[key], key).toBeTruthy();
      expect(ES[key], key).toBeTruthy();
    }
    expect(EN["content.publishWaits"]).toContain("{date}");
    expect(ES["content.publishWaits"]).toContain("{date}");
  });
});

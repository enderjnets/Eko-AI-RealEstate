/**
 * The analytics page, read off the source.
 *
 * These are not about layout. Each one guards a claim that, if it broke, would
 * still render a page that looks fine — which is the only kind of defect a
 * dashboard has. A number under the wrong caption is worse than a missing
 * number, because decisions get made on it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(join(process.cwd(), p), "utf8");

/**
 * The dictionaries are read out of the source, the same way `i18nParity` does
 * it: they are module-private on purpose, and exporting them just so a test can
 * see them would widen the surface for the sake of the test.
 */
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
const view = () => read("components/analytics/AnalyticsView.tsx");

describe("what the page promises", () => {
  it("calls the content card association and never attribution", () => {
    // A Shorts link is not clickable and Instagram strips the referrer, so
    // these visits are *followed by* the video, not *caused by* it as far as
    // anyone can prove. The word is the whole honesty of the section.
    for (const dict of [EN, ES]) {
      const hint = dict["analytics.contentHint"].toLowerCase();
      expect(hint).toMatch(/associat|asociaci/);
      // The word "attribution" may appear, but only to deny it. Anywhere else
      // in this sentence it would be claiming exactly what cannot be proven.
      for (const m of hint.matchAll(/attribution|atribuci\u00f3n/g)) {
        expect(hint.slice(Math.max(0, m.index - 5), m.index)).toMatch(/not |no /);
      }
    }
    expect(read("components/analytics/ContentTable.tsx")).toContain("analytics.assoc48");
  });

  it("says an internal note is not a reply, where the number is shown", () => {
    for (const dict of [EN, ES]) {
      expect(dict["analytics.whoAnswersHint"].toLowerCase()).toMatch(/internal|interna/);
    }
  });

  it("shows the timezone next to the range", () => {
    // Every day on this page is cut at the office's midnight. A reader in
    // another zone has no way to know that unless it is written down.
    expect(read("components/analytics/RangePicker.tsx")).toContain("timezone");
  });

  it("names the fallback reply as a held line, not as the agent", () => {
    // Folded into "the agent" it would hide an outage behind a healthy-looking
    // response time — which is what the canned reply exists to survive.
    expect(EN["replyKind.fallback"]).toMatch(/held line/i);
    expect(ES["replyKind.fallback"]).toMatch(/enlatada/i);
  });

  it("distinguishes a lead that never touched the web from a direct visit", () => {
    expect(EN["source.no_web"]).not.toBe(EN["source.direct"]);
    expect(ES["source.no_web"]).not.toBe(ES["source.direct"]);
  });

  it("every funnel stage has a caption in both languages", () => {
    // A stage rendered as `analytics.stage.called_back` is a page that looks
    // broken to the person it was built for.
    const stages = [
      "sessions",
      "engaged",
      "cta",
      "leads",
      "contacted",
      "called_back",
      "appointment_set",
      "appointment_held",
      "won",
    ];
    for (const stage of stages) {
      expect(EN[`analytics.stage.${stage}`], stage).toBeTruthy();
      expect(ES[`analytics.stage.${stage}`], stage).toBeTruthy();
    }
  });

  it("draws its own bars instead of pulling in a charting library", () => {
    const pkg = JSON.parse(read("package.json"));
    const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(deps.filter((d) => /recharts|chart\.js|victory|nivo|d3/.test(d))).toEqual([]);
  });

  it("asks the API for the range the person picked", () => {
    // Written across two lines by the formatter, so match the call and its
    // argument separately rather than a brittle single string.
    expect(view()).toContain("analyticsApi");
    expect(view()).toContain(".get({ range: r })");
  });
});

describe("the lead timeline", () => {
  it("is mounted on the lead page", () => {
    expect(read("components/leads/LeadDetail.tsx")).toContain("<LeadTimeline");
  });

  it("reads oldest first", () => {
    // The calls list beside it runs newest first because it is a worklist.
    // This is a story, and a story that runs backwards is read once and never
    // again.
    expect(read("components/leads/LeadTimeline.tsx")).toMatch(/oldest first/i);
  });
});

describe("reaching the page at all", () => {
  it("is in the desktop bar below 1536px", () => {
    // It used to live in the "More" menu under `2xl`, so on any normal laptop
    // the page existed and nobody could find it.
    expect(read("components/ui/Nav.tsx")).not.toContain("2xl:inline-flex");
  });
});

describe("view counts, and where they came from", () => {
  const table = () => read("components/analytics/ContentTable.tsx");
  const api = () => read("lib/api.ts");

  it("keeps views apart from the association numbers", () => {
    // The distinction the whole card rests on: views is the platform's own
    // counter — a measurement — while sessions and leads in the 48 hours after
    // are only association. Folding them into one figure would launder one into
    // the other, and a number with the wrong standing is worse than none.
    const source = table();
    expect(source).toContain("r.association.sessions");
    expect(source).toContain("row.views?.count");
    expect(source).not.toMatch(/association\.sessions \+/);
  });

  it("says whether a number was read or typed", () => {
    // TikTok and Instagram hand view counts to nobody without a reviewed
    // first-party app, so those are typed by a person. A column that showed
    // both alike would let an estimate be read as a measurement.
    expect(table()).toContain("analytics.viewsTyped");
    expect(table()).toContain("analytics.viewsRead");
    for (const dict of [EN, ES]) {
      expect(dict["analytics.viewsTyped"]).toBeTruthy();
      expect(dict["analytics.viewsRead"]).toBeTruthy();
      expect(dict["analytics.viewsTyped"]).not.toBe(dict["analytics.viewsRead"]);
    }
  });

  it("offers the pencil only where no machine can read the number", () => {
    const source = table();
    expect(source).toContain('TYPED_BY_HAND = new Set(["tiktok", "instagram"])');
    expect(source).toContain("TYPED_BY_HAND.has(row.platform)");
  });

  it("never renders a missing reading as zero", () => {
    // A zero says the video was seen by nobody. "No reading" says we have not
    // looked. They are opposite facts and the second one is the true one.
    const source = table();
    expect(source).toContain("count === null");
    expect(source).toContain("analytics.noViews");
  });

  it("never turns an empty box into a zero", () => {
    // Opening the editor and clicking away fires onBlur, and Number("") is 0.
    // Saving that would write "seen by nobody" — the one claim this card is
    // built to avoid making by accident.
    expect(table()).toContain('value.trim() === ""');
  });

  it("sends the typed count to the publication's own route", () => {
    expect(api()).toContain(
      "`/v1/content/${id}/publications/${platform}/metrics`",
    );
    expect(api()).toMatch(/setMetrics[\s\S]{0,400}method: "PUT"/);
  });
});

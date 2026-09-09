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
    expect(source).toContain("after.sessions");
    expect(source).toContain("row.views?.count");
    expect(source).not.toMatch(/association\.sessions \+/);
    expect(source).not.toMatch(/after\.sessions \+/);
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

describe("the card names the video", () => {
  const table = () => read("components/analytics/ContentTable.tsx");

  it("identifies a row by the video's title, not by a piece id", () => {
    // `#41 · YouTube` is not something anybody recognises, and the owner reads
    // this card to decide what to make more of.
    const source = table();
    expect(source).toContain("groupByPiece(");
    // The title the card renders is the one the grouping computed, not a
    // second call that could drift from it.
    // The title comes from the grouping and only from there: a second call
    // here would be a copy that can drift from the one the test pins.
    expect(source).toContain("{video.title}");
    expect(source).not.toContain("videoTitle(");
    expect(read("lib/videosByPiece.ts")).toContain("videoTitle(");
  });

  it("keeps the whole title reachable even though the card clips it", () => {
    // `line-clamp-2` is a truncation: a 300-character hook loses its tail with
    // no way back unless the full string is carried somewhere.
    expect(table()).toContain("title={video.title}");
  });

  it("shows the hour in the agency's zone, not the reader's", () => {
    // The three platforms post the same video half a day apart, and every
    // number on the line is counted from the moment shown beside it. The old
    // `toLocaleDateString` had no timezone and no time of day at all, so it
    // read as one date for three different publications.
    const source = table();
    expect(source).toMatch(/exactTime\([^)]*timezone\)/);
    expect(source).not.toContain("toLocaleDateString");
    // Named on the ContentTable element itself: the range picker is handed the
    // same value two hundred lines up, so merely finding the string in the file
    // would still pass with the card's prop deleted.
    expect(view()).toMatch(/<ContentTable[^>]*timezone=\{data\.range\.timezone\}/);
  });

  it("links to the post, in a new tab that cannot reach back", () => {
    // `external_url` was already in the payload and simply never rendered.
    // `rel` is not decoration: without it the opened tab can rewrite this one.
    const source = table();
    expect(source).toContain("href={r.external_url}");
    expect(source).toContain('rel="noopener noreferrer"');
    expect(source).toContain("content.watchOn");
  });

  it("says so when a post has no link rather than showing nothing", () => {
    expect(table()).toContain("analytics.noLink");
    for (const dict of [EN, ES]) expect(dict["analytics.noLink"]).toBeTruthy();
  });

  it("labels the two 48h numbers instead of printing a bare pair", () => {
    // They used to render as "1 · 0", which needs the caption to be read and
    // then remembered in the right order.
    const source = table();
    expect(source).toContain("analytics.visitsAfter");
    expect(source).toContain("analytics.leadsAfter");
    for (const dict of [EN, ES]) {
      expect(dict["analytics.visitsAfter"]).toBeTruthy();
      expect(dict["analytics.leadsAfter"]).toBeTruthy();
      expect(dict["analytics.visitsAfter"]).not.toBe(dict["analytics.leadsAfter"]);
    }
  });

  it("carries the title and the publication id from the server", () => {
    expect(read("lib/api.ts")).toMatch(/publication_id: number;[\s\S]{0,200}hook: string \| null;/);
  });
});

describe("one 48h figure per video", () => {
  const table = () => read("components/analytics/ContentTable.tsx");

  it("reads the association once per video, above the platform lines", () => {
    // The server counts the union of the video's windows and stamps the same
    // block on every row. Rendered per platform line it read as three times
    // the people; rendered per row it also invited adding the rows up.
    const source = table();
    const reads = [...source.matchAll(/\.association\b/g)];
    expect(reads.map((m) => m.index)).toHaveLength(1);
    expect(source).toContain("video.rows[0].association");
    expect(reads[0].index).toBeLessThan(source.indexOf("video.rows.map("));
    // The tag names the piece, not the post: once per video as well.
    expect([...source.matchAll(/\.leads_tagged\b/g)]).toHaveLength(1);
    expect(source.indexOf(".leads_tagged")).toBeLessThan(source.indexOf("video.rows.map("));
  });

  it("says the window is counted from each post, in both languages", () => {
    // The figure spans the union of every post's 48 hours, so "48h after"
    // alone would understate it for a video posted three times.
    for (const dict of [EN, ES]) {
      expect(dict["analytics.assoc48"].toLowerCase()).toMatch(/each post|cada publicaci/);
    }
  });

  it("keeps platform and hour on one line and the link on the next", () => {
    // At 390px the old single wrapping line broke into three, with the link
    // landing wherever the break fell. The hour's span now closes its line
    // before the link block opens.
    expect(table()).toMatch(/exactTime\([^)]*\)\}\s*<\/span>\s*<\/div>/);
  });
});

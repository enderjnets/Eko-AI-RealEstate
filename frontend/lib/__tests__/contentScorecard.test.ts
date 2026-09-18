/**
 * The content scorecard, rendered — what it says and what it refuses to say.
 *
 * The card was rewritten on 18-sep-2026 because it was the only section of
 * `/analytics` with no ceiling. Every post printed twelve numbers and every one
 * of the nine exact-attribution stages spelled out its own caption, so a video
 * on three platforms cost thirty-six numbers and twenty-seven captions — and in
 * production all twenty-seven are zero. Published daily, in half a column, the
 * page grew by a screen a day.
 *
 * These tests are about the arithmetic and the ink, not the layout: that the
 * nine names are said once, that a funnel of zeros costs one sentence, that
 * exact attribution adds across a video's platforms and the 48-hour association
 * never does, and that the list stops.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ContentTable } from "@/components/analytics/ContentTable";
import { type Analytics, type ContentAttribution } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

Object.assign(globalThis, { React });

const ZERO: ContentAttribution = {
  sessions: 0,
  engaged: 0,
  cta_clickers: 0,
  contact_intents: 0,
  form_starts: 0,
  form_submits: 0,
  leads: 0,
  appointments_set: 0,
  appointments_held: 0,
};

type Row = Analytics["content"][number];

function row(over: Partial<Row> & Pick<Row, "piece_id" | "publication_id" | "platform">): Row {
  return {
    hook: `Video ${over.piece_id}`,
    published_at: "2026-09-18T18:30:00Z",
    external_url: null,
    association: { window_hours: 48, sessions: 0, leads: 0 },
    leads_tagged: 0,
    attribution: ZERO,
    latest_metrics: null,
    views: null,
    ...over,
  } as Row;
}

/** The markup as a person reads it: tags gone, whitespace collapsed. */
function text(rows: Row[]): string {
  const html = renderToStaticMarkup(
    React.createElement(
      LanguageProvider,
      null,
      React.createElement(ContentTable, { rows, timezone: "America/Denver" }),
    ),
  );
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

/** The markup itself, because a heading's full name lives in an attribute. */
function markup(rows: Row[]): string {
  return renderToStaticMarkup(
    React.createElement(
      LanguageProvider,
      null,
      React.createElement(ContentTable, { rows, timezone: "America/Denver" }),
    ),
  );
}

const occurrences = (haystack: string, needle: string) =>
  haystack.split(needle).length - 1;

const threePosts = [
  row({ piece_id: 41, publication_id: 1, platform: "youtube" }),
  row({ piece_id: 41, publication_id: 2, platform: "instagram" }),
  row({ piece_id: 41, publication_id: 3, platform: "tiktok" }),
];

/** One video, one post, one stage off zero — production has never had one. */
const oneThatMoved = [
  row({
    piece_id: 41,
    publication_id: 1,
    platform: "youtube",
    attribution: { ...ZERO, sessions: 9, form_starts: 2 },
  }),
];

describe("the nine stage names are said once, not once per post", () => {
  it("gives the video one heading row however many posts it has", () => {
    // The whole reason for the rewrite. Before, each of the three posts carried
    // its own captioned copy of all nine — twenty-seven captions for one video,
    // every value a zero. One heading row now serves the video.
    //
    // Asserted on the heading attribute rather than on the bare name: the name
    // is allowed to appear in prose (the phone, below, spells out a stage that
    // moved), and a test that counted every appearance would be pinning the
    // wrong thing and would go red for a change that is not a regression.
    for (const rows of [threePosts, oneThatMoved]) {
      const html = markup(rows);
      expect(occurrences(html, 'title="Visitors choosing a next step"')).toBe(1);
      expect(occurrences(html, 'title="Appointments held"')).toBe(1);
    }
  });

  it("spends no caption at all on a stage that is zero", () => {
    // The twenty-seven captions were all attached to zeros. With nothing moved,
    // each name appears once — in its heading — and nowhere else.
    const html = markup(threePosts);
    expect(occurrences(html, "Visitors choosing a next step")).toBe(1);
    expect(occurrences(html, "Appointments held")).toBe(1);
  });

  it("names a stage that moved, on the phone, where nine columns do not fit", () => {
    // The fallback under `sm`: the stages that moved, said in full, and a count
    // of the ones that did not — rather than nine columns squeezed into 390px
    // or nine captioned zeros brought back.
    const read = text(oneThatMoved);
    expect(read).toContain("Visits 9 · Forms started 2");
    expect(read).toContain("the other 7 stages are zero");
  });

  it("still offers all nine under their real names, none dropped or renamed", () => {
    // Shorter is only allowed to be shorter on screen. The full caption is the
    // one the dictionaries carry and it stays reachable on every heading.
    const html = markup(threePosts);
    for (const name of [
      "Visits",
      "Engaged visits",
      "Visitors choosing a next step",
      "Contact intent",
      "Forms started",
      "Forms sent",
      "Leads",
      "Appointments set",
      "Appointments held",
    ]) {
      expect(html, name).toContain(`title="${name}"`);
    }
  });

  it("says a funnel of zeros in a sentence instead of nine captioned zeros", () => {
    expect(text(threePosts)).toContain("No tagged visit yet");
  });
});

describe("what may be added up and what may not", () => {
  /**
   * TWO videos, summing to different numbers, on purpose.
   *
   * The first draft of this used one video, and passed with the per-video sum
   * deleted — because the card's top strip adds the same rows up for its own
   * total, and with a single video the two figures are the same string. The
   * test was green for the wrong reason. With 6/1 on one video, 4/0 on the
   * other and 10/1 across both, no one figure can stand in for another.
   */
  const spread = [
    row({
      piece_id: 41,
      publication_id: 1,
      platform: "youtube",
      attribution: { ...ZERO, sessions: 1 },
      association: { window_hours: 48, sessions: 5, leads: 2 },
    }),
    row({
      piece_id: 41,
      publication_id: 2,
      platform: "instagram",
      attribution: { ...ZERO, sessions: 2 },
      association: { window_hours: 48, sessions: 5, leads: 2 },
    }),
    row({
      piece_id: 41,
      publication_id: 3,
      platform: "tiktok",
      attribution: { ...ZERO, sessions: 3, leads: 1 },
      association: { window_hours: 48, sessions: 5, leads: 2 },
    }),
    row({
      piece_id: 40,
      publication_id: 4,
      platform: "youtube",
      published_at: "2026-09-16T18:30:00Z",
      attribution: { ...ZERO, sessions: 4 },
      association: { window_hours: 48, sessions: 3, leads: 0 },
    }),
  ];

  it("adds exact attribution across a video's platforms", () => {
    // Safe, and only here: the server groups the exact half by (piece,
    // platform) on the session's own `utm_content` and `source`, and a session
    // — like a lead's first touch — has exactly one source. The platforms of
    // one video are disjoint, so 1 + 2 + 3 is three different people.
    const read = text(spread);
    expect(read).toContain("6 visits · 1 leads");
    expect(read).toContain("4 visits · 0 leads");
  });

  it("adds the same way across every video for the card's own total", () => {
    // The strip above the list answers "did any tagged link do anything at
    // all", which is the question the owner opens this card with.
    expect(text(spread)).toContain("10 visits · 1 leads");
  });

  it("never multiplies the 48-hour association by the number of posts", () => {
    // The server stamps the same block on every row of the video: it already
    // counted the union of the three windows once. Adding the rows up is how a
    // number of people that never existed gets onto the page — 15 here.
    const read = text(spread);
    expect(read).toContain("5 visits");
    expect(read).not.toContain("15 visits");
    expect(read).not.toContain("6 leads");
  });
});

describe("the list stops", () => {
  const many = Array.from({ length: 7 }, (_, i) =>
    row({
      piece_id: i + 1,
      publication_id: i + 1,
      platform: "youtube",
      hook: `Video number ${i + 1}`,
      // Newest first once grouped, so 7 is at the top and 1 falls off the end.
      published_at: `2026-09-${String(11 + i).padStart(2, "0")}T18:30:00Z`,
    }),
  );

  it("shows five videos and offers the rest rather than printing them", () => {
    const read = text(many);
    expect(read).toContain("Video number 7");
    expect(read).toContain("Video number 3");
    expect(read).not.toContain("Video number 2");
    expect(read).not.toContain("Video number 1 ");
    expect(read).toContain("Show all 7 videos");
  });

  it("does not offer to show all when everything is already shown", () => {
    expect(text(many.slice(0, 3))).not.toContain("Show all");
  });
});

describe("the missing counters", () => {
  it("offers the keyboard only where no machine can read the number", () => {
    // A YouTube counter nobody has read is a tick that has not run yet; there
    // is nothing for a person to type, and a button saying otherwise sends
    // them looking for a box that is not there.
    expect(text([row({ piece_id: 41, publication_id: 1, platform: "youtube" })])).not.toContain(
      "Enter them",
    );
    expect(text([row({ piece_id: 41, publication_id: 1, platform: "tiktok" })])).toContain(
      "Enter them",
    );
  });

  it("counts the unread posts, not the videos", () => {
    // Three posts of one video with no reading is three numbers to go and
    // fetch, and saying "1" would understate the work by two thirds.
    expect(text(threePosts)).toContain("3 of 3 posts below");
  });
});

describe("where the card sits on the page", () => {
  it("takes the whole width, because it is the only section with no ceiling", () => {
    // Every other card on `/analytics` is a fixed handful of bars. This one
    // grows a row per video for as long as the agency keeps publishing, and in
    // half a column it made the left side several screens taller than the
    // right — which is the complaint that started the rewrite.
    const view = readFileSync(
      join(process.cwd(), "components/analytics/AnalyticsView.tsx"),
      "utf8",
    );
    expect(view).toMatch(/lg:col-span-2[\s\S]{0,300}<ContentTable/);
  });
});

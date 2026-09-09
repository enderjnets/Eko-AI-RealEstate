import { describe, expect, it } from "vitest";
import { groupByPiece, videoTitle } from "../videosByPiece";

const row = (
  piece_id: number,
  platform: string,
  published_at: string,
  hook: string | null = "a video",
) => ({ piece_id, platform, published_at, hook });

describe("groupByPiece", () => {
  it("puts the three platforms of one video in one group", () => {
    const rows = [
      row(7, "tiktok", "2026-09-06T14:00:00Z"),
      row(7, "youtube", "2026-09-07T02:00:00Z"),
      row(7, "instagram", "2026-09-07T00:00:00Z"),
    ];
    const videos = groupByPiece(rows);
    expect(videos).toHaveLength(1);
    expect(videos[0].piece_id).toBe(7);
    expect(videos[0].rows).toHaveLength(3);
  });

  it("reads the platforms in the same order on every card", () => {
    // Not the order the server happened to send. A row that moves between
    // cards is a row the eye has to hunt for, and the whole point of the card
    // is comparing the same video across platforms.
    const rows = [
      row(7, "tiktok", "2026-09-06T14:00:00Z"),
      row(7, "youtube", "2026-09-07T02:00:00Z"),
      row(7, "instagram", "2026-09-07T00:00:00Z"),
    ];
    expect(groupByPiece(rows)[0].rows.map((r) => r.platform)).toEqual([
      "youtube",
      "instagram",
      "tiktok",
    ]);
  });

  it("keeps a platform it has never heard of, at the end", () => {
    const rows = [
      row(7, "threads", "2026-09-07T03:00:00Z"),
      row(7, "youtube", "2026-09-07T02:00:00Z"),
    ];
    expect(groupByPiece(rows)[0].rows.map((r) => r.platform)).toEqual([
      "youtube",
      "threads",
    ]);
  });

  it("shows the most recently published video first", () => {
    const rows = [
      row(1, "youtube", "2026-09-01T02:00:00Z"),
      row(2, "youtube", "2026-09-08T02:00:00Z"),
      row(1, "tiktok", "2026-09-02T02:00:00Z"),
    ];
    expect(groupByPiece(rows).map((v) => v.piece_id)).toEqual([2, 1]);
  });

  it("ranks a video by its newest platform, not its oldest", () => {
    // Piece 1 started earlier but its last platform went out today; piece 2
    // began and ended yesterday. Ranking on the earliest publication would
    // bury the video that is still going out.
    const rows = [
      row(1, "tiktok", "2026-09-01T02:00:00Z"),
      row(1, "youtube", "2026-09-09T02:00:00Z"),
      row(2, "youtube", "2026-09-08T02:00:00Z"),
    ];
    expect(groupByPiece(rows).map((v) => v.piece_id)).toEqual([1, 2]);
  });

  it("gives every video a title", () => {
    const videos = groupByPiece([row(7, "youtube", "2026-09-07T02:00:00Z", "Fall in Denver")]);
    expect(videos[0].title).toBe("Fall in Denver");
  });

  it("has nothing to group when nothing was published", () => {
    expect(groupByPiece([])).toEqual([]);
  });
});

describe("videoTitle", () => {
  it("uses the hook the video was written with", () => {
    expect(videoTitle({ hook: "What your budget gets you", piece_id: 7 })).toBe(
      "What your budget gets you",
    );
  });

  it("falls back to the piece id when there is no hook", () => {
    // A clip filmed on a phone need not have one, and the row must still be
    // identifiable: an empty title is a card nobody can name.
    expect(videoTitle({ hook: null, piece_id: 7 })).toBe("#7");
  });

  it("treats a hook of only spaces as no hook at all", () => {
    expect(videoTitle({ hook: "   ", piece_id: 7 })).toBe("#7");
  });

  it("trims a hook that carries stray whitespace", () => {
    expect(videoTitle({ hook: "  Fall guide  ", piece_id: 7 })).toBe("Fall guide");
  });
});

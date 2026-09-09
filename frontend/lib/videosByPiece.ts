/**
 * Groups published rows into the videos they belong to.
 *
 * The analytics payload is one row per publication — a video posted to three
 * platforms arrives as three rows — and the card reads as one video with its
 * platforms underneath. The grouping is here rather than inline in the
 * component because the component tree has no test harness (no jsdom, no
 * testing-library), and this is the part with behaviour worth pinning.
 *
 * Two orderings, and each one is a decision:
 *
 * * **Platforms always in the same order**, not the order the server sent. A
 *   line that moves between cards is a line the eye has to hunt for, and
 *   comparing the same video across platforms is the whole point of the card.
 * * **Videos by their NEWEST publication**, because the platforms of one video
 *   are half a day apart and a video whose last platform went out this morning
 *   is more recent news than one that finished yesterday.
 */

/** The order platforms are read in, everywhere. Anything else goes after. */
export const PLATFORM_ORDER = ["youtube", "instagram", "tiktok"];

export interface PublishedRow {
  piece_id: number;
  hook: string | null;
  platform: string;
  published_at: string;
}

export interface Video<R extends PublishedRow> {
  piece_id: number;
  title: string;
  rows: R[];
}

/** What the video is called on screen. Never empty: a card nobody can name. */
export function videoTitle(row: { hook: string | null; piece_id: number }): string {
  return row.hook?.trim() || `#${row.piece_id}`;
}

function rank(platform: string): number {
  const at = PLATFORM_ORDER.indexOf(platform);
  return at === -1 ? PLATFORM_ORDER.length : at;
}

function newest<R extends PublishedRow>(rows: R[]): number {
  return Math.max(...rows.map((r) => new Date(r.published_at).getTime()));
}

export function groupByPiece<R extends PublishedRow>(rows: R[]): Video<R>[] {
  const byPiece = new Map<number, R[]>();
  for (const row of rows) {
    const found = byPiece.get(row.piece_id);
    if (found) found.push(row);
    else byPiece.set(row.piece_id, [row]);
  }

  const videos: Video<R>[] = [];
  for (const [piece_id, group] of byPiece) {
    videos.push({
      piece_id,
      title: videoTitle({ hook: group[0].hook, piece_id }),
      rows: [...group].sort((a, b) => rank(a.platform) - rank(b.platform)),
    });
  }
  return videos.sort(
    (a, b) => newest(b.rows) - newest(a.rows) || b.piece_id - a.piece_id,
  );
}

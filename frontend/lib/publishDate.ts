/**
 * The day a piece goes out, as the console shows and sets it.
 *
 * The publisher has read `publish_window_start` since September: it looks for a
 * slot from that day, holds the piece back until the day is close, and moves a
 * queued post that sits outside it. Until 0.143.31 only the writer could set
 * one, so a piece made by hand for Halloween (Cheesman Park, 11-oct-2026) went
 * out the evening it was approved.
 */
import type { ContentPiece } from "@/lib/api";
import type { Lang } from "@/lib/i18n";

/**
 * Today in the agency's zone, as YYYY-MM-DD. `en-CA` is the locale whose
 * short date IS the ISO form, so this is a string compare away from a column.
 */
export function todayIn(timezone?: string | null, now: Date = new Date()): string {
  return now.toLocaleDateString("en-CA", timezone ? { timeZone: timezone } : {});
}

/** Approved, dated, and its day is still ahead: no posts yet is expected. */
export function waitsForItsDate(
  piece: Pick<ContentPiece, "publish_window_start">,
  today: string,
): boolean {
  return !!piece.publish_window_start && piece.publish_window_start > today;
}

/** Everything but a published piece: the server refuses only that one. */
export function canSetPublishDate(piece: Pick<ContentPiece, "status">): boolean {
  return piece.status !== "published";
}

/**
 * A calendar day, never through `new Date("2026-10-29")`: that is midnight
 * UTC, which Denver shows as the 28th.
 */
export function formatPublishDate(iso: string, lang: Lang): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(
    lang === "es" ? "es-ES" : "en-US",
    { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" },
  );
}

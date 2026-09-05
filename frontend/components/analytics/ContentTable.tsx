"use client";

/**
 * What followed each publication — and the word for that is **association**.
 *
 * A link in a Shorts description is not clickable, Instagram strips the
 * referrer, and in-app browsers strip it too. So most people who see a video
 * and then come to the site arrive indistinguishable from anyone else. What can
 * be said truthfully is "these visits happened in the 48 hours after this went
 * out", and the wording here says exactly that. The only number on the row that
 * is attribution is `leads_tagged`, and it is labelled separately.
 *
 * This distinction is the whole reason the column is not called "views from
 * this video": a number with the wrong name is worse than no number, because
 * decisions get made on it.
 */

import type { Analytics } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Empty } from "./parts";

export function ContentTable({ rows }: { rows: Analytics["content"] }) {
  const { t, lang } = useI18n();
  if (rows.length === 0) return <Empty>{t("analytics.empty.content")}</Empty>;

  const when = (iso: string) =>
    new Date(iso).toLocaleDateString(lang === "es" ? "es-ES" : "en-US", {
      month: "short",
      day: "numeric",
    });

  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div
          key={`${r.piece_id}-${r.platform}`}
          className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 flex items-center gap-3"
        >
          <div className="min-w-0 flex-1">
            <div className="text-xs text-white truncate">
              #{r.piece_id} · {t(`platform.${r.platform}`)}
            </div>
            <div className="text-[10px] text-gray-500">{when(r.published_at)}</div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-xs tabular-nums text-gray-300">
              {r.association.sessions} · {r.association.leads}
            </div>
            <div className="text-[10px] text-gray-600">{t("analytics.assoc48")}</div>
          </div>
          {r.leads_tagged > 0 && (
            <div className="text-right shrink-0">
              <div className="text-xs tabular-nums text-eko-green">{r.leads_tagged}</div>
              <div className="text-[10px] text-gray-600">{t("analytics.tagged")}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

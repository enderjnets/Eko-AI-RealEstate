"use client";

/**
 * What each publication reached, and what followed it.
 *
 * Two numbers with two different standings, and keeping them apart is the whole
 * job of this component:
 *
 * * **Views is a measurement.** It is the platform's own counter. For YouTube a
 *   background tick reads it; for TikTok and Instagram a person types it,
 *   because neither hands view counts to anything short of a first-party app
 *   that has passed platform review. The row says which, so a hand-read number
 *   is never mistaken for a machine-read one.
 * * **Sessions and leads are association.** A link in a Shorts description is
 *   not clickable, Instagram strips the referrer, and in-app browsers strip it
 *   too — so most people who see a video and then come to the site arrive
 *   indistinguishable from everyone else. What can be said truthfully is
 *   "these visits happened in the 48 hours after this went out".
 *
 * Only `leads_tagged` is attribution, and it is labelled separately. A number
 * with the wrong name is worse than no number, because decisions get made on it.
 */

import { useState } from "react";
import { Pencil } from "lucide-react";
import { type Analytics, contentApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Empty } from "./parts";

/** Platforms whose counters no machine of ours can read. */
const TYPED_BY_HAND = new Set(["tiktok", "instagram"]);

function Views({
  row,
  onSaved,
}: {
  row: Analytics["content"][number];
  onSaved: (piece: number, platform: string, views: number) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    // An empty box is not a zero. Opening the editor and clicking away fires
    // `onBlur`, and `Number("")` is 0 — which would write "this video was seen
    // by nobody", the exact claim the card exists to avoid making by accident.
    if (value.trim() === "") {
      setEditing(false);
      return;
    }
    const views = Number(value);
    if (!Number.isFinite(views) || views < 0) return;
    setBusy(true);
    try {
      await contentApi.setMetrics(row.piece_id, row.platform, { views });
      onSaved(row.piece_id, row.platform, views);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        min={0}
        inputMode="numeric"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
          if (e.key === "Escape") setEditing(false);
        }}
        className="w-20 bg-white/5 border border-white/20 rounded px-1.5 py-0.5 text-xs text-white tabular-nums"
      />
    );
  }

  const typed = TYPED_BY_HAND.has(row.platform);
  const count = row.views?.count ?? null;

  if (count === null) {
    // Not a zero. Nobody has read this yet, and a zero would say the video was
    // seen by no one — a different and much worse claim.
    return typed ? (
      <button
        onClick={() => setEditing(true)}
        className="text-[10px] text-gray-500 hover:text-white inline-flex items-center gap-1"
      >
        <Pencil className="w-3 h-3" /> {t("analytics.addViews")}
      </button>
    ) : (
      <span className="text-[10px] text-gray-600">{t("analytics.noViews")}</span>
    );
  }

  return (
    <button
      onClick={() => {
        setValue(String(count));
        setEditing(true);
      }}
      className="group text-right"
      title={t("analytics.editViews")}
    >
      <div className="text-xs tabular-nums text-white group-hover:underline">
        {count.toLocaleString()}
      </div>
      <div className="text-[10px] text-gray-600">
        {row.views?.source === "manual"
          ? t("analytics.viewsTyped")
          : t("analytics.viewsRead")}
      </div>
    </button>
  );
}

export function ContentTable({ rows }: { rows: Analytics["content"] }) {
  const { t, lang } = useI18n();
  // Local, because the page fetches on a range change and re-typing a number to
  // see it appear is the kind of small dishonesty that makes people stop typing.
  const [typed, setTyped] = useState<Record<string, number>>({});
  if (rows.length === 0) return <Empty>{t("analytics.empty.content")}</Empty>;

  const when = (iso: string) =>
    new Date(iso).toLocaleDateString(lang === "es" ? "es-ES" : "en-US", {
      month: "short",
      day: "numeric",
    });

  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const key = `${r.piece_id}-${r.platform}`;
        const withTyped =
          typed[key] === undefined
            ? r
            : {
                ...r,
                views: {
                  count: typed[key],
                  captured_on: new Date().toISOString().slice(0, 10),
                  source: "manual",
                },
              };
        return (
          <div
            key={key}
            className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 flex items-center gap-3"
          >
            <div className="min-w-0 flex-1">
              <div className="text-xs text-white truncate">
                #{r.piece_id} · {t(`platform.${r.platform}`)}
              </div>
              <div className="text-[10px] text-gray-500">{when(r.published_at)}</div>
            </div>
            <div className="shrink-0 text-right">
              <Views
                row={withTyped}
                onSaved={(piece, platform, views) =>
                  setTyped((prev) => ({ ...prev, [`${piece}-${platform}`]: views }))
                }
              />
            </div>
            <div className="text-right shrink-0">
              <div className="text-xs tabular-nums text-gray-300">
                {r.association.sessions} · {r.association.leads}
              </div>
              <div className="text-[10px] text-gray-600">{t("analytics.assoc48")}</div>
            </div>
            {r.leads_tagged > 0 && (
              <div className="text-right shrink-0">
                <div className="text-xs tabular-nums text-eko-green">
                  {r.leads_tagged}
                </div>
                <div className="text-[10px] text-gray-600">{t("analytics.tagged")}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

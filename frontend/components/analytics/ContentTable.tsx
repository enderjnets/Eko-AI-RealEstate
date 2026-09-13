"use client";

/**
 * What each publication reached, and what followed it.
 *
 * Three groups of numbers have different standings, and keeping them apart is
 * the whole job of this component:
 *
 * * **Views is a measurement.** It is the platform's own counter. For YouTube a
 *   background tick reads it; for TikTok and Instagram a person types it,
 *   because neither hands view counts to anything short of a first-party app
 *   that has passed platform review. The row says which, so a hand-read number
 *   is never mistaken for a machine-read one.
 * * **Exact attribution** requires both the piece tag and the matching platform
 *   source, and follows the attributed lead through its appointments.
 * * **The 48-hour sessions and leads are association.** A Shorts link is
 *   not clickable, Instagram strips the referrer, and in-app browsers strip it
 *   too — so most people who see a video and then come to the site arrive
 *   indistinguishable from everyone else. What can be said truthfully is
 *   "these visits happened in the 48 hours after this went out".
 *
 * A number with the wrong name is worse than no number, because decisions get
 * made on it.
 */

import { useState } from "react";
import { Pencil } from "lucide-react";
import { type Analytics, type PublicationMetrics, contentApi } from "@/lib/api";
import { exactTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { groupByPiece } from "@/lib/videosByPiece";
import { Empty } from "./parts";

/** Platforms whose counters no machine of ours can read. */
const TYPED_BY_HAND = new Set(["tiktok", "instagram"]);

type MetricDraft = {
  views: string;
  likes: string;
  comments: string;
};

function parseMetric(value: string, optional: boolean): number | null | undefined {
  if (value.trim() === "") return optional ? null : undefined;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > 10_000_000_000) {
    return undefined;
  }
  return parsed;
}

function MetricValue({
  label,
  value,
  missingLabel,
}: {
  label: string;
  value: number | null;
  missingLabel?: string;
}) {
  const { t, locale } = useI18n();
  return (
    <span className="whitespace-nowrap">
      <span className="text-gray-500">{label}</span>{" "}
      <span className="font-medium text-gray-200 tabular-nums">
        {value === null
          ? (missingLabel ?? t("analytics.noReading"))
          : value.toLocaleString(locale)}
      </span>
    </span>
  );
}

function ScorecardValue({ label, value }: { label: string; value: number }) {
  const { locale } = useI18n();
  return (
    <span className="whitespace-nowrap">
      <span className="text-gray-500">{label}</span>{" "}
      <span className="font-medium text-gray-200 tabular-nums">
        {value.toLocaleString(locale)}
      </span>
    </span>
  );
}

function Metrics({
  row,
  onSaved,
}: {
  row: Analytics["content"][number];
  onSaved: (piece: number, platform: string, metrics: PublicationMetrics) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<MetricDraft>({ views: "", likes: "", comments: "" });
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState(false);

  const count =
    row.latest_metrics === null ? (row.views?.count ?? null) : row.latest_metrics.views;
  const likes = row.latest_metrics === null ? null : row.latest_metrics.likes;
  const comments = row.latest_metrics === null ? null : row.latest_metrics.comments;
  const source = row.latest_metrics?.source ?? row.views?.source ?? null;

  const open = () => {
    setSaveError(false);
    setDraft({
      views: count === null ? "" : String(count),
      likes: likes === null ? "" : String(likes),
      comments: comments === null ? "" : String(comments),
    });
    setEditing(true);
  };

  const save = async () => {
    const views = parseMetric(draft.views, false);
    const nextLikes = parseMetric(draft.likes, true);
    const nextComments = parseMetric(draft.comments, true);
    if (typeof views !== "number" || nextLikes === undefined || nextComments === undefined) return;
    setSaveError(false);
    setBusy(true);
    try {
      const updated = await contentApi.setMetrics(row.piece_id, row.platform, {
        views,
        likes: nextLikes,
        comments: nextComments,
      });
      const latest = updated.publications.find(
        (publication) => publication.id === row.publication_id,
      )?.latest_metrics;
      if (!latest) throw new Error("Saved metrics missing from response");
      onSaved(row.piece_id, row.platform, latest);
      setEditing(false);
    } catch {
      setSaveError(true);
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <div>
        <form
          className="flex flex-wrap items-end justify-end gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
        <label className="text-[10px] text-gray-500">
          {t("analytics.metric.views")}
          <input
            autoFocus
            name="views"
            type="number"
            min={0}
            max={10_000_000_000}
            step={1}
            inputMode="numeric"
            required
            value={draft.views}
            disabled={busy}
            onChange={(event) => setDraft((current) => ({ ...current, views: event.target.value }))}
            className="block w-20 bg-white/5 border border-white/20 rounded px-1.5 py-1 text-xs text-white tabular-nums"
          />
        </label>
        <label className="text-[10px] text-gray-500">
          {t("analytics.metric.likes")}
          <input
            name="likes"
            type="number"
            min={0}
            max={10_000_000_000}
            step={1}
            inputMode="numeric"
            value={draft.likes}
            disabled={busy}
            onChange={(event) => setDraft((current) => ({ ...current, likes: event.target.value }))}
            className="block w-20 bg-white/5 border border-white/20 rounded px-1.5 py-1 text-xs text-white tabular-nums"
          />
        </label>
        <label className="text-[10px] text-gray-500">
          {t("analytics.metric.comments")}
          <input
            name="comments"
            type="number"
            min={0}
            max={10_000_000_000}
            step={1}
            inputMode="numeric"
            value={draft.comments}
            disabled={busy}
            onChange={(event) =>
              setDraft((current) => ({ ...current, comments: event.target.value }))
            }
            className="block w-20 bg-white/5 border border-white/20 rounded px-1.5 py-1 text-xs text-white tabular-nums"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="min-h-7 cursor-pointer rounded bg-eko-violet px-2 py-1 text-[10px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("analytics.saveMetrics")}
        </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setSaveError(false);
              setEditing(false);
            }}
            className="min-h-7 cursor-pointer rounded border border-white/10 px-2 py-1 text-[10px] text-gray-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("analytics.cancelMetrics")}
          </button>
        </form>
        {saveError && (
          <p role="alert" className="mt-1 text-[10px] text-red-400">
            {t("analytics.metricsSaveError")}
          </p>
        )}
      </div>
    );
  }

  const typed = TYPED_BY_HAND.has(row.platform);

  return (
    <div className="text-right">
      <div className="flex flex-wrap justify-end gap-x-2 gap-y-0.5 text-[10px]">
        <MetricValue
          label={t("analytics.metric.views")}
          value={count}
          missingLabel={t("analytics.noViews")}
        />
        <MetricValue label={t("analytics.metric.likes")} value={likes} />
        <MetricValue label={t("analytics.metric.comments")} value={comments} />
      </div>
      <div className="mt-0.5 flex items-center justify-end gap-1 text-[10px] text-gray-600">
        {source !== null &&
          (source === "manual" ? t("analytics.metricsTyped") : t("analytics.metricsRead"))}
        {typed && (
          <button
            type="button"
            onClick={open}
            title={t("analytics.editMetrics")}
            aria-label={t("analytics.editMetrics")}
            className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded text-gray-500 hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-eko-violet"
          >
            <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

export function ContentTable({
  rows,
  timezone,
}: {
  rows: Analytics["content"];
  timezone: string;
}) {
  const { t, lang } = useI18n();
  // Local, because the page fetches on a range change and re-typing counters to
  // see them appear is the kind of friction that makes people stop recording them.
  const [typed, setTyped] = useState<Record<string, PublicationMetrics>>({});
  if (rows.length === 0) return <Empty>{t("analytics.empty.content")}</Empty>;

  return (
    <div className="space-y-3">
      {groupByPiece(rows).map((video) => {
        // Per video, not per post. The server counts the 48 hours after EACH
        // of the video's posts as one window, so a visit that fell inside two
        // of them is one person, not two — and it stamps the same block on
        // every row of the video. Shown once, beside the title: repeated on
        // three platform lines it read as three times the people.
        const after = video.rows[0].association;
        return (
          <div
            key={video.piece_id}
            className="rounded-lg border border-white/5 bg-white/[0.02] p-3 space-y-2"
          >
            <div className="flex items-start justify-between gap-3">
              {/* Two lines, then clipped — a hook runs to 300 characters and
                  a card that grows to fit one buries the rest of the report.
                  It IS a truncation, so the whole title stays reachable in
                  `title` rather than being lost. */}
              <div
                className="min-w-0 flex-1 text-sm text-white leading-snug line-clamp-2"
                title={video.title}
              >
                {video.title}
              </div>
              <div className="shrink-0 text-right">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">
                  {t("analytics.temporalAssociation")}
                </div>
                <div className="text-xs tabular-nums text-gray-300">
                  {after.sessions} {t("analytics.visitsAfter")} ·{" "}
                  {after.leads} {t("analytics.leadsAfter")}
                </div>
                <div className="text-[10px] text-gray-600">{t("analytics.assoc48")}</div>
              </div>
            </div>
            {video.rows.map((r) => {
              const key = `${r.piece_id}-${r.platform}`;
              const withTyped =
                typed[key] === undefined
                  ? r
                  : {
                      ...r,
                      latest_metrics: typed[key],
                      views: {
                        count: typed[key].views,
                        captured_on: typed[key].captured_on,
                        source: typed[key].source,
                      },
                    };
              const platform = t(`platform.${r.platform}`);
              return (
                <div
                  key={r.publication_id}
                  className="border-t border-white/5 pt-2"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-3">
                    {/* Two lines on purpose, not one that wraps: at 390px the
                        hour and the link broke across three, with the link
                        landing wherever the break fell. */}
                    <div className="min-w-0 flex-1 text-xs text-gray-300">
                      <div>
                        <span className="text-white">{platform}</span>
                        {" · "}
                        {/* The agency's hour, not the reader's: each platform
                            posts the same video half a day apart. */}
                        <span className="text-gray-500">
                          {exactTime(r.published_at, lang, timezone)}
                        </span>
                      </div>
                      <div>
                        {r.external_url ? (
                          <a
                            href={r.external_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-eko-violet hover:underline"
                          >
                            {t("content.watchOn", { platform })}
                          </a>
                        ) : (
                          <span className="text-gray-600">{t("analytics.noLink")}</span>
                        )}
                      </div>
                    </div>
                    <div className="min-w-0 w-full sm:w-auto sm:shrink-0">
                      <Metrics
                        row={withTyped}
                        onSaved={(piece, platform_, metrics) =>
                          setTyped((prev) => ({
                            ...prev,
                            [`${piece}-${platform_}`]: metrics,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="mt-2 rounded bg-black/10 px-2 py-1.5">
                    <div className="text-[10px] uppercase tracking-wider text-eko-green">
                      {t("analytics.exactAttribution")}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px]">
                      <ScorecardValue
                        label={t("analytics.metric.visits")}
                        value={r.attribution.sessions}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.engaged")}
                        value={r.attribution.engaged}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.nextStepClicks")}
                        value={r.attribution.cta_clickers}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.contactIntent")}
                        value={r.attribution.contact_intents}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.formStarts")}
                        value={r.attribution.form_starts}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.formSubmits")}
                        value={r.attribution.form_submits}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.leads")}
                        value={r.attribution.leads}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.appointmentsSet")}
                        value={r.attribution.appointments_set}
                      />
                      <ScorecardValue
                        label={t("analytics.metric.appointmentsHeld")}
                        value={r.attribution.appointments_held}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

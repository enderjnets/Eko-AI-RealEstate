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
 *
 * **One line per video, and the nine stage names said once.** Every post used
 * to print twelve numbers — three counters and the nine exact stages — with
 * every stage spelling out its own caption. Three platforms made that thirty-six
 * numbers and twenty-seven captions per video, and in production every one of
 * the twenty-seven is a zero. The card was the only one on the page with no
 * ceiling, in half a column, so each video published pushed the rest of the
 * report further down. So: a video is one row; its stage names move into a
 * header that appears once when the row is opened; and a funnel that is
 * entirely zero is said in a sentence instead of nine captioned zeros. Nothing
 * is renamed and nothing is dropped — all nine are still there, under their own
 * names, one key press away.
 *
 * **What may be added up and what may not.** Exact attribution groups by
 * (piece, platform) on the session's `utm_content` and `source`, and a session
 * — like a lead's first touch — has exactly one source, so the platforms of one
 * video are disjoint and their counters add. The 48-hour association does NOT:
 * it is counted once over the union of the video's windows, and the same
 * visitor falls inside the windows of two different videos.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import {
  type Analytics,
  type ContentAttribution,
  type PublicationMetrics,
  contentApi,
} from "@/lib/api";
import { exactTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { groupByPiece } from "@/lib/videosByPiece";
import { Empty } from "./parts";

/** Platforms whose counters no machine of ours can read. */
const TYPED_BY_HAND = new Set(["tiktok", "instagram"]);

/** Videos shown before the card asks to be opened up. */
const SHOWN_AT_FIRST = 5;

type MetricDraft = {
  views: string;
  likes: string;
  comments: string;
};

type Row = Analytics["content"][number];

/** No piece id is 0, so it can stand for "the reader closed them all". */
const NONE_OPEN = 0;

function parseMetric(value: string, optional: boolean): number | null | undefined {
  if (value.trim() === "") return optional ? null : undefined;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > 10_000_000_000) {
    return undefined;
  }
  return parsed;
}

/** Whether anybody has read this post's view counter yet. */
function reading(row: Row): number | null {
  return row.latest_metrics === null ? (row.views?.count ?? null) : row.latest_metrics.views;
}

/**
 * Exact attribution across several posts of the same video.
 *
 * Safe precisely because it is the exact half: the server groups it by
 * (piece, platform) and one session — one lead's first touch, one visit's lead
 * — belongs to a single platform, so no person is counted twice. The 48-hour
 * association is never handled this way.
 */
function addUp(rows: Row[]): ContentAttribution {
  return rows.reduce<ContentAttribution>(
    (total, row) => ({
      sessions: total.sessions + row.attribution.sessions,
      engaged: total.engaged + row.attribution.engaged,
      cta_clickers: total.cta_clickers + row.attribution.cta_clickers,
      contact_intents: total.contact_intents + row.attribution.contact_intents,
      form_starts: total.form_starts + row.attribution.form_starts,
      form_submits: total.form_submits + row.attribution.form_submits,
      leads: total.leads + row.attribution.leads,
      appointments_set: total.appointments_set + row.attribution.appointments_set,
      appointments_held: total.appointments_held + row.attribution.appointments_held,
    }),
    {
      sessions: 0,
      engaged: 0,
      cta_clickers: 0,
      contact_intents: 0,
      form_starts: 0,
      form_submits: 0,
      leads: 0,
      appointments_set: 0,
      appointments_held: 0,
    },
  );
}

/**
 * The nine stages, in funnel order, each with a short head and its real name.
 *
 * The short one is what fits nine columns; the real one is on the heading's
 * `title` and is the only one the dictionaries treat as the caption. Spanish is
 * what forces this — "Visitantes que eligieron el siguiente paso" is
 * forty-two characters and there are nine of them across one card.
 */
function stagesOf(attribution: ContentAttribution, t: (key: string) => string) {
  return [
    {
      short: t("analytics.metric.short.visits"),
      long: t("analytics.metric.visits"),
      value: attribution.sessions,
    },
    {
      short: t("analytics.metric.short.engaged"),
      long: t("analytics.metric.engaged"),
      value: attribution.engaged,
    },
    {
      short: t("analytics.metric.short.nextStepClicks"),
      long: t("analytics.metric.nextStepClicks"),
      value: attribution.cta_clickers,
    },
    {
      short: t("analytics.metric.short.contactIntent"),
      long: t("analytics.metric.contactIntent"),
      value: attribution.contact_intents,
    },
    {
      short: t("analytics.metric.short.formStarts"),
      long: t("analytics.metric.formStarts"),
      value: attribution.form_starts,
    },
    {
      short: t("analytics.metric.short.formSubmits"),
      long: t("analytics.metric.formSubmits"),
      value: attribution.form_submits,
    },
    {
      short: t("analytics.metric.short.leads"),
      long: t("analytics.metric.leads"),
      value: attribution.leads,
    },
    {
      short: t("analytics.metric.short.appointmentsSet"),
      long: t("analytics.metric.appointmentsSet"),
      value: attribution.appointments_set,
    },
    {
      short: t("analytics.metric.short.appointmentsHeld"),
      long: t("analytics.metric.appointmentsHeld"),
      value: attribution.appointments_held,
    },
  ];
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
      <span className="text-gray-400">{label}</span>{" "}
      <span className="font-medium text-gray-200 tabular-nums">
        {value === null
          ? (missingLabel ?? t("analytics.noReading"))
          : value.toLocaleString(locale)}
      </span>
    </span>
  );
}

/**
 * One exact-attribution number under a heading that is somewhere else.
 *
 * A zero is not dimmed into illegibility — `text-gray-600` on this page's black
 * is 2.7:1 and a number nobody can read is a number with no name. What carries
 * the meaning is weight and hue: a stage that moved is bright and green.
 */
function StageValue({ value }: { value: number }) {
  const { locale } = useI18n();
  return (
    <span
      className={`text-right tabular-nums ${
        value > 0 ? "font-semibold text-eko-green" : "text-gray-400"
      }`}
    >
      {value.toLocaleString(locale)}
    </span>
  );
}

function Metrics({
  row,
  onSaved,
}: {
  row: Row;
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
  const capturedOn = row.latest_metrics?.captured_on ?? row.views?.captured_on ?? null;

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
          className="flex flex-wrap items-end gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
        <label className="text-[10px] text-gray-400">
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
        <label className="text-[10px] text-gray-400">
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
        <label className="text-[10px] text-gray-400">
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
    <div>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px]">
        <MetricValue
          label={t("analytics.metric.views")}
          value={count}
          missingLabel={t("analytics.noViews")}
        />
        <MetricValue label={t("analytics.metric.likes")} value={likes} />
        <MetricValue label={t("analytics.metric.comments")} value={comments} />
      </div>
      <div className="mt-0.5 flex items-center gap-1 text-[10px] text-gray-400">
        {source !== null &&
          (source === "manual" ? t("analytics.metricsTyped") : t("analytics.metricsRead"))}
        {source !== null && capturedOn !== null && " · "}
        {capturedOn !== null && <time dateTime={capturedOn}>{capturedOn}</time>}
        {typed && (
          <button
            type="button"
            onClick={open}
            title={t("analytics.editMetrics")}
            aria-label={t("analytics.editMetrics")}
            className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded text-gray-400 hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-eko-violet"
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
  const { t, lang, locale } = useI18n();
  // Local, because the page fetches on a range change and re-typing counters to
  // see them appear is the kind of friction that makes people stop recording them.
  const [typed, setTyped] = useState<Record<string, PublicationMetrics>>({});
  // `null` means nobody has chosen yet, and the newest video is open — the one
  // the reader came to check. `NONE_OPEN` is the reader closing that one.
  const [opened, setOpened] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  if (rows.length === 0) return <Empty>{t("analytics.empty.content")}</Empty>;

  const videos = groupByPiece(rows);
  const openId = opened === null ? videos[0].piece_id : opened;
  const shown = showAll ? videos : videos.slice(0, SHOWN_AT_FIRST);
  const tagged = addUp(rows);
  const unread = rows.filter((row) => reading(row) === null);
  // The button only appears where pressing it can achieve something: a YouTube
  // counter nobody has read is a tick that has not run, not a box to fill in.
  const firstTypable = unread.find((row) => TYPED_BY_HAND.has(row.platform));

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-eko-green/25 bg-eko-green/[0.04] px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-eko-green">
            {t("analytics.taggedEverything")}
          </div>
          <div className="text-sm text-gray-100 tabular-nums">
            {t("analytics.taggedSummary", {
              visits: tagged.sessions.toLocaleString(locale),
              leads: tagged.leads.toLocaleString(locale),
            })}
          </div>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-lg border border-white/10 px-3 py-2">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-400">
              {t("analytics.countersUnread")}
            </div>
            <div className="text-sm text-gray-100 tabular-nums">
              {t("analytics.countersUnreadOf", { unread: unread.length, total: rows.length })}
            </div>
          </div>
          {firstTypable && (
            <button
              type="button"
              onClick={() => {
                // The video with the missing counter may be below the cut, and
                // a button that silently opens something nobody can see is
                // worse than no button.
                setShowAll(true);
                setOpened(firstTypable.piece_id);
              }}
              className="min-h-[44px] shrink-0 cursor-pointer rounded-lg border border-white/15 px-3 text-xs text-gray-200 hover:bg-white/5"
            >
              {t("analytics.enterCounters")}
            </button>
          )}
        </div>
      </div>

      {/* The headings the rows are read against, said once for the whole card
          instead of once per post — which is what the nine captions used to
          cost, three times over per video. */}
      <div className="hidden gap-3 border-b border-white/10 pb-1.5 text-[10px] uppercase tracking-wider sm:grid sm:grid-cols-[20px_minmax(0,2.2fr)_minmax(0,1.8fr)_minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <span />
        <span className="text-gray-400">{t("analytics.videoColumn")}</span>
        <span className="text-gray-400">{t("analytics.postsColumn")}</span>
        <span className="text-eko-green">{t("analytics.exactAttribution")}</span>
        <span className="text-gray-400">{t("analytics.temporalAssociation")}</span>
      </div>

      <div>
        {shown.map((video) => {
          // Per video, not per post. The server counts the 48 hours after EACH
          // of the video's posts as one window, so a visit that fell inside two
          // of them is one person, not two — and it stamps the same block on
          // every row of the video. Shown once, beside the title: repeated on
          // three platform lines it read as three times the people.
          const after = video.rows[0].association;
          const isOpen = openId === video.piece_id;
          const own = addUp(video.rows);
          const stages = stagesOf(own, t);
          const moved = stages.filter((stage) => stage.value > 0);
          return (
            <div key={video.piece_id} className="border-b border-white/[0.07] last:border-b-0">
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpened(isOpen ? NONE_OPEN : video.piece_id)}
                className="flex w-full min-h-[44px] cursor-pointer flex-col gap-2 px-1 py-3 text-left hover:bg-white/[0.02] sm:grid sm:grid-cols-[20px_minmax(0,2.2fr)_minmax(0,1.8fr)_minmax(0,1.1fr)_minmax(0,0.9fr)] sm:items-start sm:gap-3"
              >
                <span className="flex items-start gap-2 sm:contents">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center text-gray-400">
                    {isOpen ? (
                      <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
                    )}
                  </span>
                  {/* Two lines, then clipped — a hook runs to 300 characters and
                      a card that grows to fit one buries the rest of the report.
                      It IS a truncation, so the whole title stays reachable in
                      `title` rather than being lost. */}
                  <span className="min-w-0 flex-1 text-sm leading-snug text-white line-clamp-2" title={video.title}>
                    {video.title}
                  </span>
                </span>

                <span className="flex flex-wrap gap-1.5">
                  {video.rows.map((r) => {
                    const key = `${r.piece_id}-${r.platform}`;
                    const count = typed[key] === undefined ? reading(r) : typed[key].views;
                    return (
                      <span
                        key={r.publication_id}
                        className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-gray-300"
                      >
                        <span
                          aria-hidden="true"
                          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                            count === null ? "bg-gray-600" : "bg-eko-green"
                          }`}
                        />
                        {t(`platform.${r.platform}`)}
                        <span className="tabular-nums text-gray-400">
                          {count === null ? "—" : count.toLocaleString(locale)}
                        </span>
                      </span>
                    );
                  })}
                </span>

                <span className="grid grid-cols-2 gap-3 sm:contents">
                  <span className="min-w-0">
                    <span className="text-[10px] uppercase tracking-wider text-eko-green sm:hidden">
                      {t("analytics.exactAttribution")}
                    </span>
                    {/* Nine zeros with nine captions said the same thing this
                        sentence says, and buried the one video that did not. */}
                    {moved.length === 0 ? (
                      <span className="block text-xs text-gray-400">{t("analytics.noTaggedYet")}</span>
                    ) : (
                      <span className="block text-sm font-semibold tabular-nums text-eko-green">
                        {t("analytics.taggedSummary", {
                          visits: own.sessions.toLocaleString(locale),
                          leads: own.leads.toLocaleString(locale),
                        })}
                      </span>
                    )}
                  </span>

                  <span className="min-w-0 tabular-nums">
                    <span className="text-[10px] uppercase tracking-wider text-gray-400 sm:hidden">
                      {t("analytics.temporalAssociation")}
                    </span>
                    <span className="block text-xs text-gray-200">
                      {after.sessions} {t("analytics.visitsAfter")}
                    </span>
                    <span className="block text-xs text-gray-200">
                      {after.leads} {t("analytics.leadsAfter")}
                    </span>
                    <span className="block text-[10px] text-gray-400">{t("analytics.assoc48")}</span>
                  </span>
                </span>
              </button>

              {isOpen && (
                <div className="mb-3 rounded-lg border border-white/[0.08] bg-black/20 p-3 sm:ml-[32px]">
                  {/* The nine names, once per open video — the change this whole
                      card was rewritten for. They were printed under every
                      counter of every post, three times over. */}
                  <div className="hidden gap-2 border-b border-white/[0.08] pb-1.5 text-[9px] uppercase tracking-wide text-gray-400 sm:grid sm:grid-cols-[minmax(0,1.7fr)_minmax(0,1.6fr)_repeat(9,minmax(0,0.55fr))] sm:items-end">
                    <span>{t("analytics.postColumn")}</span>
                    <span>{t("analytics.platformCounters")}</span>
                    {stages.map((stage) => (
                      <abbr
                        key={stage.long}
                        title={stage.long}
                        className="cursor-help text-right no-underline"
                      >
                        {stage.short}
                      </abbr>
                    ))}
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
                    const own_stages = stagesOf(r.attribution, t);
                    const own_moved = own_stages.filter((stage) => stage.value > 0);
                    return (
                      <div
                        key={r.publication_id}
                        className="flex flex-col gap-2 border-b border-white/[0.05] py-2 last:border-b-0 sm:grid sm:grid-cols-[minmax(0,1.7fr)_minmax(0,1.6fr)_repeat(9,minmax(0,0.55fr))] sm:items-center sm:gap-2"
                      >
                        {/* Two lines on purpose, not one that wraps: at 390px the
                            hour and the link broke across three, with the link
                            landing wherever the break fell. */}
                        <div className="min-w-0 text-xs text-gray-300">
                          <div>
                            <span className="text-white">{platform}</span>
                            {" · "}
                            {/* The agency's hour, not the reader's: each platform
                                posts the same video half a day apart. */}
                            <span className="text-gray-400">
                              {exactTime(r.published_at, lang, timezone)}
                            </span>
                          </div>
                          <div>
                            {r.external_url ? (
                              <a
                                href={r.external_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-violet-400 hover:underline"
                              >
                                {t("content.watchOn", { platform })}
                              </a>
                            ) : (
                              <span className="text-gray-400">{t("analytics.noLink")}</span>
                            )}
                          </div>
                        </div>

                        <div className="min-w-0">
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

                        {/* Nine columns need width there is none of on a phone,
                            so a phone gets the stages that moved and a count of
                            the ones that did not — the same facts, no captions
                            spent on zeros. */}
                        <p className="text-[11px] text-gray-400 sm:hidden">
                          {own_moved.length === 0
                            ? t("analytics.stagesAllZero")
                            : `${own_moved
                                .map((stage) => `${stage.long} ${stage.value}`)
                                .join(" · ")} — ${t("analytics.stagesRest", {
                                n: own_stages.length - own_moved.length,
                              })}`}
                        </p>

                        {own_stages.map((stage) => (
                          <span key={stage.long} className="hidden text-xs sm:block">
                            <StageValue value={stage.value} />
                          </span>
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {videos.length > SHOWN_AT_FIRST && (
          <button
            type="button"
            onClick={() => setShowAll((current) => !current)}
            className="min-h-[44px] cursor-pointer rounded-lg border border-white/15 px-4 text-xs text-gray-200 hover:bg-white/5"
          >
            {showAll
              ? t("analytics.showFewer")
              : t("analytics.showAllVideos", { n: videos.length })}
          </button>
        )}
        <p className="flex-1 text-[11px] text-gray-400">{t("analytics.neverAddedUp")}</p>
      </div>
    </div>
  );
}

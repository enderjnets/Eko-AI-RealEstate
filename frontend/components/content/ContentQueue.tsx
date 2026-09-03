"use client";

/**
 * The approval queue. Everything waiting for a person, with the reason it is
 * waiting, and the two buttons that settle it.
 *
 * The editor is inline rather than a separate page because the common case is
 * fixing one phrase the filter flagged — and an edit to an APPROVED piece
 * visibly knocks it back to the queue, which is the backend rule made
 * legible: the person approved the old text.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  Check,
  Info,
  Loader2,
  Pencil,
  Clock,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  X,
} from "lucide-react";
import {
  type ContentPiece,
  type ContentStatus,
  type StudioStatus,
  contentApi,
} from "@/lib/api";
import type { Lang } from "@/lib/i18n";
import { exactTime, relativeTime, timeUntil } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { latestWins } from "@/lib/latestWins";
import { useSettingsAccess, useViewer } from "@/lib/useViewer";
import { UploadClip } from "@/components/content/UploadClip";

/**
 * A tab is not a status.
 *
 * "Approved" covers `approved` *and* `publishing`, because a piece handed to
 * the queue is still waiting to go out and is exactly the one whose date
 * somebody opened this screen to see. And `published` gets a tab of its own:
 * without it a piece leaves the console the moment it succeeds, which is how
 * pieces 6 and 7 went live and then appeared nowhere at all.
 */
const TABS = {
  needs_approval: ["needs_approval"],
  draft: ["draft"],
  approved: ["approved", "publishing"],
  published: ["published"],
  rejected: ["rejected"],
} as const satisfies Record<string, readonly ContentStatus[]>;

type TabKey = keyof typeof TABS;
const TAB_KEYS = Object.keys(TABS) as TabKey[];

export function ContentQueue() {
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<TabKey>("needs_approval");
  const [pieces, setPieces] = useState<ContentPiece[] | null>(null);
  const [studio, setStudio] = useState<StudioStatus | null>(null);
  // Write controls hide themselves for viewers everywhere else in this app
  // (`useViewer`), and the backend 403s them anyway — a visible upload button
  // for a read-only account is a button that can only ever fail.
  const readOnly = useViewer();
  // Uploading switches to Drafts AND reloads, so two loads are in flight with
  // different `tab` closures. Without this the older one can land last and
  // leave the person on Drafts looking at the previous tab's list — the exact
  // damage this helper was written for, in the panel next door.
  const gate = useRef(latestWins()).current;
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const mine = gate.start();
    try {
      // In parallel, and the status is not allowed to break the list: if it
      // fails the queue still renders, just without the explanation.
      const [list, status] = await Promise.all([
        contentApi.list([...TABS[tab]]),
        contentApi.status().catch(() => null),
      ]);
      if (!mine()) return;
      setPieces(list);
      setStudio(status);
    } catch (err) {
      if (!mine()) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [tab, gate]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: number, action: () => Promise<ContentPiece>) => {
    setBusyId(id);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section>
      {/* Title and subtitle live in the page's PageHeader — repeating them here
          is what the move out of /console was for. */}
      <div className="flex items-start justify-end gap-3 flex-wrap">
        <button
          onClick={() => void load()}
          className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors mt-1.5"
        >
          <RefreshCw className="w-4 h-4" /> {t("content.refresh")}
        </button>
        {/* A new clip lands in Drafts, so send the person there rather than
            leaving them on a tab where nothing appeared. */}
        {!readOnly && (
        <UploadClip
          /* `studio` is null when the status GET failed — deliberately, so one
             failed request cannot break uploading. Undefined means "limit
             unknown", and the client-side check stands down; the server is
             still the gate. */
          maxMb={studio?.upload_max_mb}
          onUploaded={() => {
            setTab("draft");
            void load();
          }}
        />
        )}
      </div>

      <div className="mt-3 flex gap-2 flex-wrap" role="tablist">
        {TAB_KEYS.map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
              tab === key
                ? "bg-eko-violet/15 text-eko-violet border-eko-violet/40"
                : "bg-white/[0.03] text-gray-400 border-white/10 hover:border-white/20"
            }`}
          >
            {t(`content.tab.${key}`)}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 text-sm text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="break-words">{error}</span>
        </div>
      )}

      {pieces !== null && pieces.length > 0 && <StudioDiagnosis studio={studio} tab={tab} compact />}

      {pieces === null ? (
        <div className="mt-6 flex justify-center text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : pieces.length === 0 ? (
        <div className="mt-6">
          <p className="text-sm text-gray-500">{t("content.empty")}</p>
          <StudioDiagnosis studio={studio} tab={tab} />
        </div>
      ) : (
        <ul className="mt-4 space-y-4">
          {pieces.map((piece) => (
            <PieceCard
              studio={studio}
              key={piece.id}
              piece={piece}
              busy={busyId === piece.id}
              lang={lang}
              onApprove={() => act(piece.id, () => contentApi.approve(piece.id))}
              onReject={(reason) =>
                act(piece.id, () => contentApi.reject(piece.id, reason))
              }
              onSubmit={() => act(piece.id, () => contentApi.submit(piece.id))}
              onRetry={() => act(piece.id, () => contentApi.retry(piece.id))}
              onRebuild={() => act(piece.id, () => contentApi.rebuild(piece.id))}
              onEdit={(body) => act(piece.id, () => contentApi.edit(piece.id, body))}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Why this screen looks the way it does.
 *
 * "Nothing here right now" is true and answers nothing: the reasons live in
 * three unrelated places — two server flags and a settings row — and no screen
 * showed any of them.
 *
 * The trap this walked into first: the emptiness is per TAB, the studio state
 * is global. On an installation with twelve pieces awaiting approval, opening
 * the empty "Rejected" tab announced "nothing is waiting, and these are the
 * reasons why" and then blamed the configuration. Both halves false, and the
 * second one sends a broker off to fix something while twelve approved clips
 * sit one tab away. `counts` arrives in the same response precisely so this
 * screen can tell the two apart — an empty tab in a busy studio says where the
 * work is; an empty studio explains itself.
 */
function StudioDiagnosis({
  studio,
  tab,
  compact = false,
}: {
  studio: StudioStatus | null;
  tab: TabKey;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const canOpenSettings = useSettingsAccess();
  if (!studio) return null;

  const total = Object.values(studio.counts).reduce((a, b) => a + b, 0);
  // Summed over the statuses this tab covers, not read from one key: with
  // "Approved" holding both `approved` and `publishing`, a single lookup would
  // report pieces as being "somewhere else" while they sat on this very screen.
  const here = TABS[tab].reduce((n, s) => n + (studio.counts[s] ?? 0), 0);
  const elsewhere = total - here;

  // Only what someone can act on. "Publishing is not built yet" is true
  // forever until v0.56, so putting it in the list would pin a permanent
  // banner to a page whose whole point is that its box means something.
  const blockers: { key: string; fixable?: boolean }[] = [];
  if (!studio.brokerage_line_set) {
    blockers.push({ key: "brokerage", fixable: canOpenSettings });
  }
  if (!studio.studio_enabled) blockers.push({ key: "studio" });
  if (!studio.render_enabled) blockers.push({ key: "render" });

  // With pieces on screen the box is only worth showing when something is
  // actually switched off — otherwise it is noise on every load.
  if (compact && blockers.length === 0) return null;

  const heading = compact
    ? "content.whyLimited"
    : elsewhere > 0
      ? "content.emptyTabBusyStudio"
      : blockers.length > 0
        ? "content.whyEmpty"
        : "content.whyEmptyAndReady";

  return (
    <div
      className={`${compact ? "mt-3" : "mt-4"} rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm`}
    >
      <p className="flex items-center gap-1.5 text-gray-300">
        <Info className="w-4 h-4 text-eko-violet shrink-0" />
        {t(heading, { count: String(elsewhere) })}
      </p>
      {blockers.length > 0 && (
        <ul className="mt-2 space-y-1 text-gray-400">
          {blockers.map(({ key, fixable }) => (
            <li key={key} className="flex gap-2">
              <span aria-hidden className="text-gray-600">·</span>
              <span>
                {t(`content.why.${key}`)}{" "}
                {fixable && (
                  <Link href="/settings" className="text-eko-violet hover:underline">
                    {t("content.whyFixHere")}
                  </Link>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {!compact && !studio.publishing_ready && (
        <p className="mt-2 text-gray-500">{t("content.why.publishing")}</p>
      )}
    </div>
  );
}


/**
 * What the render is actually doing.
 *
 * This used to be one line — "the video is still being made" — shown with a
 * spinner whether the job was queued, being worked on, or waiting for the
 * render machine's agreed hours. The owner watched it for an hour and went
 * looking for a fault; there was none, the machine simply does not work at
 * 22:00. A spinner that means three different things is worse than no spinner.
 */

/**
 * A clock that ticks, so a countdown is not a screenshot.
 *
 * `timeUntil` reads `Date.now()` when it runs, and React has no reason to run
 * it again on its own — the piece has not changed. Without this the number a
 * person sees is however long it was until the moment the page rendered, which
 * is worse than showing nothing because it looks live.
 *
 * Thirty seconds: the finest unit the text ever shows is a minute.
 */
function useNow(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return now;
}

const PLATFORM_LABEL: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
};

/**
 * When each platform gets this video, and where to watch it once it has.
 *
 * This replaced a row of `platform · status` chips, which answered a question
 * nobody was asking. The owner's was "cuándo se publica", and until the queue
 * existed there was no honest answer to give.
 */
function PublishSchedule({
  piece,
  studio,
}: {
  piece: ContentPiece;
  studio: StudioStatus | null;
}) {
  const { t, lang } = useI18n();
  // Subscribed unconditionally: hooks cannot be called behind a condition, and
  // the early return below would otherwise change the hook order between
  // renders of the same card.
  useNow(30_000);

  if (piece.publications.length === 0) {
    // Approved and not yet picked up. The next tick of the publish loop is
    // minutes away, so say that rather than spin: a spinner with no end is the
    // fault this console already shipped once with the render queue.
    if (piece.status === "approved") {
      return (
        <p className="mt-3 text-sm text-gray-400">{t("content.publishSoon")}</p>
      );
    }
    return null;
  }

  return (
    <div className="mt-3 space-y-1.5">
      {piece.publications.map((pub) => {
        const name = PLATFORM_LABEL[pub.platform] ?? pub.platform;

        if (pub.status === "scheduled" && pub.scheduled_at) {
          return (
            <p key={pub.id} className="text-sm text-gray-300">
              <span className="text-gray-500">{name}</span>{" "}
              {exactTime(pub.scheduled_at, lang, studio?.timezone)}{" "}
              <span className="text-eko-violet">
                · {timeUntil(pub.scheduled_at, lang)}
              </span>
            </p>
          );
        }

        if (pub.status === "published") {
          return (
            <p key={pub.id} className="text-sm text-gray-300">
              <span className="text-gray-500">{name}</span>{" "}
              {t("content.publishedLabel")}
              {pub.external_url && (
                <>
                  {" · "}
                  <a
                    href={pub.external_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-eko-violet hover:underline"
                  >
                    {t("content.watchOn", { platform: name })}
                  </a>
                </>
              )}
            </p>
          );
        }

        if (pub.status === "failed") {
          return (
            <p key={pub.id} className="text-sm text-red-300">
              <span className="text-gray-500">{name}</span>{" "}
              {pub.last_error || t("content.publishFailed")}
            </p>
          );
        }

        // pending / publishing: in flight, and the honest word for it.
        return (
          <p key={pub.id} className="text-sm text-gray-400">
            <span className="text-gray-500">{name}</span>{" "}
            {t("content.publishInFlight")}
          </p>
        );
      })}
    </div>
  );
}

function RenderProgress({ piece }: { piece: ContentPiece }) {
  const { t } = useI18n();
  const state = piece.render_state;
  const idle = piece.render_machine_working === false;

  if (state === "queued" || state == null) {
    return (
      <span className="inline-flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400">
        <Clock className="w-4 h-4" />
        {idle ? t("content.renderQueuedIdle") : t("content.renderQueued")}
      </span>
    );
  }

  // A percentage the worker reported, or an honest indeterminate bar. Never a
  // number invented on this side: a bar that moves on its own is a lie with an
  // animation.
  const pct = typeof piece.render_progress === "number" ? piece.render_progress : null;
  const stage = piece.render_stage ? t(`content.stage.${piece.render_stage}`) : null;
  return (
    <span className="inline-flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 min-w-[240px]">
      <Loader2 className="w-4 h-4 animate-spin shrink-0" />
      <span className="flex-1">
        <span className="block">{stage ?? t("content.awaitingVideo")}</span>
        <span className="mt-1 block h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
          <span
            className="block h-full rounded-full bg-eko-violet transition-[width] duration-700"
            style={{ width: pct == null ? "35%" : `${Math.max(4, pct)}%` }}
          />
        </span>
      </span>
      {pct != null && <span className="tabular-nums text-gray-500">{pct}%</span>}
    </span>
  );
}


function PieceCard({
  piece,
  studio,
  busy,
  lang,
  onApprove,
  onReject,
  onSubmit,
  onRetry,
  onRebuild,
  onEdit,
}: {
  piece: ContentPiece;
  /** Carries the agency timezone, so a scheduled date is shown in ITS hours. */
  studio: StudioStatus | null;
  busy: boolean;
  lang: Lang;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onSubmit: () => void;
  onRetry: () => void;
  onRebuild: () => void;
  onEdit: (body: { hook?: string; script?: string; caption?: string }) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [hook, setHook] = useState(piece.hook ?? "");
  const [script, setScript] = useState(piece.script ?? "");
  const [caption, setCaption] = useState(piece.caption ?? "");

  const submitEdit = () => {
    onEdit({ hook, script, caption });
    setEditing(false);
  };

  return (
    <li className="border border-white/10 rounded-xl p-4 bg-white/[0.02]">
      <div className="flex items-center gap-2 flex-wrap text-xs text-gray-500">
        <span className="uppercase tracking-wide">{t(`content.kind.${piece.kind}`)}</span>
        <span>·</span>
        <span className="uppercase">{piece.language}</span>
        <span>·</span>
        <span>{relativeTime(piece.created_at, lang)}</span>
        {piece.approved_by && (
          <>
            <span>·</span>
            <span className="inline-flex items-center gap-1 text-eko-green">
              <Check className="w-3 h-3" /> {piece.approved_by}
            </span>
          </>
        )}
      </div>

      {piece.media_path && (
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <video
          controls
          preload="metadata"
          className="mt-3 w-full max-h-80 rounded-lg bg-black"
          src={contentApi.mediaUrl(piece.id)}
        />
      )}

      {editing ? (
        <div className="mt-3 space-y-2">
          <input
            value={hook}
            onChange={(e) => setHook(e.target.value)}
            maxLength={300}
            placeholder={t("content.hookLabel")}
            className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-eko-violet/50"
          />
          <textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            rows={4}
            placeholder={t("content.scriptLabel")}
            className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-eko-violet/50"
          />
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={2}
            placeholder={t("content.captionLabel")}
            className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-eko-violet/50"
          />
          <div className="flex gap-2">
            <button
              onClick={submitEdit}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-eko-violet text-white text-sm font-medium hover:bg-eko-violet-dark disabled:opacity-50"
            >
              {t("content.saveEdit")}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 rounded-lg border border-white/10 text-gray-300 text-sm hover:border-white/20"
            >
              {t("content.cancel")}
            </button>
          </div>
          {piece.status === "approved" && (
            <p className="text-xs text-amber-300">{t("content.editRevokes")}</p>
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-1">
          {piece.hook && <p className="font-medium text-white">{piece.hook}</p>}
          {piece.script && (
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{piece.script}</p>
          )}
          {piece.caption && (
            <p className="text-sm text-gray-500 italic">{piece.caption}</p>
          )}
        </div>
      )}

      {piece.violations && piece.violations.length > 0 && (
        <div className="mt-3 text-sm bg-amber-500/10 border border-amber-500/20 rounded-lg p-3">
          <p className="flex items-center gap-1 font-medium text-amber-300">
            <ShieldAlert className="w-4 h-4" /> {t("content.violationsTitle")}
          </p>
          <ul className="mt-1 list-disc list-inside text-amber-200">
            {piece.violations.map((v) => (
              <li key={`${v.category}:${v.phrase}`}>
                “{v.phrase}” — {t(`content.category.${v.category}`)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {piece.render_error && (
        <p className="mt-3 text-sm text-gray-400 bg-white/[0.03] border border-white/10 rounded-lg p-3">
          <span className="text-gray-500">{t("content.renderStatus")}: </span>
          {piece.render_error}
        </p>
      )}

      <PublishSchedule piece={piece} studio={studio} />

      {piece.rejected_reason && piece.status === "rejected" && (
        <p className="mt-2 text-sm text-red-300">
          {t("content.rejectedBecause")}: {piece.rejected_reason}
        </p>
      )}

      {rejecting ? (
        <div className="mt-3 flex gap-2 items-start">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("content.rejectReason")}
            className="flex-1 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-eko-violet/50"
          />
          <button
            onClick={() => {
              if (reason.trim().length >= 3) {
                onReject(reason.trim());
                setRejecting(false);
                setReason("");
              }
            }}
            disabled={busy || reason.trim().length < 3}
            className="px-3 py-2 rounded-lg bg-red-600 text-white text-sm disabled:opacity-50"
          >
            {t("content.rejectConfirm")}
          </button>
          <button
            onClick={() => setRejecting(false)}
            className="px-3 py-2 rounded-lg border border-white/10 text-gray-300 text-sm hover:border-white/20"
          >
            {t("content.cancel")}
          </button>
        </div>
      ) : (
        <div className="mt-3 flex gap-2 flex-wrap">
          {busy ? (
            <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
          ) : (
            <>
              {piece.status === "needs_approval" && !piece.media_path && (
                // No button at all, and a reason. Approving a piece before its
                // video exists leaves it approved and empty forever: the render
                // is refused with a 409 once the piece is no longer awaiting
                // one. That happened here on 2026-09-01.
                <RenderProgress piece={piece} />
              )}
              {piece.status === "needs_approval" && piece.media_path && (
                <button
                  onClick={onApprove}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-eko-green text-eko-noir text-sm font-semibold hover:brightness-110"
                >
                  <Check className="w-4 h-4" /> {t("content.approve")}
                </button>
              )}
              {piece.status === "failed" && (
                <button
                  onClick={onRetry}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-eko-violet text-white text-sm font-semibold hover:bg-eko-violet-dark"
                >
                  <RotateCcw className="w-4 h-4" /> {t("content.retry")}
                </button>
              )}
              {piece.status === "draft" && (
                <button
                  onClick={onSubmit}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-eko-violet text-white text-sm font-medium hover:bg-eko-violet-dark"
                >
                  {t("content.submit")}
                </button>
              )}
              {piece.kind === "generated" &&
                !!piece.media_path &&
                piece.status !== "published" && (
                  <button
                    onClick={onRebuild}
                    title={t("content.rebuildHint")}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-white/10 text-gray-300 text-sm hover:border-white/20"
                  >
                    <RefreshCw className="w-4 h-4" /> {t("content.rebuild")}
                  </button>
                )}
              {(piece.status === "needs_approval" ||
                piece.status === "draft" ||
                piece.status === "approved") && (
                <>
                  <button
                    onClick={() => setEditing(true)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-white/10 text-gray-300 text-sm hover:border-white/20"
                  >
                    <Pencil className="w-4 h-4" /> {t("content.edit")}
                  </button>
                  <button
                    onClick={() => setRejecting(true)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-red-500/30 text-red-300 text-sm hover:border-red-500/50"
                  >
                    <X className="w-4 h-4" /> {t("content.reject")}
                  </button>
                </>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

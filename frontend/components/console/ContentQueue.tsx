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

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  Loader2,
  Pencil,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";
import { type ContentPiece, type ContentStatus, contentApi } from "@/lib/api";
import type { Lang } from "@/lib/i18n";
import { relativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const TABS: ContentStatus[] = ["needs_approval", "draft", "approved", "rejected"];

export function ContentQueue() {
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<ContentStatus>("needs_approval");
  const [pieces, setPieces] = useState<ContentPiece[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPieces(await contentApi.list(tab));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [tab]);

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
    <section className="mt-8">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-lg font-semibold">{t("content.title")}</h2>
        <button
          onClick={() => void load()}
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800"
        >
          <RefreshCw className="w-4 h-4" /> {t("content.refresh")}
        </button>
      </div>
      <p className="text-sm text-gray-500 mt-1">{t("content.subtitle")}</p>

      <div className="mt-3 flex gap-2 flex-wrap" role="tablist">
        {TABS.map((status) => (
          <button
            key={status}
            role="tab"
            aria-selected={tab === status}
            onClick={() => setTab(status)}
            className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
              tab === status
                ? "bg-gray-900 text-white border-gray-900"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-500"
            }`}
          >
            {t(`content.tab.${status}`)}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="break-words">{error}</span>
        </div>
      )}

      {pieces === null ? (
        <div className="mt-6 flex justify-center text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : pieces.length === 0 ? (
        <p className="mt-6 text-sm text-gray-400">{t("content.empty")}</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {pieces.map((piece) => (
            <PieceCard
              key={piece.id}
              piece={piece}
              busy={busyId === piece.id}
              lang={lang}
              onApprove={() => act(piece.id, () => contentApi.approve(piece.id))}
              onReject={(reason) =>
                act(piece.id, () => contentApi.reject(piece.id, reason))
              }
              onSubmit={() => act(piece.id, () => contentApi.submit(piece.id))}
              onEdit={(body) => act(piece.id, () => contentApi.edit(piece.id, body))}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function PieceCard({
  piece,
  busy,
  lang,
  onApprove,
  onReject,
  onSubmit,
  onEdit,
}: {
  piece: ContentPiece;
  busy: boolean;
  lang: Lang;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onSubmit: () => void;
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
    <li className="border border-gray-200 rounded-xl p-4 bg-white shadow-sm">
      <div className="flex items-center gap-2 flex-wrap text-xs text-gray-500">
        <span className="uppercase tracking-wide">{t(`content.kind.${piece.kind}`)}</span>
        <span>·</span>
        <span className="uppercase">{piece.language}</span>
        <span>·</span>
        <span>{relativeTime(piece.created_at, lang)}</span>
        {piece.approved_by && (
          <>
            <span>·</span>
            <span className="inline-flex items-center gap-1 text-green-700">
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
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            rows={4}
            placeholder={t("content.scriptLabel")}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={2}
            placeholder={t("content.captionLabel")}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <button
              onClick={submitEdit}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-gray-900 text-white text-sm disabled:opacity-50"
            >
              {t("content.saveEdit")}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 rounded-lg border border-gray-300 text-sm"
            >
              {t("content.cancel")}
            </button>
          </div>
          {piece.status === "approved" && (
            <p className="text-xs text-amber-700">{t("content.editRevokes")}</p>
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-1">
          {piece.hook && <p className="font-medium">{piece.hook}</p>}
          {piece.script && (
            <p className="text-sm text-gray-600 whitespace-pre-wrap">{piece.script}</p>
          )}
          {piece.caption && (
            <p className="text-sm text-gray-500 italic">{piece.caption}</p>
          )}
        </div>
      )}

      {piece.violations && piece.violations.length > 0 && (
        <div className="mt-3 text-sm bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="flex items-center gap-1 font-medium text-amber-800">
            <ShieldAlert className="w-4 h-4" /> {t("content.violationsTitle")}
          </p>
          <ul className="mt-1 list-disc list-inside text-amber-800">
            {piece.violations.map((v) => (
              <li key={`${v.category}:${v.phrase}`}>
                “{v.phrase}” — {t(`content.category.${v.category}`)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {piece.rejected_reason && piece.status === "rejected" && (
        <p className="mt-2 text-sm text-red-700">
          {t("content.rejectedBecause")}: {piece.rejected_reason}
        </p>
      )}

      {rejecting ? (
        <div className="mt-3 flex gap-2 items-start">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("content.rejectReason")}
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
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
            className="px-3 py-2 rounded-lg border border-gray-300 text-sm"
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
              {piece.status === "needs_approval" && (
                <button
                  onClick={onApprove}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-green-600 text-white text-sm"
                >
                  <Check className="w-4 h-4" /> {t("content.approve")}
                </button>
              )}
              {piece.status === "draft" && (
                <button
                  onClick={onSubmit}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-gray-900 text-white text-sm"
                >
                  {t("content.submit")}
                </button>
              )}
              {(piece.status === "needs_approval" ||
                piece.status === "draft" ||
                piece.status === "approved") && (
                <>
                  <button
                    onClick={() => setEditing(true)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-300 text-sm"
                  >
                    <Pencil className="w-4 h-4" /> {t("content.edit")}
                  </button>
                  <button
                    onClick={() => setRejecting(true)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-red-300 text-red-700 text-sm"
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

"use client";

/**
 * The way a clip gets into the studio.
 *
 * The endpoint has existed since v0.52 and nothing ever called it: the API
 * client had no `upload` and no component referenced one, so the recorded lane
 * — an agent filming on her phone, which is half the product — had a back door
 * and no front one.
 *
 * No `capture` attribute on the input. With it, a phone goes straight to the
 * camera and refuses to offer the library, which inverts the real workflow:
 * she films first and uploads later, often not the same day. Without it, iOS
 * offers Photo Library / Take Video / Choose File and the camera is still one
 * tap away.
 */

import { useRef, useState } from "react";
import { AlertCircle, Loader2, Upload } from "lucide-react";
import { type UploadFailure, contentApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function UploadClip({
  onUploaded,
  maxMb,
}: {
  onUploaded: () => void;
  maxMb?: number;
}) {
  const { t, lang } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [language, setLanguage] = useState<"en" | "es">("en");
  const [percent, setPercent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = percent !== null;

  async function send(file: File) {
    setError(null);
    setPercent(0);
    try {
      await contentApi.upload(file, language, setPercent, maxMb);
      onUploaded();
    } catch (err) {
      // The server's own words where there are any — 415 is "that is not a
      // video", 400 is "empty", and those are different fixes. The size
      // refusal usually comes from the body-size middleware or a proxy rather
      // than from the route, so it may arrive as `body_too_large` or as an
      // HTML page; `xhrDetail` falls back to the raw body for that reason.
      // Our own client failures arrive as `upload:<kind>` so they can be said
      // in the reader's language instead of hard-coded English in the API layer.
      const raw = err instanceof Error ? err.message : String(err);
      if (raw.startsWith("upload:")) {
        // `upload:<kind>` or `upload:<kind>:<detail>…`. Only `tooLarge` carries
        // detail today, and it carries the two numbers the sentence needs: a
        // limit without the file's own size leaves the person guessing which
        // clip to blame, and a size without the limit gives them nothing to
        // aim at.
        const [kind, ...detail] = raw.slice("upload:".length).split(":");
        // Formatted in the reader's language, not with a bare `toFixed`. In
        // Spanish the dot is the THOUSANDS separator, so "143.7 MB" reads as a
        // hundred and forty-three thousand megabytes — a number so absurd it
        // reads as a bug in us rather than as a clip to trim. `toLocaleString`
        // gives "143,7" there and "143.7" in English.
        const asNumber = (raw2: string | undefined) => {
          const n = Number(raw2);
          return Number.isFinite(n)
            ? n.toLocaleString(lang, { maximumFractionDigits: 1 })
            : (raw2 ?? "");
        };
        // A refusal with no limit to name gets its own sentence rather than
        // "the limit is  MB". The number is missing only when the status GET
        // failed AND the 413 came from a proxy's HTML page instead of us —
        // rare, but the message has to still be a sentence when it happens.
        const key =
          kind === "tooLarge" && !detail[1]
            ? "content.upload.tooLargeUnknown"
            : `content.upload.${kind as UploadFailure}`;
        setError(
          t(key, {
            size: asNumber(detail[0]),
            limit: asNumber(detail[1]),
          }),
        );
      } else {
        setError(raw);
      }
    } finally {
      setPercent(null);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as "en" | "es")}
          disabled={busy}
          aria-label={t("content.uploadLanguage")}
          className="px-2 py-1.5 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50 disabled:opacity-50"
        >
          <option value="en" className="bg-eko-noir">EN</option>
          <option value="es" className="bg-eko-noir">ES</option>
        </select>

        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-eko-violet text-white text-sm font-medium hover:bg-eko-violet-dark disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Upload className="w-4 h-4" />
          )}
          {busy ? `${percent}%` : t("content.uploadClip")}
        </button>

        {/* The cap, before the file picker opens. `StudioStatus` carries this
            number precisely so the choice can be informed; showing it only in
            the refusal would mean the person still learns it by being told
            "no" — which is the thing this phase set out to stop. Hidden while
            uploading, where it is noise, and when the status GET failed, where
            we would be inventing it. */}
        {!busy && maxMb !== undefined && (
          <span className="text-xs text-gray-500 whitespace-nowrap">
            {t("content.upload.limitHint", { limit: maxMb })}
          </span>
        )}

        <input
          ref={input}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file);
          }}
        />
      </div>

      {busy && (
        <div
          className="w-48 h-1 rounded-full bg-white/10 overflow-hidden"
          role="progressbar"
          aria-valuenow={percent ?? 0}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-eko-violet transition-[width] duration-200"
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {error && (
        <p className="flex items-start gap-1.5 text-xs text-red-300 max-w-sm text-right">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="break-words">{error}</span>
        </p>
      )}
    </div>
  );
}

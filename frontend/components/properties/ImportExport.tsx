"use client";

import { useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { type ListingImportResult, propertiesApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * Upload a REcolorado Matrix "Full" export.
 *
 * There is no MLS API behind this product, so this is how listings get in: a
 * person runs the search in Matrix under her own subscription, exports, and
 * drops the file here. The steps are printed on the screen rather than left to
 * memory, because the default format in Matrix is "Single Line" — which the
 * importer refuses, correctly, and which is the mistake somebody makes once a
 * month otherwise.
 */
export function ImportExport() {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ListingImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await propertiesApi.importExport(file));
    } catch (err: unknown) {
      setError(String((err as Error)?.message || err));
    } finally {
      setBusy(false);
      // Cleared so picking the SAME file again still fires a change event —
      // which is exactly what happens when somebody fixes the export format
      // and re-downloads it under the same name.
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 mb-6">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-eko-violet/20 text-eko-violet border border-eko-violet/30 text-sm disabled:opacity-40"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
          {busy ? t("import.working") : t("import.button")}
        </button>
        <span className="text-[12px] text-gray-500">{t("import.how")}</span>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          onChange={onPick}
          className="hidden"
        />
      </div>

      {result && (
        <div className="mt-3 text-[13px] text-eko-green">
          {t("import.done")
            .replace("{created}", String(result.created))
            .replace("{updated}", String(result.updated))
            .replace("{skipped}", String(result.skipped))}
        </div>
      )}
      {error && <div className="mt-3 text-[13px] text-red-400">{error}</div>}
    </div>
  );
}

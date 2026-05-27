"use client";

import { useRef, useState } from "react";
import { FileUp, Loader2, Upload } from "lucide-react";
import { type BusinessLead, discoveryApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ResultsList } from "@/components/discovery/ResultsList";

export function FileImport() {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [results, setResults] = useState<BusinessLead[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  async function handleFile(file: File) {
    setLoading(true);
    setError(null);
    setResults(null);
    setFileName(file.name);
    try {
      const res = await discoveryApi.upload(file);
      setResults(res.results);
    } catch (err: unknown) {
      setError(`${t("discovery.fileError")}: ${String((err as Error)?.message || err)}`);
    } finally {
      setLoading(false);
    }
  }

  function onInput(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  }

  return (
    <section className="rounded-2xl border border-white/5 bg-white/[0.02] p-5">
      <h2 className="text-sm font-semibold text-white mb-1 inline-flex items-center gap-2">
        <FileUp className="w-4 h-4 text-eko-violet" /> {t("discovery.fileTitle")}
      </h2>
      <p className="text-xs text-gray-500 mb-4">{t("discovery.fileHint")}</p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={
          "cursor-pointer rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors " +
          (dragOver ? "border-eko-violet/50 bg-eko-violet/[0.06]" : "border-white/10 hover:border-white/20")
        }
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.csv,.tsv,.html,.htm,.xlsx,.xlsm,.json,image/*"
          onChange={onInput}
          className="hidden"
        />
        {loading ? (
          <div className="flex items-center justify-center gap-2 text-gray-400 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> {t("discovery.uploading")}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 text-gray-500">
            <Upload className="w-6 h-6" />
            <span className="text-sm">
              <span className="text-eko-violet font-medium">{t("discovery.chooseFile")}</span>
            </span>
            <span className="text-[11px] text-gray-600">PDF · JPG/PNG · TXT · CSV · XLSX · HTML</span>
            {fileName && <span className="text-[11px] text-gray-500 mt-1">{fileName}</span>}
          </div>
        )}
      </div>

      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 mt-4">
          {error}
        </div>
      )}

      {results !== null && (
        <div className="mt-5">
          <ResultsList leads={results} emptyKey="discovery.fileNone" sourceLabel="file-import" />
        </div>
      )}
    </section>
  );
}

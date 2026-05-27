"use client";

import { useMemo, useState } from "react";
import { Check, Loader2, Mail, MapPin, Phone, UserPlus } from "lucide-react";
import { type BusinessLead, type ImportResult, discoveryApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function keyOf(b: BusinessLead, i: number): string {
  return `${b.phone || b.email || b.business_name || "row"}-${i}`;
}

export function ResultsList({
  leads,
  emptyKey,
  sourceLabel,
}: {
  leads: BusinessLead[];
  emptyKey: string;
  sourceLabel: string;
}) {
  const { t } = useI18n();
  const keys = useMemo(() => leads.map(keyOf), [leads]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(keys));
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (leads.length === 0) {
    return (
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-8 text-center text-gray-500 text-sm">
        {t(emptyKey)}
      </div>
    );
  }

  const allSelected = selected.size === leads.length;

  function toggle(k: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(keys));
  }

  async function handleImport() {
    const chosen = leads.filter((_, i) => selected.has(keys[i]));
    if (importing || chosen.length === 0) return;
    setImporting(true);
    setError(null);
    setResult(null);
    try {
      const res = await discoveryApi.import(chosen, sourceLabel);
      setResult(res);
    } catch (err: unknown) {
      setError(String((err as Error)?.message || err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <button
          type="button"
          onClick={toggleAll}
          className="text-xs text-gray-400 hover:text-white inline-flex items-center gap-1.5"
        >
          <span
            className={
              "w-4 h-4 rounded border flex items-center justify-center " +
              (allSelected ? "bg-eko-violet/20 border-eko-violet/50" : "border-white/15")
            }
          >
            {allSelected && <Check className="w-3 h-3 text-eko-violet" />}
          </span>
          {t("discovery.selectAll")}
        </button>
        <span className="text-[11px] text-gray-600">
          {leads.length} {t("discovery.results")}
        </span>
      </div>

      <ul className="space-y-1.5 mb-4">
        {leads.map((b, i) => {
          const k = keys[i];
          const on = selected.has(k);
          return (
            <li key={k}>
              <button
                type="button"
                onClick={() => toggle(k)}
                className={
                  "w-full text-left flex items-start gap-3 px-3 py-2.5 rounded-lg border transition-colors " +
                  (on ? "border-eko-violet/30 bg-eko-violet/[0.06]" : "border-white/5 bg-white/[0.02] hover:bg-white/[0.04]")
                }
              >
                <span
                  className={
                    "mt-0.5 w-4 h-4 rounded border flex items-center justify-center shrink-0 " +
                    (on ? "bg-eko-violet/20 border-eko-violet/50" : "border-white/15")
                  }
                >
                  {on && <Check className="w-3 h-3 text-eko-violet" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-white truncate">{b.business_name}</span>
                    <span className="text-[10px] uppercase tracking-wider text-gray-600 px-1.5 py-0.5 rounded bg-white/5">
                      {t(`discovery.source.${b.source}`) || b.source}
                    </span>
                    {b.category && <span className="text-[11px] text-gray-500">{b.category}</span>}
                  </span>
                  <span className="mt-1 flex items-center gap-3 flex-wrap text-[11px] text-gray-500">
                    {b.phone && (
                      <span className="inline-flex items-center gap-1">
                        <Phone className="w-3 h-3" /> {b.phone}
                      </span>
                    )}
                    {b.email && (
                      <span className="inline-flex items-center gap-1">
                        <Mail className="w-3 h-3" /> {b.email}
                      </span>
                    )}
                    {(b.city || b.address) && (
                      <span className="inline-flex items-center gap-1">
                        <MapPin className="w-3 h-3" /> {b.address || b.city}
                      </span>
                    )}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 mb-3">
          {error}
        </div>
      )}
      {result && (
        <div className="text-sm text-green-300 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20 mb-3">
          {t("discovery.imported", { created: result.created, skipped: result.skipped })}
        </div>
      )}

      <button
        type="button"
        onClick={handleImport}
        disabled={importing || selected.size === 0}
        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20 disabled:opacity-50"
      >
        {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
        {importing ? t("discovery.importing") : `${t("discovery.importSelected")} (${selected.size})`}
      </button>
    </>
  );
}

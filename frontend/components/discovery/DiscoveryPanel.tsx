"use client";

import { useState } from "react";
import { Loader2, Search } from "lucide-react";
import {
  type BusinessLead,
  type DiscoverySource,
  discoveryApi,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ResultsList } from "@/components/discovery/ResultsList";

const SOURCES: DiscoverySource[] = ["google_maps", "yelp", "linkedin", "colorado_sos"];

export function DiscoveryPanel() {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [city, setCity] = useState("Denver");
  const [state, setState] = useState("CO");
  const [maxResults, setMaxResults] = useState("50");
  const [sources, setSources] = useState<DiscoverySource[]>([...SOURCES]);

  const [results, setResults] = useState<BusinessLead[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleSource(s: DiscoverySource) {
    setSources((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (loading || !query.trim() || sources.length === 0) return;
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const res = await discoveryApi.search({
        query: query.trim(),
        city: city.trim(),
        state: state.trim() || "CO",
        max_results: Math.min(100, Math.max(1, Number(maxResults) || 50)),
        sources,
      });
      setResults(res.results);
    } catch (err: unknown) {
      setError(String((err as Error)?.message || err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-2xl border border-white/5 bg-white/[0.02] p-5 mb-6">
      <h2 className="text-sm font-semibold text-white mb-4 inline-flex items-center gap-2">
        <Search className="w-4 h-4 text-eko-violet" /> {t("discovery.searchTitle")}
      </h2>

      <form onSubmit={handleSearch}>
        <label className="block mb-3">
          <span className="text-[10px] uppercase tracking-wider text-gray-600">{t("discovery.query")}</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("discovery.queryPlaceholder")}
            className="mt-1 block w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
          />
        </label>

        <div className="flex flex-wrap items-end gap-3 mb-4">
          <label className="block">
            <span className="text-[10px] uppercase tracking-wider text-gray-600">{t("discovery.city")}</span>
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              className="mt-1 block w-40 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <label className="block">
            <span className="text-[10px] uppercase tracking-wider text-gray-600">{t("discovery.state")}</span>
            <input
              value={state}
              onChange={(e) => setState(e.target.value.toUpperCase().slice(0, 2))}
              className="mt-1 block w-20 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <label className="block">
            <span className="text-[10px] uppercase tracking-wider text-gray-600">{t("discovery.maxResults")}</span>
            <input
              value={maxResults}
              onChange={(e) => setMaxResults(e.target.value.replace(/[^0-9]/g, ""))}
              className="mt-1 block w-24 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
            />
          </label>
        </div>

        <div className="mb-4">
          <span className="text-[10px] uppercase tracking-wider text-gray-600">{t("discovery.sources")}</span>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {SOURCES.map((s) => {
              const on = sources.includes(s);
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => toggleSource(s)}
                  className={
                    "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors " +
                    (on
                      ? "border-eko-violet/40 bg-eko-violet/15 text-eko-violet"
                      : "border-white/10 text-gray-500 hover:text-gray-300 hover:bg-white/5")
                  }
                >
                  {t(`discovery.source.${s}`)}
                </button>
              );
            })}
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !query.trim() || sources.length === 0}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {loading ? t("discovery.searching") : t("discovery.search")}
        </button>
      </form>

      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 mt-4">
          {error}
        </div>
      )}

      {results !== null && (
        <div className="mt-5">
          <ResultsList
            leads={results}
            emptyKey="discovery.empty"
            sourceLabel="discovery"
          />
        </div>
      )}
    </section>
  );
}

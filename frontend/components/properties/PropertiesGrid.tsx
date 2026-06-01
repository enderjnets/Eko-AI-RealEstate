"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownWideNarrow, Clock, Loader2, RefreshCw, Search, X } from "lucide-react";
import { type Property, propertiesApi } from "@/lib/api";
import { PropertyCard } from "@/components/properties/PropertyCard";
import { useI18n } from "@/lib/i18n";

type Sort = "price" | "recent";

function num(v: string | null): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

export function PropertiesGrid() {
  const { t } = useI18n();
  const [items, setItems] = useState<Property[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [maxPrice, setMaxPrice] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const searchRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await propertiesApi.list({ status: "active", limit: 200 });
      setItems(res.items);
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function handleSync() {
    if (syncing) return;
    setSyncing(true);
    setError(null);
    try {
      await propertiesApi.sync();
      await load();
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setSyncing(false);
    }
  }

  const types = useMemo(() => {
    const set = new Set<string>();
    for (const p of items) if (p.property_type) set.add(p.property_type);
    return Array.from(set).sort();
  }, [items]);

  const typeLabel = (key: string) => {
    const label = t(`propType.${key}`);
    return label === `propType.${key}` ? key : label; // fall back to raw value
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const cap = maxPrice.trim() ? Number(maxPrice) : null;
    const out = items.filter((p) => {
      if (type !== "all" && p.property_type !== type) return false;
      if (cap != null) {
        const price = num(p.price);
        if (price == null || price > cap) return false;
      }
      if (q) {
        const hay = [p.title, p.address, p.city, p.zone, p.property_type]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    out.sort((a, b) => {
      if (sort === "price") return (num(b.price) ?? -1) - (num(a.price) ?? -1);
      const at = a.listed_at || a.created_at;
      const bt = b.listed_at || b.created_at;
      return bt.localeCompare(at);
    });
    return out;
  }, [items, query, type, maxPrice, sort]);

  const segBtn = (active: boolean) =>
    `inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium transition-colors ${
      active ? "bg-eko-violet/20 text-eko-violet" : "text-gray-400 hover:bg-white/5"
    }`;

  return (
    <>
      {/* Toolbar */}
      <div className="mb-4">
        <div className="flex items-center gap-3 mb-3 flex-wrap sm:flex-nowrap">
          <div className="relative flex items-center flex-1 min-w-full sm:min-w-0">
            <Search className="w-3.5 h-3.5 text-gray-600 absolute left-3 pointer-events-none" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("properties.search.placeholder")}
              className="w-full bg-white/[0.03] border border-white/10 rounded-lg text-sm text-white placeholder-gray-600 pl-9 pr-9 py-2 focus:outline-none focus:border-eko-violet/50 focus:bg-white/[0.04] transition-colors"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery("")}
                title={t("properties.search.clear")}
                className="absolute right-2 w-[22px] h-[22px] flex items-center justify-center rounded-md bg-white/5 text-gray-400 hover:text-white hover:bg-white/10"
              >
                <X className="w-3 h-3" />
              </button>
            ) : (
              <kbd className="absolute right-2.5 font-mono text-[10px] text-gray-500 bg-white/5 border border-white/10 rounded px-1.5 leading-relaxed">
                /
              </kbd>
            )}
          </div>
          <input
            value={maxPrice}
            onChange={(e) => setMaxPrice(e.target.value.replace(/[^0-9]/g, ""))}
            inputMode="numeric"
            placeholder={t("properties.maxPrice")}
            className="w-full sm:w-36 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
          />
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20 disabled:opacity-60"
            title={t("properties.syncTitle")}
          >
            {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            {t("properties.sync")}
          </button>
        </div>
        <div className="flex items-center gap-2 justify-between flex-wrap">
          <div className="flex items-center gap-1.5 flex-nowrap overflow-x-auto sm:flex-wrap pb-1 sm:pb-0">
            {["all", ...types].map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setType(key)}
                className={`shrink-0 whitespace-nowrap text-[11px] font-medium px-3 py-1.5 rounded-full border transition-colors ${
                  type === key
                    ? "bg-eko-violet/15 border-eko-violet/30 text-violet-300"
                    : "bg-white/[0.03] border-white/10 text-gray-400 hover:text-gray-100 hover:border-white/20"
                }`}
              >
                {key === "all" ? t("properties.filter.all") : typeLabel(key)}
              </button>
            ))}
          </div>
          <div className="inline-flex rounded-lg border border-white/10 overflow-hidden shrink-0">
            <button type="button" onClick={() => setSort("recent")} className={segBtn(sort === "recent")}>
              <Clock className="w-3 h-3" />
              {t("properties.sort.recent")}
            </button>
            <button type="button" onClick={() => setSort("price")} className={segBtn(sort === "price")}>
              <ArrowDownWideNarrow className="w-3 h-3" />
              {t("properties.sort.price")}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> {t("properties.loading")}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-12 text-center text-gray-500 text-sm">
          {t("properties.empty.pre")} <strong className="text-gray-300">{t("properties.sync")}</strong>{" "}
          {t("properties.empty.post")}
        </div>
      ) : (
        <>
          <div className="text-[11px] text-gray-600 mb-3">
            <strong className="text-gray-300 font-bold">{visible.length}</strong> {t("leads.of")} {items.length}{" "}
            {t("properties.activeCount")}
          </div>
          {visible.length === 0 ? (
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-10 text-center text-gray-500 text-sm flex flex-col items-center gap-3">
              <Search className="w-6 h-6 text-gray-600" />
              <p>{t("properties.noMatch")}</p>
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setType("all");
                  setMaxPrice("");
                }}
                className="text-xs px-3 py-1.5 rounded-md border border-white/10 text-gray-400 hover:text-white hover:bg-white/5"
              >
                {t("leads.clearFilters")}
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {visible.map((p) => (
                <PropertyCard key={p.id} p={p} />
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}

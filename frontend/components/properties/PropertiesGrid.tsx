"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Search } from "lucide-react";
import { type Property, type PropertyFilters, propertiesApi } from "@/lib/api";
import { PropertyCard } from "@/components/properties/PropertyCard";

export function PropertiesGrid() {
  const [items, setItems] = useState<Property[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [zone, setZone] = useState("");
  const [maxPrice, setMaxPrice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const filters: PropertyFilters = { status: "active", limit: 100 };
    if (zone.trim()) filters.zone = zone.trim();
    if (maxPrice.trim() && !Number.isNaN(Number(maxPrice))) filters.max_price = Number(maxPrice);
    try {
      const res = await propertiesApi.list(filters);
      setItems(res.items);
      setTotal(res.total);
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setLoading(false);
    }
  }, [zone, maxPrice]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSync() {
    if (syncing) return;
    setSyncing(true);
    try {
      await propertiesApi.sync();
      await load();
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-end gap-3 mb-5">
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-gray-600">Zona</span>
          <input
            value={zone}
            onChange={(e) => setZone(e.target.value)}
            placeholder="Brickell, Doral…"
            className="mt-1 block w-44 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
          />
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-gray-600">Precio máx.</span>
          <input
            value={maxPrice}
            onChange={(e) => setMaxPrice(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder="850000"
            className="mt-1 block w-36 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
          />
        </label>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-white/10 text-gray-300 hover:bg-white/5"
        >
          <Search className="w-3.5 h-3.5" /> Filtrar
        </button>
        <button
          type="button"
          onClick={handleSync}
          disabled={syncing}
          className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20 disabled:opacity-60"
          title="Importar listings del feed MLS/IDX configurado"
        >
          {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Sincronizar MLS
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Cargando propiedades…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-12 text-center text-gray-500 text-sm">
          No hay propiedades. Pulsá <strong className="text-gray-300">Sincronizar MLS</strong> para importar listings.
        </div>
      ) : (
        <>
          <div className="text-[11px] text-gray-600 mb-3">{total} propiedades activas</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((p) => (
              <PropertyCard key={p.id} p={p} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { LeadIntent, LeadStatus } from "@/lib/api";

const STATUSES: { value: LeadStatus | ""; label: string }[] = [
  { value: "", label: "Todos los estados" },
  { value: "new", label: "Nuevo" },
  { value: "qualified", label: "Cualificado" },
  { value: "visiting", label: "Visitando" },
  { value: "post_visit", label: "Post-visita" },
  { value: "won", label: "Cerrado" },
  { value: "lost", label: "Perdido" },
  { value: "paused", label: "Pausado" },
];

const INTENTS: { value: LeadIntent | ""; label: string }[] = [
  { value: "", label: "Todas las intenciones" },
  { value: "rent", label: "Alquiler" },
  { value: "buy", label: "Compra" },
  { value: "valuation", label: "Tasación" },
  { value: "other", label: "Otro" },
];

export function FilterBar() {
  const router = useRouter();
  const params = useSearchParams();
  const currentStatus = params.get("status") ?? "";
  const currentIntent = params.get("intent") ?? "";

  function update(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.push(`/leads${next.toString() ? `?${next.toString()}` : ""}`);
  }

  return (
    <div className="flex flex-wrap gap-2 items-center mb-4">
      <select
        value={currentStatus}
        onChange={(e) => update("status", e.target.value)}
        className="px-3 py-1.5 rounded-md bg-white/5 border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
      >
        {STATUSES.map((o) => (
          <option key={o.value} value={o.value} className="bg-eko-noir">
            {o.label}
          </option>
        ))}
      </select>
      <select
        value={currentIntent}
        onChange={(e) => update("intent", e.target.value)}
        className="px-3 py-1.5 rounded-md bg-white/5 border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
      >
        {INTENTS.map((o) => (
          <option key={o.value} value={o.value} className="bg-eko-noir">
            {o.label}
          </option>
        ))}
      </select>
      {(currentStatus || currentIntent) && (
        <button
          type="button"
          onClick={() => router.push("/leads")}
          className="px-3 py-1.5 rounded-md text-xs text-gray-400 hover:text-white border border-white/10 hover:bg-white/5"
        >
          Limpiar filtros
        </button>
      )}
    </div>
  );
}

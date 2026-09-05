"use client";

/**
 * The small pieces every card on `/analytics` is built from.
 *
 * No charting library, on purpose: this page draws bars and one column chart,
 * and the smallest sensible library is larger than the whole page. The repo has
 * none today and this is not the feature to introduce one for.
 */

import type { ReactNode } from "react";
import type { Breakdown } from "@/lib/api";

export function Card({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        {hint && <p className="text-[11px] text-gray-500 mt-0.5">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-xs text-gray-500 py-2">{children}</p>;
}

export function Bar({
  label,
  value,
  max,
  secondary,
  color = "bg-eko-violet",
}: {
  label: string;
  value: number;
  max: number;
  secondary?: string;
  color?: string;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-24 sm:w-28 text-gray-400 truncate shrink-0" title={label}>
        {label}
      </span>
      <div className="flex-1 h-5 rounded bg-white/[0.04] overflow-hidden min-w-0">
        {/* A visible sliver for any non-zero value: a bar of width 0 for a real
            number reads as "nothing here", which is a different fact. */}
        <div className={`h-full ${color}`} style={{ width: `${Math.max(pct, value > 0 ? 4 : 0)}%` }} />
      </div>
      <span className="w-14 text-right text-gray-300 tabular-nums text-xs shrink-0">
        {value}
        {secondary && <span className="text-gray-600"> {secondary}</span>}
      </span>
    </div>
  );
}

/** A named list with counts, from either a `Breakdown[]` or a plain map. */
export function Bars({
  rows,
  empty,
  label,
}: {
  rows: { name: string; value: number; secondary?: string }[];
  empty: string;
  label?: (name: string) => string;
}) {
  if (rows.length === 0) return <Empty>{empty}</Empty>;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <Bar
          key={r.name}
          label={label ? label(r.name) : r.name}
          value={r.value}
          max={max}
          secondary={r.secondary}
        />
      ))}
    </div>
  );
}

export const fromBreakdown = (rows: Breakdown[]) =>
  rows.map((r) => ({
    name: r.name,
    value: r.sessions,
    secondary: r.leads > 0 ? `· ${r.leads}` : undefined,
  }));

export const fromMap = (map: Record<string, number>) =>
  Object.entries(map)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

/** Seconds as something a person reads without converting in their head. */
export function duration(seconds: number | null | undefined, unit: (k: string) => string) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} ${unit("s")}`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} ${unit("min")}`;
  return `${(seconds / 3600).toFixed(1)} ${unit("h")}`;
}

"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronRight,
  Clock,
  Flame,
  Globe,
  Loader2,
  Mail,
  MessageCircle,
  Search,
  User2,
  X,
} from "lucide-react";
import { type Lead, type LeadStatus, leadsApi } from "@/lib/api";
import { formatBudget, relativeTime } from "@/lib/format";
import { IntentBadge, StatusBadge } from "@/components/ui/Badge";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { AddLeadButton } from "@/components/leads/AddLeadButton";
import { useI18n } from "@/lib/i18n";

type Sort = "priority" | "recent";
type QuickFilter = "all" | "hot" | "pending" | LeadStatus;

const CHIP_FILTERS: { id: QuickFilter; labelKey: string }[] = [
  { id: "all", labelKey: "leads.filter.all" },
  { id: "hot", labelKey: "leads.filter.hot" },
  { id: "pending", labelKey: "leads.filter.pending" },
  { id: "new", labelKey: "status.new" },
  { id: "qualified", labelKey: "status.qualified" },
  { id: "visiting", labelKey: "status.visiting" },
  { id: "won", labelKey: "status.won" },
];

function channelGlyph(identifier: string): typeof MessageCircle {
  if (identifier.startsWith("discovery:")) return Search;
  if (identifier.startsWith("http")) return Globe;
  return identifier.includes("@") ? Mail : MessageCircle;
}

function displayIdentifier(identifier: string): string {
  if (identifier.startsWith("discovery:")) return "—";
  if (identifier.startsWith("http")) return identifier.replace(/^https?:\/\/(www\.)?/, "");
  return identifier;
}

export function LeadsExplorer() {
  const { t, lang } = useI18n();
  const [data, setData] = useState<{ total: number; items: Lead[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<QuickFilter>("all");
  const [sort, setSort] = useState<Sort>("priority");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    leadsApi
      .list({ sort: sort === "priority" ? "score" : "recent", limit: 200 })
      .then((d) => setData(d))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [sort]);

  // "/" focuses the search from anywhere (unless already typing in a field).
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

  const visible = useMemo(() => {
    const items = data?.items ?? [];
    const q = query.trim().toLowerCase();
    return items.filter((l) => {
      if (filter === "hot" && l.score < 67) return false;
      if (filter === "pending" && !l.needs_response) return false;
      if (
        (filter === "new" || filter === "qualified" || filter === "visiting" || filter === "won") &&
        l.status !== filter
      )
        return false;
      if (q) {
        const hay = [l.name, l.zone, displayIdentifier(l.phone), l.intent, l.property_type]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [data, query, filter]);

  return (
    <div>
      {/* Toolbar — search + sort + add */}
      <div className="mb-3.5">
        <div className="flex items-center gap-3 mb-3 flex-wrap sm:flex-nowrap">
          <div className="relative flex items-center flex-1 min-w-full sm:min-w-0">
            <Search className="w-3.5 h-3.5 text-gray-600 absolute left-3 pointer-events-none" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("leads.search.placeholder")}
              className="w-full bg-white/[0.03] border border-white/10 rounded-lg text-sm text-white placeholder-gray-600 pl-9 pr-9 py-2 focus:outline-none focus:border-eko-violet/50 focus:bg-white/[0.04] transition-colors"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery("")}
                title={t("leads.search.clear")}
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
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 hidden sm:inline">
              {t("leads.sort")}
            </span>
            <div className="inline-flex rounded-lg border border-white/10 overflow-hidden">
              <button
                type="button"
                onClick={() => setSort("priority")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium transition-colors ${
                  sort === "priority" ? "bg-eko-violet/20 text-eko-violet" : "text-gray-400 hover:bg-white/5"
                }`}
              >
                <Flame className="w-3 h-3" />
                {t("leads.sort.priority")}
              </button>
              <button
                type="button"
                onClick={() => setSort("recent")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium transition-colors ${
                  sort === "recent" ? "bg-eko-violet/20 text-eko-violet" : "text-gray-400 hover:bg-white/5"
                }`}
              >
                <Clock className="w-3 h-3" />
                {t("leads.sort.recent")}
              </button>
            </div>
          </div>
          <AddLeadButton />
        </div>
        <div className="flex items-center gap-1.5 flex-nowrap overflow-x-auto sm:flex-wrap pb-1 sm:pb-0">
          {CHIP_FILTERS.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setFilter(c.id)}
              className={`shrink-0 whitespace-nowrap text-[11px] font-medium px-3 py-1.5 rounded-full border transition-colors ${
                filter === c.id
                  ? "bg-eko-violet/15 border-eko-violet/30 text-violet-300"
                  : "bg-white/[0.03] border-white/10 text-gray-400 hover:text-gray-100 hover:border-white/20"
              }`}
            >
              {t(c.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      {loading && !data ? (
        <div className="flex items-center gap-2 text-gray-400 text-sm py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t("leads.loading")}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-300">
          {t("leads.error")}: {error}
        </div>
      ) : (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] overflow-hidden">
          <div className="px-4 py-2 border-b border-white/5 text-[10px] uppercase tracking-wider text-gray-500 flex justify-between">
            <span>
              <strong className="text-gray-200 font-bold">{visible.length}</strong> {t("leads.of")}{" "}
              {data?.items.length ?? 0}{" "}
              {(data?.items.length ?? 0) === 1 ? t("leads.count.one") : t("leads.count.other")} ·{" "}
              {sort === "priority" ? t("leads.sortedByPriority") : t("leads.sortedByRecent")}
            </span>
            <span>{t("leads.lastActivity")}</span>
          </div>
          <ul className="divide-y divide-white/5">
            {visible.map((lead) => {
              const budget = formatBudget(lead.budget_min, lead.budget_max, lang);
              const isHot = lead.score >= 67;
              const Glyph = channelGlyph(lead.phone);
              return (
                <li key={lead.id}>
                  <Link
                    href={`/leads/${lead.id}`}
                    className="group relative flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03] transition-colors"
                  >
                    {isHot && (
                      <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r bg-gradient-to-b from-red-400 to-amber-400" />
                    )}
                    <div className="shrink-0 w-12 flex justify-center">
                      <ScoreBadge score={lead.score} />
                    </div>
                    <div className="w-9 h-9 rounded-full bg-eko-violet/10 border border-eko-violet/20 flex items-center justify-center shrink-0">
                      <User2 className="w-4 h-4 text-eko-violet" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-white text-sm">
                          {lead.name || t("common.noName")}
                        </span>
                        <Glyph className="w-3 h-3 text-gray-600" aria-hidden />
                        <span className="text-xs text-gray-500 font-mono truncate max-w-[260px]">
                          {displayIdentifier(lead.phone)}
                        </span>
                        {lead.human_takeover && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30">
                            {t("leads.human")}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1 flex-wrap text-xs text-gray-500">
                        <StatusBadge status={lead.status} />
                        <IntentBadge intent={lead.intent} />
                        {lead.zone && <span className="text-gray-400">{lead.zone}</span>}
                        {budget && <span className="text-gray-400">{budget}</span>}
                      </div>
                    </div>
                    {lead.needs_response && (
                      <span
                        className="w-2 h-2 rounded-full bg-amber-400 shrink-0"
                        style={{ boxShadow: "0 0 0 3px rgba(245,158,11,0.15)" }}
                        title={t("leads.pendingHint")}
                      />
                    )}
                    <div className="text-right shrink-0 text-[11px] text-gray-500">
                      {relativeTime(lead.last_message_at, lang)}
                    </div>
                    <ChevronRight className="w-4 h-4 text-gray-600 shrink-0 opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all" />
                  </Link>
                </li>
              );
            })}
            {visible.length === 0 && (
              <li>
                <div className="py-10 px-6 text-center text-gray-500 flex flex-col items-center gap-3">
                  <Search className="w-6 h-6 text-gray-600" />
                  <p className="text-sm">
                    {query ? (
                      <>
                        {t("leads.empty.searchPrefix")} <strong className="text-gray-300">“{query}”</strong>
                        {filter !== "all" ? ` ${t("leads.empty.inFilter")}` : ""}.
                      </>
                    ) : (
                      t("leads.empty.title")
                    )}
                  </p>
                  {(query || filter !== "all") && (
                    <button
                      type="button"
                      onClick={() => {
                        setQuery("");
                        setFilter("all");
                      }}
                      className="text-xs px-3 py-1.5 rounded-md border border-white/10 text-gray-400 hover:text-white hover:bg-white/5"
                    >
                      {t("leads.clearFilters")}
                    </button>
                  )}
                </div>
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

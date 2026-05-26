"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Flame } from "lucide-react";
import { type Lead, leadsApi } from "@/lib/api";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { useI18n } from "@/lib/i18n";

export function HotLeadsPanel() {
  const { t } = useI18n();
  const [leads, setLeads] = useState<Lead[] | null>(null);

  useEffect(() => {
    let mounted = true;
    leadsApi
      .digest(5)
      .then((d) => mounted && setLeads(d))
      .catch(() => mounted && setLeads([]));
    return () => {
      mounted = false;
    };
  }, []);

  if (!leads || leads.length === 0) return null;

  return (
    <section className="mb-6 rounded-xl border border-eko-violet/20 bg-gradient-to-br from-eko-violet/[0.06] to-transparent p-4">
      <h2 className="text-xs uppercase tracking-wider text-eko-violet mb-3 flex items-center gap-1.5">
        <Flame className="w-3.5 h-3.5" />
        {t("hot.title")}
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {leads.map((lead) => (
          <Link
            key={lead.id}
            href={`/leads/${lead.id}`}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/5 hover:border-eko-violet/30 transition-colors"
          >
            <ScoreBadge score={lead.score} />
            <div className="min-w-0">
              <div className="text-sm text-white truncate">{lead.name || lead.phone}</div>
              <div className="text-[11px] text-gray-500 truncate">
                {[lead.zone, lead.intent].filter(Boolean).join(" · ") || "—"}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

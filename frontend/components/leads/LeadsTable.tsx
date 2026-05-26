"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, Mail, MessageCircle, MessageSquare, Phone, User2 } from "lucide-react";
import { type Lead, type LeadIntent, type LeadStatus, leadsApi } from "@/lib/api";
import { formatBudget, relativeTime } from "@/lib/format";
import { IntentBadge, StatusBadge } from "@/components/ui/Badge";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { useI18n } from "@/lib/i18n";

function channelGlyph(identifier: string): typeof MessageCircle {
  // Heuristic: email addresses contain "@", phone numbers don't.
  return identifier.includes("@") ? Mail : MessageCircle;
}

export function LeadsTable() {
  const params = useSearchParams();
  const { t, lang } = useI18n();
  const [data, setData] = useState<{ total: number; items: Lead[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const status = params.get("status") || undefined;
    const intent = params.get("intent") || undefined;
    leadsApi
      .list({
        status: status as LeadStatus | undefined,
        intent: intent as LeadIntent | undefined,
        limit: 100,
      })
      .then((d) => setData(d))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [params]);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-12 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t("leads.loading")}
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-300">
        {t("leads.error")}: {error}
      </div>
    );
  }
  if (!data || data.items.length === 0) {
    return (
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-12 text-center">
        <MessageCircle className="w-8 h-8 text-gray-600 mx-auto mb-3" />
        <p className="text-gray-400 text-sm mb-1">{t("leads.empty.title")}</p>
        <p className="text-gray-600 text-xs">{t("leads.empty.hint")}</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] overflow-hidden">
      <div className="px-4 py-2 border-b border-white/5 text-[10px] uppercase tracking-wider text-gray-500 flex justify-between">
        <span>{data.total} {data.total === 1 ? t("leads.count.one") : t("leads.count.other")} · {t("leads.sortedByPriority")}</span>
        <span>{t("leads.lastActivity")}</span>
      </div>
      <ul className="divide-y divide-white/5">
        {data.items.map((lead) => {
          const budget = formatBudget(lead.budget_min, lead.budget_max, lang);
          return (
            <li key={lead.id}>
              <Link
                href={`/leads/${lead.id}`}
                className="block px-4 py-3 hover:bg-white/[0.03] transition-colors"
              >
                <div className="flex items-center gap-3">
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
                      {(() => {
                        const Glyph = channelGlyph(lead.phone);
                        return <Glyph className="w-3 h-3 text-gray-600" aria-hidden />;
                      })()}
                      <span className="text-xs text-gray-500 font-mono truncate max-w-[260px]">{lead.phone}</span>
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
                  <div className="text-right shrink-0">
                    <div className="text-[11px] text-gray-500">{relativeTime(lead.last_message_at, lang)}</div>
                  </div>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

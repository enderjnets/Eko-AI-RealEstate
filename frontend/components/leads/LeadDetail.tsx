"use client";

import { useEffect, useState } from "react";
import { Loader2, MessageCircle, Phone, User2 } from "lucide-react";
import {
  type Conversation,
  type Lead,
  conversationsApi,
  leadsApi,
} from "@/lib/api";
import { IntentBadge, StatusBadge } from "@/components/ui/Badge";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { VisitsSection } from "@/components/calendar/VisitsSection";
import { MatchesSection } from "@/components/properties/MatchesSection";
import { Composer } from "@/components/conversation/Composer";
import { MessageBubble } from "@/components/conversation/MessageBubble";
import { TakeoverToggle } from "@/components/conversation/TakeoverToggle";
import { exactTime, formatBudget, relativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function LeadDetail({ leadId }: { leadId: number }) {
  const { t, lang } = useI18n();
  const [lead, setLead] = useState<Lead | null>(null);
  const [conv, setConv] = useState<Conversation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    Promise.all([leadsApi.get(leadId), conversationsApi.get(leadId).catch(() => null)])
      .then(([leadData, convData]) => {
        if (!mounted) return;
        setLead(leadData);
        setConv(convData);
      })
      .catch((e) => mounted && setError(String(e.message || e)))
      .finally(() => mounted && setLoading(false));

    return () => {
      mounted = false;
    };
  }, [leadId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-12 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("lead.loading")}
      </div>
    );
  }
  if (error || !lead) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-300">
        {error || t("lead.notFound")}
      </div>
    );
  }

  const budget = formatBudget(lead.budget_min, lead.budget_max, lang);

  return (
    <>
      {/* Header */}
      <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-5 mb-6">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-full bg-eko-violet/10 border border-eko-violet/30 flex items-center justify-center shrink-0">
            <User2 className="w-5 h-5 text-eko-violet" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h1 className="text-xl font-semibold text-white">
                {lead.name || t("common.noName")}
              </h1>
              <ScoreBadge score={lead.score} showLabel size="lg" />
              <StatusBadge status={lead.status} />
              <IntentBadge intent={lead.intent} />
            </div>
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Phone className="w-3.5 h-3.5" />
              <span className="font-mono">{lead.phone}</span>
              <span className="text-gray-700">·</span>
              <span>{t("leads.lastMessage")} {relativeTime(lead.last_message_at, lang)}</span>
            </div>
          </div>
          <TakeoverToggle leadId={lead.id} initial={lead.human_takeover} />
        </div>

        {(lead.zone || budget || lead.property_type || lead.urgency) && (
          <div className="mt-4 pt-4 border-t border-white/5 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <Field label={t("lead.field.zone")} value={lead.zone} />
            <Field label={t("lead.field.budget")} value={budget} />
            <Field label={t("lead.field.type")} value={lead.property_type} />
            <Field label={t("lead.field.urgency")} value={lead.urgency} />
          </div>
        )}
        <div className="mt-3 text-[10px] text-gray-600">
          {t("lead.created")} {exactTime(lead.created_at, lang)} · {t("lead.updated")} {exactTime(lead.updated_at, lang)}
        </div>
      </div>

      {/* Conversation */}
      <section>
        <h2 className="text-sm uppercase tracking-wider text-gray-500 mb-3 flex items-center gap-2">
          <MessageCircle className="w-3.5 h-3.5" />
          {t("lead.conversation")}
          {conv && (
            <span className="text-[10px] text-gray-600 normal-case tracking-normal">
              ({conv.messages.length} {t("lead.messages")} · {t("lead.channel")} {conv.channel})
            </span>
          )}
        </h2>

        {!conv || conv.messages.length === 0 ? (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-12 text-center text-gray-500 text-sm">
            {t("lead.noMessages")}
          </div>
        ) : (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-5 space-y-4">
            {conv.messages.map((m) => (
              <MessageBubble key={m.id} msg={m} channel={conv.channel} />
            ))}
          </div>
        )}
      </section>

      {conv && <Composer leadId={lead.id} channel={conv.channel} />}

      <MatchesSection leadId={lead.id} />

      <VisitsSection leadId={lead.id} />
    </>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-gray-600 mb-0.5">
        {label}
      </div>
      <div className="text-sm text-white">{value || <span className="text-gray-600">—</span>}</div>
    </div>
  );
}

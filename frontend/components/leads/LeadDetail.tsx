"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Mail, MessageCircle, MessageSquare, Phone, User2 } from "lucide-react";
import {
  type Lead,
  type Timeline,
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

const CHANNEL_ICON: Record<string, typeof MessageCircle> = {
  whatsapp: MessageCircle,
  email: Mail,
  sms: MessageSquare,
  voice: Phone,
};

export function LeadDetail({ leadId }: { leadId: number }) {
  const { t, lang } = useI18n();
  const [lead, setLead] = useState<Lead | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Reload just the timeline — called after the composer sends, so the new
  // outbound shows immediately (router.refresh() doesn't re-run this client effect).
  const refetchTimeline = useCallback(() => {
    conversationsApi.timeline(leadId).then(setTimeline).catch(() => {});
  }, [leadId]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    Promise.all([leadsApi.get(leadId), conversationsApi.timeline(leadId).catch(() => null)])
      .then(([leadData, tl]) => {
        if (!mounted) return;
        setLead(leadData);
        setTimeline(tl);
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

      {/* Conversation — unified timeline across all channels */}
      <section>
        <h2 className="text-sm uppercase tracking-wider text-gray-500 mb-3 flex items-center gap-2 flex-wrap">
          <MessageCircle className="w-3.5 h-3.5" />
          {t("lead.conversation")}
          {timeline && timeline.messages.length > 0 && (
            <span className="text-[10px] text-gray-600 normal-case tracking-normal">
              ({timeline.messages.length} {t("lead.messages")})
            </span>
          )}
          {timeline && timeline.channels.length > 0 && (
            <span className="inline-flex items-center gap-1.5">
              {timeline.channels.map((ch) => {
                const Ch = CHANNEL_ICON[ch] ?? MessageCircle;
                return (
                  <span
                    key={ch}
                    className="inline-flex items-center gap-1 text-[10px] text-gray-500 px-1.5 py-0.5 rounded border border-white/10 bg-white/[0.03] normal-case tracking-normal"
                    title={ch}
                  >
                    <Ch className="w-3 h-3" aria-hidden /> {ch}
                  </span>
                );
              })}
            </span>
          )}
        </h2>

        {!timeline || timeline.messages.length === 0 ? (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-12 text-center text-gray-500 text-sm">
            {t("lead.noMessages")}
          </div>
        ) : (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-5 space-y-4">
            {timeline.messages.map((m) => (
              <MessageBubble key={m.id} msg={m} channel={m.channel} />
            ))}
          </div>
        )}
      </section>

      <Composer
        leadId={lead.id}
        defaultChannel={timeline?.primary_channel ?? "sms"}
        onSent={refetchTimeline}
      />

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

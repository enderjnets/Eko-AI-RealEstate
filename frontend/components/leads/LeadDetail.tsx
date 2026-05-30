"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CalendarCheck,
  CheckCircle2,
  Loader2,
  Mail,
  MessageCircle,
  MessageSquare,
  Phone,
  Sparkles,
  User2,
} from "lucide-react";
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
  const [marking, setMarking] = useState(false);

  // Reload just the timeline — called after the composer sends, so the new
  // outbound shows immediately (router.refresh() doesn't re-run this client effect).
  const refetchTimeline = useCallback(() => {
    conversationsApi.timeline(leadId).then(setTimeline).catch(() => {});
  }, [leadId]);

  async function markWon() {
    if (marking || !lead) return;
    setMarking(true);
    try {
      setLead(await leadsApi.patch(lead.id, { status: "won" }));
    } catch {
      // non-fatal; the status badge simply stays as-is
    } finally {
      setMarking(false);
    }
  }

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

  const identifier = lead.phone;
  const isPhoneContact =
    !identifier.includes("@") && !identifier.startsWith("discovery:") && !identifier.startsWith("http");
  const primaryChannel = timeline?.primary_channel || (identifier.includes("@") ? "email" : "sms");
  const PrimaryIcon = CHANNEL_ICON[primaryChannel] ?? MessageSquare;
  const primaryLabel =
    primaryChannel === "email"
      ? "Email"
      : primaryChannel === "whatsapp"
      ? "WhatsApp"
      : primaryChannel === "sms"
      ? "SMS"
      : t("lead.qa.message");
  const canWin = lead.status !== "won" && lead.status !== "lost";

  function focusComposer() {
    const el = document.getElementById("composer");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => el?.querySelector("textarea")?.focus(), 350);
  }
  function scrollToVisits() {
    document.getElementById("visits")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const qaBase =
    "inline-flex items-center gap-1.5 shrink-0 px-3.5 py-2 rounded-lg border text-xs font-medium transition-colors";
  const qaGhost = "bg-white/[0.03] border-white/10 text-gray-300 hover:bg-white/5 hover:border-white/20 hover:text-white";

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

      {/* Quick actions */}
      <div className="flex gap-2 mb-6 flex-nowrap overflow-x-auto sm:flex-wrap pb-1 sm:pb-0">
        <button
          type="button"
          onClick={focusComposer}
          className={`${qaBase} bg-eko-violet/15 border-eko-violet/30 text-violet-300 hover:bg-eko-violet/25 hover:text-white`}
        >
          <PrimaryIcon className="w-3.5 h-3.5" />
          {primaryLabel}
        </button>
        {isPhoneContact && (
          <a href={`tel:${identifier}`} className={`${qaBase} ${qaGhost}`}>
            <Phone className="w-3.5 h-3.5" />
            {t("lead.qa.call")}
          </a>
        )}
        <button type="button" onClick={scrollToVisits} className={`${qaBase} ${qaGhost}`}>
          <CalendarCheck className="w-3.5 h-3.5" />
          {t("lead.qa.bookVisit")}
        </button>
        {canWin && (
          <button type="button" onClick={markWon} disabled={marking} className={`${qaBase} ${qaGhost} disabled:opacity-60`}>
            {marking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
            {t("lead.qa.markWon")}
          </button>
        )}
      </div>

      <ScoreInsight breakdown={lead.score_breakdown} />

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

      <div id="composer">
        <Composer
          leadId={lead.id}
          defaultChannel={timeline?.primary_channel ?? "sms"}
          onSent={refetchTimeline}
        />
      </div>

      <MatchesSection leadId={lead.id} />

      <div id="visits">
        <VisitsSection leadId={lead.id} />
      </div>
    </>
  );
}

const SCORE_FACTORS: { key: string; max: number }[] = [
  { key: "intent", max: 20 },
  { key: "budget", max: 15 },
  { key: "engagement", max: 15 },
  { key: "urgency", max: 12 },
  { key: "zone", max: 10 },
  { key: "property_type", max: 8 },
  { key: "recency", max: 10 },
  { key: "visit", max: 10 },
];

function ScoreInsight({ breakdown }: { breakdown: Lead["score_breakdown"] }) {
  const { t } = useI18n();
  const comps = breakdown?.components ?? {};
  const rows = SCORE_FACTORS.filter((f) => f.key in comps);
  if (rows.length === 0) return null;
  const gate = breakdown?.status_gate;
  return (
    <section className="rounded-xl border border-white/5 bg-white/[0.02] p-4 mb-6">
      <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-3 flex items-center gap-1.5">
        <Sparkles className="w-3.5 h-3.5 text-eko-violet" />
        {t("lead.insight.title")}
      </h2>
      <div className="flex flex-col gap-2.5">
        {rows.map((f) => {
          const v = comps[f.key] ?? 0;
          const pct = Math.min(100, Math.round((v / f.max) * 100));
          return (
            <div key={f.key} className="grid grid-cols-[88px_1fr_auto] items-center gap-2.5">
              <span className="text-[11px] text-gray-400">{t(`lead.insight.factor.${f.key}`)}</span>
              <span className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                <span
                  className="block h-full rounded-full bg-gradient-to-r from-eko-violet to-eko-magenta"
                  style={{ width: `${pct}%` }}
                />
              </span>
              <span className="text-[10px] text-gray-500 tabular-nums text-right">
                {v}/{f.max}
              </span>
            </div>
          );
        })}
      </div>
      {typeof gate === "number" && gate < 1 && (
        <p className="text-[10px] text-amber-400/80 mt-3">{t("lead.insight.gate")}</p>
      )}
      <p className="text-[10px] text-gray-600 leading-relaxed mt-3">{t("lead.insight.foot")}</p>
    </section>
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

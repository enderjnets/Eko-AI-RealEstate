"use client";

import { Bot, MessageCircle, Mail, MessageSquare, Phone, User2 } from "lucide-react";
import type { Message } from "@/lib/api";
import { exactTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const CHANNEL_ICON: Record<string, typeof MessageCircle> = {
  whatsapp: MessageCircle,
  email: Mail,
  sms: MessageSquare,
  voice: Phone,
};

export function MessageBubble({ msg, channel }: { msg: Message; channel?: string }) {
  const { t, lang } = useI18n();
  const isInbound = msg.direction === "inbound";
  const isHuman = msg.sender === "human";
  const isAgent = msg.sender === "agent";

  // A note filed in this thread that the lead never received — today, the copy
  // of an appointment invitation sent to the agency. It has to look different
  // from everything around it: rendered like an ordinary outbound message, a
  // realtor would believe the client read it and answer on that basis.
  const isInternal = msg.internal;

  const Icon = isInbound ? User2 : isAgent ? Bot : Phone;
  const senderLabel = isInbound
    ? t("msg.sender.lead")
    : isAgent
    ? t("msg.sender.agent")
    : t("msg.sender.human");

  return (
    <div className={`flex ${isInbound ? "justify-start" : "justify-end"} gap-2`}>
      {isInbound && (
        <div className="w-7 h-7 rounded-full bg-white/5 border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
          <Icon className="w-3.5 h-3.5 text-gray-400" aria-hidden />
        </div>
      )}
      <div className={`max-w-[78%] ${isInbound ? "" : "items-end"}`}>
        <div className="flex items-center gap-1.5 mb-0.5 text-[10px] text-gray-500">
          <span>{senderLabel}</span>
          {channel && (() => {
            const Ch = CHANNEL_ICON[channel] ?? MessageCircle;
            return <Ch className="w-3 h-3 text-gray-600" aria-hidden />;
          })()}
          {isAgent && msg.llm_provider && (
            <span className="text-[10px] px-1 rounded bg-eko-violet/10 text-eko-violet border border-eko-violet/20">
              {msg.llm_provider}
            </span>
          )}
          {isHuman && (
            <span className="text-[10px] px-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
              {t("msg.manual")}
            </span>
          )}
          {isInternal && (
            <span
              className="text-[10px] px-1 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20"
              title={t("msg.internalHelp")}
            >
              {t("msg.internal")}
            </span>
          )}
          {msg.fair_housing_flags && msg.fair_housing_flags.length > 0 && (
            <span
              className="text-[10px] px-1 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20"
              title={msg.fair_housing_flags
                .map((f) => `${f.phrase} (${f.category})`)
                .join(", ")}
            >
              {t("msg.fairHousing", { n: msg.fair_housing_flags.length })}
            </span>
          )}
          <span>· {exactTime(msg.created_at, lang)}</span>
        </div>
        {channel === "email" && msg.subject && (
          <div className="text-[11px] text-gray-400 mb-1 truncate" title={msg.subject}>
            <span className="text-gray-600">{t("msg.subject")}</span> {msg.subject}
          </div>
        )}
        <div
          className={`px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap leading-relaxed ${
            isInternal
              ? "bg-sky-500/[0.07] border border-dashed border-sky-500/30 text-gray-300 rounded-tr-sm"
              : isInbound
              ? "bg-white/[0.05] border border-white/10 text-gray-100 rounded-tl-sm"
              : isHuman
              ? "bg-amber-500/10 border border-amber-500/20 text-amber-50 rounded-tr-sm"
              : "bg-eko-violet/15 border border-eko-violet/25 text-white rounded-tr-sm"
          }`}
        >
          {msg.content}
        </div>
        {!isInbound && (
          <div className="text-[10px] text-gray-600 mt-0.5 text-right">
            {t(`msg.status.${msg.delivery_status}`)}
          </div>
        )}
      </div>
      {!isInbound && (
        <div
          className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
            isHuman
              ? "bg-amber-500/15 border border-amber-500/30"
              : "bg-eko-violet/15 border border-eko-violet/30"
          }`}
        >
          <Icon className={`w-3.5 h-3.5 ${isHuman ? "text-amber-400" : "text-eko-violet"}`} aria-hidden />
        </div>
      )}
    </div>
  );
}

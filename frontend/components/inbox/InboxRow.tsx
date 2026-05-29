"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, Loader2, MessageCircleReply, User2 } from "lucide-react";
import { type InboxItem, inboxApi } from "@/lib/api";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { relativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { ItemBadges } from "@/components/inbox/InboxBadges";

export function InboxRow({ item, onHandled }: { item: InboxItem; onHandled: (leadId: number) => void }) {
  const { t, lang } = useI18n();
  const [marking, setMarking] = useState(false);

  async function markHandled() {
    if (marking) return;
    setMarking(true);
    try {
      await inboxApi.markHandled(item.lead_id);
      onHandled(item.lead_id);
    } catch {
      setMarking(false);
    }
  }

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5 hover:bg-white/[0.02] transition-colors">
      <ScoreBadge score={item.score} />
      <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
        <User2 className="w-4 h-4 text-gray-400" aria-hidden />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-white truncate">
            {item.name || item.identifier}
          </span>
          <ItemBadges item={item} />
        </div>
        {item.last_preview && (
          <div className="text-xs text-gray-500 truncate mt-0.5">{item.last_preview}</div>
        )}
      </div>

      <span className="text-[10px] text-gray-600 shrink-0 hidden sm:block">
        {relativeTime(item.last_message_at, lang)}
      </span>

      <div className="flex items-center gap-1.5 shrink-0">
        <Link
          href={`/leads/${item.lead_id}`}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium bg-eko-violet/90 text-white hover:bg-eko-violet transition-colors"
        >
          <MessageCircleReply className="w-3 h-3" aria-hidden />
          {t("inbox.action.reply")}
        </Link>
        {item.needs_response && (
          <button
            type="button"
            onClick={markHandled}
            disabled={marking}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium border border-white/10 text-gray-300 hover:bg-white/5 disabled:opacity-50 transition-colors"
            title={t("inbox.action.handled")}
          >
            {marking ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
            {t("inbox.action.handled")}
          </button>
        )}
      </div>
    </div>
  );
}

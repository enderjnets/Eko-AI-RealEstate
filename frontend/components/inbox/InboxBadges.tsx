"use client";

import {
  CalendarCheck,
  CheckCircle2,
  Globe,
  Mail,
  MessageCircle,
  MessageSquare,
  Phone,
} from "lucide-react";
import type { InboxItem } from "@/lib/api";
import { pendingLabelKey } from "@/lib/inboxBadge";
import { exactTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const CHANNEL_ICON: Record<string, typeof Mail> = {
  whatsapp: MessageCircle,
  email: Mail,
  sms: MessageSquare,
  voice: Phone,
  web: Globe,
};

/** Pending-reply badge: which channel is waiting for our answer. */
export function PendingBadge({ channel }: { channel: string | null }) {
  const { t } = useI18n();
  const Icon = (channel && CHANNEL_ICON[channel]) || MessageSquare;
  const labelKey = pendingLabelKey(channel);
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
      <Icon className="w-3 h-3" aria-hidden />
      {t(labelKey)}
    </span>
  );
}

/** Booked-visit badge with the (localized) date. */
export function VisitBadge({ at }: { at: string | null }) {
  const { t, lang } = useI18n();
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-blue-500/15 text-blue-300 border border-blue-500/30"
      title={at ? exactTime(at, lang) : undefined}
    >
      <CalendarCheck className="w-3 h-3" aria-hidden />
      {t("inbox.badge.visit")}
      {at && <span className="text-blue-200/80">· {exactTime(at, lang)}</span>}
    </span>
  );
}

/** "Up to date" badge for a lead with no pending reply. */
export function AtDiaBadge() {
  const { t } = useI18n();
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-eko-green/10 text-eko-green border border-eko-green/25">
      <CheckCircle2 className="w-3 h-3" aria-hidden />
      {t("inbox.badge.atDia")}
    </span>
  );
}

/** Convenience: the right status badges for an item (pending / visit / at-día). */
export function ItemBadges({ item }: { item: InboxItem }) {
  return (
    <>
      {item.needs_response ? (
        <PendingBadge channel={item.last_channel} />
      ) : (
        <AtDiaBadge />
      )}
      {item.has_visit && <VisitBadge at={item.next_visit_at} />}
    </>
  );
}

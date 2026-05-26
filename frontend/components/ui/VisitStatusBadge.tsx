"use client";

import type { VisitStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const COLOR: Record<VisitStatus, string> = {
  scheduled: "bg-eko-violet/15 text-eko-violet border-eko-violet/30",
  confirmed: "bg-eko-green/15 text-eko-green border-eko-green/30",
  cancelled: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  completed: "bg-eko-green/15 text-eko-green border-eko-green/30",
  no_show: "bg-red-500/15 text-red-400 border-red-500/30",
};

export function VisitStatusBadge({ status }: { status: VisitStatus }) {
  const { t } = useI18n();
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border ${COLOR[status]}`}>
      {t(`visitStatus.${status}`)}
    </span>
  );
}

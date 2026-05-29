"use client";

import type { InboxFilter } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function InboxFilters({
  active,
  pendingCount,
  bookedCount,
  onChange,
}: {
  active: InboxFilter;
  pendingCount: number;
  bookedCount: number;
  onChange: (f: InboxFilter) => void;
}) {
  const { t } = useI18n();
  const tabs: { key: InboxFilter; label: string; count?: number }[] = [
    { key: "pending", label: t("inbox.filter.pending"), count: pendingCount },
    { key: "booked", label: t("inbox.filter.booked"), count: bookedCount },
    { key: "all", label: t("inbox.filter.all") },
  ];
  return (
    <div className="inline-flex rounded-lg border border-white/10 overflow-hidden">
      {tabs.map(({ key, label, count }) => {
        const isActive = key === active;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
              isActive ? "bg-eko-violet/20 text-eko-violet" : "text-gray-400 hover:bg-white/5"
            }`}
          >
            {label}
            {count != null && count > 0 && (
              <span
                className={`px-1.5 py-0.5 rounded-full text-[10px] ${
                  isActive ? "bg-eko-violet/30 text-eko-violet" : "bg-white/10 text-gray-400"
                }`}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

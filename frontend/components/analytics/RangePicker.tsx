"use client";

import type { AnalyticsRange } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const PRESETS: AnalyticsRange[] = ["7d", "30d", "90d"];

export function RangePicker({
  value,
  onChange,
  timezone,
}: {
  value: AnalyticsRange;
  onChange: (r: AnalyticsRange) => void;
  timezone: string | null;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="flex rounded-lg border border-white/10 overflow-hidden">
        {PRESETS.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => onChange(r)}
            className={`px-3 py-1.5 text-xs ${
              value === r ? "bg-eko-violet text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            {t(`analytics.range.${r}`)}
          </button>
        ))}
      </div>
      {/* The timezone is shown, not assumed. Every day on this page is a day in
          the office's zone, and a reader in another one would otherwise have no
          way to know which midnight the columns are cut at. */}
      {timezone && <span className="text-[10px] text-gray-600">{timezone}</span>}
    </div>
  );
}

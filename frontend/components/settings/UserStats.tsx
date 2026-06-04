"use client";

import { type UserActivity } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { exactTime, relativeTime } from "@/lib/format";

const SECTION_LABEL: Record<string, string> = {
  leads: "Leads",
  inbox: "Inbox",
  calendar: "Calendar",
  properties: "Properties",
  analytics: "Analytics",
  discovery: "Discovery",
  settings: "Settings",
};

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-1.5">
      <div className="text-sm font-semibold text-white">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
    </div>
  );
}

/** Per-user engagement stats block (rendered inside an expanded admin row). */
export function UserStats({ activity }: { activity?: UserActivity }) {
  const { t, lang } = useI18n();

  if (!activity) {
    return <p className="text-[11px] text-gray-600 mt-2">{t("stats.none")}</p>;
  }

  const maxSection = Math.max(1, ...activity.top_sections.map((s) => s.count));

  return (
    <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.015] p-3 space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Metric label={t("stats.logins")} value={activity.login_count} />
        <Metric label={t("stats.actions")} value={activity.request_count} />
        <Metric label={t("stats.activeDays")} value={activity.active_days} />
        <Metric label={t("stats.lastSeen")} value={relativeTime(activity.last_seen, lang)} />
      </div>

      {activity.top_sections.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            {t("stats.sections")}
          </div>
          <div className="space-y-1">
            {activity.top_sections.slice(0, 6).map((s) => (
              <div key={s.section} className="flex items-center gap-2">
                <span className="w-20 shrink-0 text-[11px] text-gray-400 truncate">
                  {SECTION_LABEL[s.section] ?? s.section}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full bg-eko-violet/70"
                    style={{ width: `${(s.count / maxSection) * 100}%` }}
                  />
                </div>
                <span className="w-8 shrink-0 text-right text-[10px] text-gray-500">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-500">
        {activity.device && <span>📱 {activity.device}</span>}
        {activity.last_ip && <span>🌐 {activity.last_ip}</span>}
        <span>
          {t("stats.firstSeen")}: {exactTime(activity.first_seen, lang)}
        </span>
      </div>
    </div>
  );
}

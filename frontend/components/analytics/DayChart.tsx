"use client";

/**
 * Visits and leads per day, drawn as SVG.
 *
 * Labels are thinned to fit rather than rotated: at 390px a month of dates
 * becomes an unreadable grey smear, and a chart nobody can read is worse than
 * one with five labels and a tooltip on every column.
 */

import { useI18n } from "@/lib/i18n";
import { Empty } from "./parts";

interface Day {
  date: string;
  sessions: number;
  leads: number;
}

export function DayChart({ days }: { days: Day[] }) {
  const { t, lang } = useI18n();
  if (days.length === 0) return <Empty>{t("analytics.empty.days")}</Empty>;

  const max = Math.max(1, ...days.map((d) => Math.max(d.sessions, d.leads)));
  // Roughly one label per 55px of a 320px-wide viewport's chart area.
  const every = Math.max(1, Math.ceil(days.length / 6));
  const short = (iso: string) =>
    new Date(`${iso}T12:00:00Z`).toLocaleDateString(lang === "es" ? "es-ES" : "en-US", {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });

  return (
    <div>
      <div className="flex items-end gap-[2px] h-28">
        {days.map((d) => (
          <div
            key={d.date}
            className="flex-1 flex items-end gap-[1px] h-full min-w-0"
            title={`${short(d.date)} · ${d.sessions} ${t("analytics.sessions")} · ${d.leads} ${t("analytics.leadsWord")}`}
          >
            <div
              className="flex-1 bg-eko-violet/70 rounded-t-sm"
              style={{ height: `${Math.max((d.sessions / max) * 100, d.sessions > 0 ? 3 : 0)}%` }}
            />
            <div
              className="flex-1 bg-eko-green/80 rounded-t-sm"
              style={{ height: `${Math.max((d.leads / max) * 100, d.leads > 0 ? 3 : 0)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-[2px] mt-1.5">
        {days.map((d, i) => (
          <span
            key={d.date}
            className="flex-1 text-[9px] text-gray-600 text-center truncate min-w-0"
          >
            {i % every === 0 ? short(d.date) : ""}
          </span>
        ))}
      </div>
      <div className="flex items-center gap-4 mt-2 text-[10px] text-gray-500">
        <span className="flex items-center gap-1">
          <i className="w-2 h-2 rounded-sm bg-eko-violet/70 inline-block" />
          {t("analytics.sessions")}
        </span>
        <span className="flex items-center gap-1">
          <i className="w-2 h-2 rounded-sm bg-eko-green/80 inline-block" />
          {t("analytics.leadsWord")}
        </span>
      </div>
    </div>
  );
}

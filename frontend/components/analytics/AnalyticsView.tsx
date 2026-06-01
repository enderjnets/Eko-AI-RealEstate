"use client";

import { useEffect, useState } from "react";
import { Activity, Clock, Flame, Loader2, Minus, TrendingDown, TrendingUp, Users } from "lucide-react";
import { type Analytics, analyticsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function Bar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-28 text-gray-400 truncate">{label}</span>
      <div className="flex-1 h-5 rounded bg-white/[0.04] overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.max(pct, value > 0 ? 4 : 0)}%` }} />
      </div>
      <span className="w-8 text-right text-gray-300 tabular-nums">{value}</span>
    </div>
  );
}

function TrendPill({ pct, title }: { pct: number | null; title?: string }) {
  if (pct === null) return null;
  const up = pct > 0;
  const down = pct < 0;
  const cls = up
    ? "text-eko-green bg-eko-green/10 border-eko-green/30"
    : down
    ? "text-red-400 bg-red-500/10 border-red-500/30"
    : "text-gray-400 bg-white/5 border-white/10";
  const Icon = up ? TrendingUp : down ? TrendingDown : Minus;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border tabular-nums ${cls}`}
      title={title}
    >
      <Icon className="w-3 h-3" />
      {up ? "+" : ""}
      {pct}%
    </span>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  trend,
}: {
  icon: typeof Users;
  label: string;
  value: string;
  trend?: number | null;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-gray-500 mb-1">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="flex items-center gap-2">
        <div className="text-2xl font-bold text-white tabular-nums">{value}</div>
        {trend !== undefined && <TrendPill pct={trend ?? null} />}
      </div>
    </div>
  );
}

export function AnalyticsView() {
  const { t } = useI18n();
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    analyticsApi
      .get()
      .then(setData)
      .catch((e) => setError(String((e as Error)?.message || e)));
  }, []);

  if (error) {
    return <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">{error}</div>;
  }
  if (!data) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("analytics.loading")}
      </div>
    );
  }

  const resp =
    data.avg_first_response_seconds == null
      ? "—"
      : data.avg_first_response_seconds >= 60
      ? `${Math.round(data.avg_first_response_seconds / 60)} ${t("analytics.minutes")}`
      : `${Math.round(data.avg_first_response_seconds)} ${t("analytics.seconds")}`;

  const funnelMax = Math.max(1, ...Object.values(data.funnel));
  const chanMax = Math.max(1, ...Object.values(data.by_channel));
  const days = [...data.leads_per_day].sort((a, b) => a.date.localeCompare(b.date));
  const dayMax = Math.max(1, ...days.map((d) => d.count));
  const last7 = days.slice(-7).reduce((s, d) => s + d.count, 0);
  const prev7 = days.slice(-14, -7).reduce((s, d) => s + d.count, 0);
  const weekTrend = prev7 > 0 ? Math.round(((last7 - prev7) / prev7) * 100) : last7 > 0 ? 100 : null;

  const TIER_COLOR: Record<string, string> = {
    hot: "bg-red-400/70",
    warm: "bg-amber-400/70",
    cold: "bg-gray-400/60",
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <Stat icon={Users} label={t("analytics.totalLeads")} value={String(data.total_leads)} />
        <Stat icon={Activity} label={t("analytics.newThisWeek")} value={String(last7)} trend={weekTrend} />
        <Stat icon={TrendingUp} label={t("analytics.conversion")} value={`${Math.round(data.conversion_rate * 100)}%`} />
        <Stat icon={Clock} label={t("analytics.avgResponse")} value={resp} />
        <Stat icon={Flame} label={t("analytics.hotLeads")} value={String(data.by_score_tier.hot ?? 0)} />
      </div>

      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-3">{t("analytics.funnel")}</h2>
        <div className="space-y-2">
          {Object.entries(data.funnel).map(([status, n]) => (
            <Bar key={status} label={t(`status.${status}`)} value={n} max={funnelMax} color="bg-eko-violet/70" />
          ))}
        </div>
      </section>

      <div className="grid md:grid-cols-2 gap-6">
        <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
          <h2 className="text-sm font-semibold text-white mb-3">{t("analytics.byChannel")}</h2>
          {Object.keys(data.by_channel).length === 0 ? (
            <p className="text-sm text-gray-600">{t("analytics.noData")}</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(data.by_channel).map(([ch, n]) => (
                <Bar key={ch} label={ch} value={n} max={chanMax} color="bg-eko-magenta/60" />
              ))}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
          <h2 className="text-sm font-semibold text-white mb-3">{t("analytics.byTier")}</h2>
          <div className="space-y-2">
            {(["hot", "warm", "cold"] as const).map((tier) => (
              <Bar
                key={tier}
                label={t(`score.${tier}`)}
                value={data.by_score_tier[tier] ?? 0}
                max={Math.max(1, ...Object.values(data.by_score_tier))}
                color={TIER_COLOR[tier]}
              />
            ))}
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <div className="flex items-center justify-between mb-3 gap-2">
          <h2 className="text-sm font-semibold text-white">{t("analytics.perDay")}</h2>
          <TrendPill pct={weekTrend} title={t("analytics.vsLastWeek")} />
        </div>
        {days.length === 0 ? (
          <p className="text-sm text-gray-600">{t("analytics.noData")}</p>
        ) : (
          <div className="flex items-end gap-1.5 h-28">
            {days.map((d, i) => {
              const thisWeek = i >= days.length - 7;
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center justify-end gap-1" title={`${d.date}: ${d.count}`}>
                  <div
                    className={`w-full rounded-t ${thisWeek ? "bg-eko-violet/70" : "bg-eko-violet/25"}`}
                    style={{ height: `${Math.max((d.count / dayMax) * 100, d.count > 0 ? 8 : 2)}%` }}
                  />
                  <span className="text-[9px] text-gray-600">{d.date.slice(5)}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

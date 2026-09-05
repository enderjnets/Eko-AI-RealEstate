"use client";

/**
 * The whole funnel on one page.
 *
 * What this replaces answered five questions with no date range: how many
 * leads, by status, by channel, by score, and an average first response that
 * counted advisors' own notes as replies. It could not say where anybody came
 * from, whether the phone was ever picked up, whether an appointment happened,
 * or what kind of business closed.
 *
 * Two rules the layout follows, and they are the same rule twice: **a number
 * appears with the words that make it true, or it does not appear.** The
 * content card says "association", never "attribution". The empty states say
 * why a section is empty rather than showing a zero that reads like a fact.
 */

import { useCallback, useEffect, useState } from "react";
import {
  CalendarCheck,
  Clock,
  Handshake,
  Loader2,
  Phone,
  Users,
} from "lucide-react";
import { type Analytics, type AnalyticsRange, analyticsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { AgentsTable } from "./AgentsTable";
import { ContentTable } from "./ContentTable";
import { DayChart } from "./DayChart";
import { FunnelSteps } from "./FunnelSteps";
import { RangePicker } from "./RangePicker";
import { Bars, Card, Empty, duration, fromBreakdown, fromMap } from "./parts";

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Users;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-gray-500 mb-1">
        <Icon className="w-3.5 h-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <div className="text-xl font-semibold text-white tabular-nums">{value}</div>
      {hint && <div className="text-[10px] text-gray-600 mt-0.5">{hint}</div>}
    </div>
  );
}

export function AnalyticsView() {
  const { t } = useI18n();
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((r: AnalyticsRange) => {
    setLoading(true);
    setError(null);
    analyticsApi
      .get({ range: r })
      .then(setData)
      .catch((e) => setError(String(e?.message || e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(range), [load, range]);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-12">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("common.loading")}
      </div>
    );
  }
  if (error) {
    return <p className="text-sm text-red-400 py-8">{error}</p>;
  }
  if (!data) return null;

  // Translate if we have a word for it, otherwise show what the database said.
  // The raw values are already readable — `tiktok`, `instagram`, `phone` — so a
  // missing translation degrades to "slightly less polished", never to a blank
  // row or the literal key.
  const label = (key: string, raw: string) => {
    const translated = t(key);
    return translated === key ? raw : translated;
  };

  const { traffic, leads, response, calls, appointments, deals } = data;
  const days = traffic.by_day.map((d, i) => ({
    date: d.date,
    sessions: d.sessions,
    leads: leads.new_by_day[i]?.leads ?? 0,
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <RangePicker value={range} onChange={setRange} timezone={data.range.timezone} />
        {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-500" />}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        <Stat icon={Users} label={t("analytics.sessions")} value={String(traffic.sessions)} />
        <Stat
          icon={Users}
          label={t("analytics.leadsWord")}
          value={String(leads.total)}
          hint={`${leads.by_source.no_web ?? 0} ${t("analytics.noWeb")}`}
        />
        <Stat
          icon={Clock}
          label={t("analytics.firstResponse")}
          value={duration(response.first_response_seconds.median, (k) => t(`unit.${k}`))}
          hint={
            response.unanswered > 0
              ? `${response.unanswered} ${t("analytics.unanswered")}`
              : undefined
          }
        />
        <Stat icon={Phone} label={t("analytics.callsIn")} value={String(calls.inbound)} />
        <Stat
          icon={CalendarCheck}
          label={t("analytics.appointments")}
          value={`${appointments.completed}/${appointments.set}`}
          hint={t("analytics.heldOfSet")}
        />
        <Stat
          icon={Handshake}
          label={t("analytics.won")}
          value={String(deals.won)}
          hint={
            deals.total_value !== null
              ? `$${Math.round(deals.total_value).toLocaleString()}`
              : undefined
          }
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title={t("analytics.funnel")} hint={t("analytics.funnelHint")}>
          <FunnelSteps steps={data.funnel} />
        </Card>

        <Card title={t("analytics.perDay")}>
          <DayChart days={days} />
        </Card>

        <Card title={t("analytics.bySource")} hint={t("analytics.bySourceHint")}>
          <Bars
            rows={fromBreakdown(traffic.by_source)}
            empty={t("analytics.empty.traffic")}
            label={(n) => label(`source.${n}`, n)}
          />
        </Card>

        <Card title={t("analytics.byDevice")}>
          <Bars rows={fromBreakdown(traffic.by_device)} empty={t("analytics.empty.traffic")} />
        </Card>

        <Card title={t("analytics.where")} hint={t("analytics.whereHint")}>
          {traffic.by_city.length === 0 ? (
            <Empty>{t("analytics.empty.traffic")}</Empty>
          ) : (
            <Bars rows={fromBreakdown(traffic.by_city)} empty={t("analytics.empty.traffic")} />
          )}
        </Card>

        <Card title={t("analytics.howFar")} hint={`${traffic.avg_scroll_pct}% ${t("analytics.avgScroll")}`}>
          <Bars
            rows={fromMap(traffic.sections)}
            empty={t("analytics.empty.traffic")}
            label={(n) => label(`section.${n}`, n)}
          />
        </Card>

        <Card title={t("analytics.whoAnswers")} hint={t("analytics.whoAnswersHint")}>
          <Bars
            rows={fromMap(response.by_kind)}
            empty={t("analytics.empty.replies")}
            label={(n) => label(`replyKind.${n}`, n)}
          />
          <p className="text-[11px] text-gray-500">
            {t("analytics.p90")}: {duration(response.first_response_seconds.p90, (k) => t(`unit.${k}`))}
          </p>
        </Card>

        {/* Two different facts, and the first draft put them in one card with
            one empty state: it read "no calls logged in this range" directly
            above "average call: 2 min". They are calls the office made and
            calls the agent received, and each needs its own absence. */}
        <Card title={t("analytics.calls")}>
          <div className="space-y-1.5">
            <p className="text-[11px] uppercase tracking-wider text-gray-500">
              {t("analytics.callsIn")}
            </p>
            {calls.inbound === 0 ? (
              <Empty>{t("analytics.empty.callsIn")}</Empty>
            ) : (
              <p className="text-sm text-gray-300">
                {calls.inbound}
                {calls.avg_duration_seconds !== null && (
                  <span className="text-gray-500">
                    {" · "}
                    {t("analytics.avgCall")}{" "}
                    {duration(calls.avg_duration_seconds, (k) => t(`unit.${k}`))}
                  </span>
                )}
              </p>
            )}
          </div>
          <div className="space-y-1.5 pt-1">
            <p className="text-[11px] uppercase tracking-wider text-gray-500">
              {t("analytics.callsLogged")}
            </p>
            <Bars rows={fromMap(calls.by_outcome)} empty={t("analytics.empty.calls")} />
          </div>
        </Card>

        <Card title={t("analytics.appointments")}>
          <Bars
            rows={[
              { name: t("analytics.held"), value: appointments.completed },
              { name: t("analytics.noShow"), value: appointments.no_show },
              { name: t("analytics.cancelled"), value: appointments.cancelled },
            ].filter((r) => r.value > 0)}
            empty={t("analytics.empty.appointments")}
          />
        </Card>

        <Card title={t("analytics.deals")} hint={t("analytics.dealsHint")}>
          {deals.won === 0 && deals.lost === 0 ? (
            <Empty>{t("analytics.empty.deals")}</Empty>
          ) : (
            <>
              <Bars
                rows={fromMap(deals.by_kind)}
                empty={t("analytics.empty.deals")}
                label={(n) => label(`lead.close.kind.${n}`, n)}
              />
              <p className="text-[11px] text-gray-500">
                {t("analytics.closeRate")}: {Math.round(deals.close_rate * 100)}% ·{" "}
                {deals.lost} {t("analytics.lost")}
              </p>
            </>
          )}
        </Card>

        <Card title={t("analytics.content")} hint={t("analytics.contentHint")}>
          <ContentTable rows={data.content} />
        </Card>

        <Card title={t("analytics.byAgent")}>
          <AgentsTable rows={data.by_agent} />
        </Card>
      </div>
    </div>
  );
}

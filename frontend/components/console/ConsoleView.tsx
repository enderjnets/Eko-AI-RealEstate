"use client";

/**
 * The list of today. A list, not a dashboard — anything that needs
 * interpreting belongs on the analytics page.
 *
 * Two of the three sections surface state that previously existed only in a
 * log line: a follow-up nothing can send, and a follow-up being held because
 * we have no record of permission to write to this person. Both were invisible
 * to the office, which meant "we are nurturing them" and "we have not been
 * able to say a word to them for a week" looked identical from the outside.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, Flame, Loader2, Mail, PhoneCall, RefreshCw } from "lucide-react";
import {
  type ConsoleLead,
  type ConsoleToday,
  type PreferredChannel,
  consoleApi,
} from "@/lib/api";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { relativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function ConsoleView() {
  const { t, lang } = useI18n();
  const [data, setData] = useState<ConsoleToday | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    consoleApi
      .today()
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  if (loading && !data) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <p role="alert" className="py-8 text-sm text-red-600 dark:text-red-400">
        {t("console.error")}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={load}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-gray-300 px-4 text-sm text-gray-700 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          {t("console.reload")}
        </button>
      </div>

      <Section
        icon={<PhoneCall className="h-4 w-4 text-eko-violet" />}
        title={t("console.tasks")}
        hint={t("console.tasksHint")}
        empty={t("console.tasksEmpty")}
        count={data?.tasks.length ?? 0}
      >
        {data?.tasks.map((task) => (
          <Row
            key={task.follow_up_id}
            lead={task.lead}
            lang={lang}
            trailing={
              <span className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                <ChannelIcon channel={task.channel} />
                {t(`call.preferred.${task.channel}`)} ·{" "}
                {t("console.due").replace(
                  "{when}",
                  relativeTime(task.scheduled_for, lang),
                )}
              </span>
            }
          />
        ))}
      </Section>

      <Section
        icon={<AlertCircle className="h-4 w-4 text-amber-600" />}
        title={t("console.held")}
        hint={t("console.heldHint")}
        empty={t("console.heldEmpty")}
        count={data?.held.length ?? 0}
      >
        {data?.held.map((held) => (
          <Row
            key={held.follow_up_id}
            lead={held.lead}
            lang={lang}
            trailing={
              <span className="text-xs text-amber-700 dark:text-amber-400">
                {t("console.holds").replace("{n}", String(held.holds))}
              </span>
            }
          />
        ))}
      </Section>

      <Section
        icon={<Flame className="h-4 w-4 text-orange-500" />}
        title={t("console.hot")}
        hint={t("console.hotHint")}
        empty={t("console.hotEmpty")}
        count={data?.untouched_hot.length ?? 0}
      >
        {data?.untouched_hot.map((lead) => (
          <Row
            key={lead.id}
            lead={lead}
            lang={lang}
            trailing={
              lead.last_message_at ? (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {relativeTime(lead.last_message_at, lang)}
                </span>
              ) : null
            }
          />
        ))}
      </Section>
    </div>
  );
}

function ChannelIcon({ channel }: { channel: PreferredChannel }) {
  if (channel === "email") return <Mail className="h-3.5 w-3.5" />;
  return <PhoneCall className="h-3.5 w-3.5" />;
}

function Section({
  icon,
  title,
  hint,
  empty,
  count,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  empty: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-950">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-50">{title}</h2>
        {count > 0 && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400">
            {count}
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{hint}</p>
      {count === 0 ? (
        <p className="mt-4 text-sm text-gray-400 dark:text-gray-500">{empty}</p>
      ) : (
        <ul className="mt-4 divide-y divide-gray-100 dark:divide-gray-800">{children}</ul>
      )}
    </section>
  );
}

function Row({
  lead,
  lang,
  trailing,
}: {
  lead: ConsoleLead;
  lang: string;
  trailing: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <li>
      <Link
        href={`/leads/${lead.id}#call`}
        className="flex min-h-[56px] flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 hover:opacity-80"
      >
        <span className="flex min-w-0 items-center gap-2">
          {lead.score != null && <ScoreBadge score={lead.score} />}
          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {lead.name || lead.phone || `#${lead.id}`}
          </span>
          {lead.zone && (
            <span className="truncate text-xs text-gray-500 dark:text-gray-400">
              {lead.zone}
            </span>
          )}
        </span>
        <span className="flex items-center gap-3">
          {trailing}
          <span className="text-xs text-eko-violet">{t("console.open")}</span>
        </span>
      </Link>
    </li>
  );
}

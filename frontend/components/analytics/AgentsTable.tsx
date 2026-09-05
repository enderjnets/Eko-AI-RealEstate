"use client";

/**
 * Per person. `office` is a real row, not a bug: it is what gets recorded when
 * somebody signs in with the master password rather than with Google, which is
 * how the owner often works. Hiding it would make his own actions vanish from
 * his own report.
 */

import type { Analytics } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Empty } from "./parts";

export function AgentsTable({ rows }: { rows: Analytics["by_agent"] }) {
  const { t } = useI18n();
  if (rows.length === 0) return <Empty>{t("analytics.empty.agents")}</Empty>;
  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 text-[10px] uppercase tracking-wider">
            <th className="text-left font-medium pb-1.5">{t("analytics.agent")}</th>
            <th className="text-right font-medium pb-1.5">{t("analytics.callsLogged")}</th>
            <th className="text-right font-medium pb-1.5">{t("analytics.appointments")}</th>
            <th className="text-right font-medium pb-1.5">{t("analytics.won")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.email} className="border-t border-white/5">
              <td className="py-1.5 text-gray-300 truncate max-w-[10rem]">{r.email}</td>
              <td className="py-1.5 text-right tabular-nums text-gray-400">{r.calls_logged}</td>
              <td className="py-1.5 text-right tabular-nums text-gray-400">{r.appointments}</td>
              <td className="py-1.5 text-right tabular-nums text-white">{r.won}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

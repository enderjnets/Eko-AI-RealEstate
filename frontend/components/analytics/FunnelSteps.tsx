"use client";

/**
 * The funnel, as bars that each say what fraction of the step above they are.
 *
 * Against the previous step and not against the top, because that is the only
 * form a person can act on: "half the people who reached the form sent it" says
 * where to look, while "3% of visitors sent it" says nothing about which of the
 * seven stages in between is the leak.
 */

import type { FunnelStep } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Empty } from "./parts";

export function FunnelSteps({ steps }: { steps: FunnelStep[] }) {
  const { t } = useI18n();
  const top = Math.max(1, ...steps.map((s) => s.count));
  if (steps.every((s) => s.count === 0)) {
    return <Empty>{t("analytics.empty.funnel")}</Empty>;
  }
  return (
    <ol className="space-y-2">
      {steps.map((step) => (
        <li key={step.stage}>
          <div className="flex items-baseline justify-between gap-2 text-xs mb-1">
            <span className="text-gray-300 truncate">{t(`analytics.stage.${step.stage}`)}</span>
            <span className="tabular-nums text-gray-400 shrink-0">
              {step.count}
              {step.pct_of_previous !== null && (
                <span
                  className={
                    step.pct_of_previous < 0.2 ? "text-amber-400 ml-1.5" : "text-gray-600 ml-1.5"
                  }
                  title={t("analytics.ofPrevious")}
                >
                  {Math.round(step.pct_of_previous * 100)}%
                </span>
              )}
            </span>
          </div>
          <div className="h-2.5 rounded bg-white/[0.04] overflow-hidden">
            <div
              className="h-full bg-eko-violet"
              style={{ width: `${Math.max((step.count / top) * 100, step.count > 0 ? 3 : 0)}%` }}
            />
          </div>
        </li>
      ))}
    </ol>
  );
}

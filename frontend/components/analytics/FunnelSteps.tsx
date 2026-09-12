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

/**
 * The two ways a visitor tries to reach the agency and nothing arrives.
 *
 * Both facts were already in the database and read by nothing. `form_error` was
 * stored from the day the tracker shipped; the lost-lead combination
 * (`form_submitted_at` set, `lead_id` null) is described in the code that
 * writes it — "pressed send and no lead ever arrived" — and no query ever asked
 * it. A funnel that goes quiet between "tapped" and "became a lead" cannot say
 * whether nobody tried or whether something ate them, and those need opposite
 * responses.
 *
 * Rendered only when non-zero: a row that always reads "0 lost" is furniture,
 * and furniture is what people stop seeing.
 */
function SilentLosses({
  lost,
  errors,
  people,
}: {
  lost: number;
  errors: number;
  people: number;
}) {
  const { t } = useI18n();
  if (lost === 0 && errors === 0) return null;
  return (
    <ul className="mt-3 space-y-1 border-t border-white/[0.06] pt-3 text-xs">
      {lost > 0 && (
        <li className="text-amber-400">
          {t("analytics.lostAfterSend").replace("{n}", String(lost))}
        </li>
      )}
      {errors > 0 && (
        <li className="text-amber-400">
          {t("analytics.formErrors")
            .replace("{n}", String(errors))
            .replace("{p}", String(people))}
        </li>
      )}
    </ul>
  );
}

export function FunnelSteps({
  steps,
  lost = 0,
  errors = 0,
  peopleWithErrors = 0,
}: {
  steps: FunnelStep[];
  lost?: number;
  errors?: number;
  peopleWithErrors?: number;
}) {
  const { t } = useI18n();
  const top = Math.max(1, ...steps.map((s) => s.count));
  if (steps.every((s) => s.count === 0)) {
    return <Empty>{t("analytics.empty.funnel")}</Empty>;
  }
  return (
    <>
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
    <SilentLosses lost={lost} errors={errors} people={peopleWithErrors} />
    </>
  );
}

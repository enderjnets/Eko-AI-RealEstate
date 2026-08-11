"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Bot, UserCheck, Loader2 } from "lucide-react";
import { leadsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function TakeoverToggle({
  leadId,
  initial,
  optedOut = false,
}: {
  leadId: number;
  initial: boolean;
  /** When the lead replied STOP the AI will not answer them whatever this
      toggle says, so the badge must not claim otherwise. Same failure as an
      Inbox badge that labelled web submissions "SMS pending": a control that
      states something false about what the system will do. */
  optedOut?: boolean;
}) {
  const router = useRouter();
  const { t } = useI18n();
  const [value, setValue] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function toggle() {
    const next = !value;
    setValue(next);
    setError(null);
    leadsApi
      .patch(leadId, { human_takeover: next })
      .then(() => {
        startTransition(() => router.refresh());
      })
      .catch((e) => {
        setError(String(e.message || e));
        setValue(!next);
      });
  }

  return (
    <div className="flex flex-col gap-1 items-end">
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
          value
            ? "bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/25"
            : "bg-eko-violet/15 text-eko-violet border-eko-violet/30 hover:bg-eko-violet/25"
        } ${optedOut ? "opacity-70" : ""} disabled:opacity-60 disabled:cursor-wait`}
        title={
          optedOut
            ? t("lead.optedOut")
            : value
              ? t("takeover.titleOn")
              : t("takeover.titleOff")
        }
      >
        {pending ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : value ? (
          <UserCheck className="w-3.5 h-3.5" />
        ) : (
          <Bot className="w-3.5 h-3.5" />
        )}
        {optedOut
          ? t("takeover.optedOut")
          : value
            ? t("takeover.human")
            : t("takeover.ai")}
      </button>
      {error && <span className="text-[10px] text-red-400">{error}</span>}
    </div>
  );
}

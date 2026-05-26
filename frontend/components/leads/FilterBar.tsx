"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { LeadIntent, LeadStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const STATUS_VALUES: (LeadStatus | "")[] = ["", "new", "qualified", "visiting", "post_visit", "won", "lost", "paused"];
const INTENT_VALUES: (LeadIntent | "")[] = ["", "rent", "buy", "valuation", "other"];

export function FilterBar() {
  const router = useRouter();
  const params = useSearchParams();
  const { t } = useI18n();
  const currentStatus = params.get("status") ?? "";
  const currentIntent = params.get("intent") ?? "";

  const statusLabel = (v: LeadStatus | "") => (v === "" ? t("filter.allStatuses") : t(`status.${v}`));
  const intentLabel = (v: LeadIntent | "") => (v === "" ? t("filter.allIntents") : t(`intent.${v}`));

  function update(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.push(`/leads${next.toString() ? `?${next.toString()}` : ""}`);
  }

  return (
    <div className="flex flex-wrap gap-2 items-center mb-4">
      <select
        value={currentStatus}
        onChange={(e) => update("status", e.target.value)}
        className="px-3 py-1.5 rounded-md bg-white/5 border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
      >
        {STATUS_VALUES.map((v) => (
          <option key={v} value={v} className="bg-eko-noir">
            {statusLabel(v)}
          </option>
        ))}
      </select>
      <select
        value={currentIntent}
        onChange={(e) => update("intent", e.target.value)}
        className="px-3 py-1.5 rounded-md bg-white/5 border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
      >
        {INTENT_VALUES.map((v) => (
          <option key={v} value={v} className="bg-eko-noir">
            {intentLabel(v)}
          </option>
        ))}
      </select>
      {(currentStatus || currentIntent) && (
        <button
          type="button"
          onClick={() => router.push("/leads")}
          className="px-3 py-1.5 rounded-md text-xs text-gray-400 hover:text-white border border-white/10 hover:bg-white/5"
        >
          {t("filter.clear")}
        </button>
      )}
    </div>
  );
}

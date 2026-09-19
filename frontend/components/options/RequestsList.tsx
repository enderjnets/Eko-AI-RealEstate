"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, PhoneCall } from "lucide-react";
import { type ListingRequest, optionsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function RequestsList() {
  const { t } = useI18n();
  const [items, setItems] = useState<ListingRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await optionsApi.list("all"));
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-10">
        <Loader2 className="w-4 h-4 animate-spin" />
      </div>
    );
  }
  if (error) return <div className="text-sm text-red-400 py-10">{error}</div>;
  if (items.length === 0) {
    return <div className="text-sm text-gray-500 py-10">{t("options.empty")}</div>;
  }

  return (
    <div className="space-y-2">
      {items.map((r) => (
        <Link
          key={r.id}
          href={`/options/${r.id}`}
          className="block rounded-xl border border-white/10 bg-white/[0.02] p-4 hover:border-eko-violet/30 transition-colors"
        >
          <div className="flex items-center gap-3">
            <div className="text-sm font-semibold text-white">
              {r.lead_name || r.lead_email || `Lead ${r.lead_id}`}
            </div>
            {r.status === "open" && (
              <span className="px-2 py-0.5 rounded text-[11px] bg-eko-violet/10 text-eko-violet border border-eko-violet/20">
                {t("options.open")}
              </span>
            )}
            {r.status === "callback_requested" && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-eko-green/10 text-eko-green border border-eko-green/20">
                <PhoneCall className="w-3 h-3" />
                {t("options.callbackAsked")}
              </span>
            )}
            <span className="ml-auto text-[11px] text-gray-500">
              {r.lead_zone || "—"}
            </span>
          </div>
          {r.they_wrote && (
            <div className="mt-2 text-[12px] text-gray-400 line-clamp-2">{r.they_wrote}</div>
          )}
          {r.callback_text && (
            <div className="mt-2 text-[12px] text-eko-green">{r.callback_text}</div>
          )}
        </Link>
      ))}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { Inbox, Loader2 } from "lucide-react";
import { type InboxFilter, type InboxList as InboxListData, inboxApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { InboxFilters } from "@/components/inbox/InboxFilters";
import { InboxRow } from "@/components/inbox/InboxRow";

export function InboxList() {
  const { t } = useI18n();
  const [filter, setFilter] = useState<InboxFilter>("pending");
  const [data, setData] = useState<InboxListData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((f: InboxFilter) => {
    setLoading(true);
    setError(null);
    inboxApi
      .list({ filter: f })
      .then(setData)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(filter);
  }, [filter, load]);

  // After marking handled: drop the row from the pending view + sync counts.
  const onHandled = useCallback(
    (leadId: number) => {
      setData((prev) => {
        if (!prev) return prev;
        const items =
          filter === "pending"
            ? prev.items.filter((it) => it.lead_id !== leadId)
            : prev.items.map((it) =>
                it.lead_id === leadId ? { ...it, needs_response: false } : it,
              );
        return { ...prev, items, pending_count: Math.max(0, prev.pending_count - 1) };
      });
    },
    [filter],
  );

  const emptyKey =
    filter === "pending"
      ? "inbox.empty.pending"
      : filter === "booked"
      ? "inbox.empty.booked"
      : "inbox.empty.all";

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <InboxFilters
          active={filter}
          pendingCount={data?.pending_count ?? 0}
          bookedCount={data?.booked_count ?? 0}
          onChange={setFilter}
        />
        <span className="text-[11px] text-gray-600 inline-flex items-center gap-1.5">
          {t("inbox.sortedByPriority")}
        </span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-gray-400 text-sm py-12 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> {t("inbox.loading")}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-300">
          {t("inbox.error")}: {error}
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-12 text-center text-gray-500 text-sm flex flex-col items-center gap-3">
          <Inbox className="w-8 h-8 text-gray-600" aria-hidden />
          {t(emptyKey)}
        </div>
      ) : (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] overflow-hidden">
          {data.items.map((item) => (
            <InboxRow key={item.lead_id} item={item} onHandled={onHandled} />
          ))}
        </div>
      )}
    </div>
  );
}

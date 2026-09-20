"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { type ListingRequestDetail, optionsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function money(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

export function OptionsPicker({ id }: { id: number }) {
  const { t } = useI18n();
  const [data, setData] = useState<ListingRequestDetail | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  // What she wants said about each one. Seeded from the generated line and
  // hers from the moment she touches it — the send only carries what is here,
  // and anything she leaves alone falls back to the same generated line on the
  // server, so an untouched box and an edited one behave identically.
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await optionsApi.get(id);
      setData(res);
      // Already sent: show what went out. Otherwise: the system's proposal,
      // ticked, up to the six she may send. The point of a proposal is that
      // she can untick two without going hunting.
      const alreadySent = res.request.selected_property_ids || [];
      setPicked(
        alreadySent.length > 0
          ? alreadySent
          : res.candidates
              .filter((c) => c.score != null)
              .slice(0, res.max_selected ?? 6)
              .map((c) => c.id),
      );
      const seeded: Record<number, string> = {};
      for (const c of res.candidates) if (c.reason) seeded[c.id] = c.reason;
      setReasons(seeded);
      setSent(res.request.status === "sent");
    } catch {
      setError(t("options.loadError"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  const max = data?.max_selected ?? 6;

  // Order matters: the email prints them in the order she ticked them, so a
  // toggle appends rather than re-sorting by id.
  const toggle = (pid: number) => {
    setPicked((current) =>
      current.includes(pid)
        ? current.filter((x) => x !== pid)
        : current.length >= max
          ? current
          : [...current, pid],
    );
  };

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      await optionsApi.send(
        id,
        picked,
        Object.fromEntries(picked.map((pid) => [pid, reasons[pid] ?? ""]).filter(([, v]) => v)),
      );
      setSent(true);
    } catch (e: unknown) {
      setError(`${t("options.sendError")}: ${String((e as Error)?.message || e)}`);
    } finally {
      setSending(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-10">
        <Loader2 className="w-4 h-4 animate-spin" />
      </div>
    );
  }
  if (!data) return <div className="text-sm text-red-400 py-10">{error}</div>;

  const r = data.request;
  return (
    <div className="space-y-6">
      <Link
        href="/options"
        className="inline-flex items-center gap-1.5 text-[12px] text-gray-500 hover:text-eko-violet"
      >
        <ArrowLeft className="w-3 h-3" />
        {t("options.backToList")}
      </Link>

      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-2">
        <div className="text-sm font-semibold text-white">
          {r.lead_name || r.lead_email || `Lead ${r.lead_id}`}
        </div>
        <div className="flex flex-wrap gap-4 text-[12px] text-gray-400">
          <span>{t("options.area")}: {r.lead_zone || "—"}</span>
          <span>{t("options.wants")}: {r.lead_intent || "—"}</span>
          <span>{t("options.timeline")}: {r.lead_urgency || "—"}</span>
        </div>
        {r.they_wrote && (
          <div className="text-[12px] text-gray-300 border-l-2 border-white/10 pl-3">
            <span className="text-gray-500">{t("options.theyWrote")}: </span>
            {r.they_wrote}
          </div>
        )}
      </div>

      {sent ? (
        <div className="flex items-center gap-2 text-sm text-eko-green">
          <Check className="w-4 h-4" />
          {t("options.sent")}
        </div>
      ) : data.candidates.length === 0 ? (
        <div className="text-sm text-gray-500">{t("options.noCandidates")}</div>
      ) : (
        <>
          <div className="flex items-center gap-3">
            <div className="text-[12px] text-gray-500">
              {t("options.pick").replace("{n}", String(max))}
            </div>
            <div className="ml-auto text-[12px] text-gray-400">
              {t("options.selected").replace("{n}", String(picked.length))}
            </div>
          </div>

          <div className="space-y-2">
            {data.candidates.map((c) => {
              const on = picked.includes(c.id);
              return (
                <label
                  key={c.id}
                  className={`flex items-start gap-3 rounded-xl border p-3 cursor-pointer transition-colors ${
                    on
                      ? "border-eko-violet/50 bg-eko-violet/5"
                      : "border-white/10 bg-white/[0.02] hover:border-white/20"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggle(c.id)}
                    className="mt-1"
                  />
                  <div className="min-w-0">
                    <div className="text-sm text-white">
                      {[c.address, c.city].filter(Boolean).join(", ") || "—"}
                    </div>
                    <div className="mt-0.5 text-[12px] text-gray-400">
                      {money(c.price)}
                      {c.bedrooms != null && ` · ${c.bedrooms} bd`}
                      {c.bathrooms != null && ` · ${Number(c.bathrooms)} ba`}
                      {c.sqft != null && ` · ${c.sqft.toLocaleString()} sq ft`}
                    </div>
                    {/* Colorado Rule 6.10.A.4. Shown here as well as in the
                        email so the person choosing can see whose listing she
                        is about to put in front of a consumer. */}
                    {c.listing_broker && (
                      <div className="mt-0.5 text-[10px] text-gray-500 italic">
                        {c.listing_broker}
                      </div>
                    )}

                    {/* What was compared, and what could not be. An `unknown`
                        is shown as a question and never as a tick: the MLS
                        export has no column for an office, and a shortlist
                        that quietly dropped the requirement would be worse
                        than one that admits it. */}
                    {c.checks.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                        {c.checks.map((k, i) => (
                          <span
                            key={`${c.id}-${i}`}
                            className={
                              k.status === "met"
                                ? "text-eko-green"
                                : k.status === "missed"
                                  ? "text-red-400"
                                  : "text-gray-500"
                            }
                          >
                            {k.status === "met" ? "✓" : k.status === "missed" ? "✗" : "?"}{" "}
                            {k.detail}
                          </span>
                        ))}
                      </div>
                    )}

                    {on && (
                      <div className="mt-2" onClick={(e) => e.preventDefault()}>
                        <label className="block text-[10px] uppercase tracking-wide text-gray-500">
                          {t("options.why")}
                        </label>
                        <textarea
                          value={reasons[c.id] ?? ""}
                          maxLength={240}
                          rows={2}
                          onChange={(e) =>
                            setReasons((r) => ({ ...r, [c.id]: e.target.value }))
                          }
                          placeholder={t("options.whyPlaceholder")}
                          className="mt-1 w-full rounded-md border border-white/10 bg-black/20 px-2 py-1.5 text-[12px] text-gray-200 focus:border-eko-violet/50 focus:outline-none"
                        />
                      </div>
                    )}
                  </div>
                </label>
              );
            })}
          </div>

          <button
            type="button"
            onClick={send}
            disabled={sending || picked.length === 0}
            className="px-4 py-2 rounded-lg bg-eko-violet/20 text-eko-violet border border-eko-violet/30 text-sm disabled:opacity-40"
          >
            {sending ? t("options.sending") : t("options.send")}
          </button>
        </>
      )}

      {error && <div className="text-sm text-red-400">{error}</div>}
    </div>
  );
}

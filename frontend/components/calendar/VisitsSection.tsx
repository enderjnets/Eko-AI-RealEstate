"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarCheck, CalendarPlus, Loader2, MapPin, X } from "lucide-react";
import { type Visit, visitsApi } from "@/lib/api";
import { VisitStatusBadge } from "@/components/ui/VisitStatusBadge";
import { BookingDialog } from "@/components/calendar/BookingDialog";
import { useI18n } from "@/lib/i18n";
import { useViewer } from "@/lib/useViewer";

const BROWSER_TZ =
  typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";

// Render a visit in ITS OWN timezone (the office tz stored on the visit), with the
// tz abbreviation, so "2 PM" is unambiguous regardless of where the realtor looks.
function fmtDateTime(iso: string, locale: string, tz: string): string {
  return new Date(iso).toLocaleString(locale, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz || BROWSER_TZ,
    timeZoneName: "short",
  });
}

function isPast(iso: string): boolean {
  return new Date(iso).getTime() < Date.now();
}

export function VisitsSection({
  leadId,
  reloadSignal = 0,
}: {
  leadId: number;
  /** Bumped when a booking is made elsewhere on the page. Without it the list
      below stays empty after booking from the matched listings, which invites
      a second attempt — and that creates a second real Cal.com booking. */
  reloadSignal?: number;
}) {
  const { t, locale } = useI18n();
  const isViewer = useViewer();
  const [visits, setVisits] = useState<Visit[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bookingOpen, setBookingOpen] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);

  // Two refreshes can now be in flight at once — cancel a visit, then book one
  // from the matched listings — and without a guard the slower first response
  // lands last and reverts the list to how it looked before the booking. That
  // is the exact appearance of failure that makes someone book a second time,
  // and a second booking is a second real invite in the lead's inbox.
  const latestRequest = useRef(0);

  const refresh = useCallback(() => {
    const request = ++latestRequest.current;
    setLoading(true);
    setError(null);
    visitsApi
      .list(leadId)
      .then((data) => {
        if (request === latestRequest.current) setVisits(data);
      })
      .catch((e) => {
        if (request === latestRequest.current) setError(String(e.message || e));
      })
      .finally(() => {
        if (request === latestRequest.current) setLoading(false);
      });
  }, [leadId]);

  useEffect(() => {
    refresh();
  }, [refresh, reloadSignal]);

  async function handleCancel(visitId: number) {
    if (!confirm(t("visits.confirmCancel"))) return;
    setCancellingId(visitId);
    try {
      await visitsApi.cancel(visitId, t("visits.cancelReason"));
      refresh();
    } catch (e: unknown) {
      alert(`${t("visits.cancelFailed")} ${(e as Error)?.message || e}`);
    } finally {
      setCancellingId(null);
    }
  }

  const upcoming = (visits ?? []).filter(
    (v) => v.status === "scheduled" || v.status === "confirmed",
  );
  const past = (visits ?? []).filter(
    (v) => v.status === "cancelled" || v.status === "completed" || v.status === "no_show",
  );

  return (
    <section className="mt-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm uppercase tracking-wider text-gray-500 flex items-center gap-2">
          <CalendarCheck className="w-3.5 h-3.5" />
          {t("visits.title")}
          {visits && (
            <span className="text-[10px] text-gray-600 normal-case tracking-normal">
              ({upcoming.length} {t("visits.upcoming")} · {past.length} {t("visits.archived")})
            </span>
          )}
        </h2>
        {!isViewer && (
          <button
            type="button"
            onClick={() => setBookingOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20"
          >
            <CalendarPlus className="w-3 h-3" />
            {t("visits.book")}
          </button>
        )}
      </div>

      {loading && !visits && (
        <div className="flex items-center gap-2 text-sm text-gray-500 py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t("visits.loading")}
        </div>
      )}
      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20">
          {error}
        </div>
      )}
      {visits && visits.length === 0 && (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 text-center text-gray-500 text-sm">
          {t("visits.empty.pre")}{" "}
          <span className="text-eko-violet">{t("visits.book")}</span> {t("visits.empty.post")}
        </div>
      )}

      {visits && visits.length > 0 && (
        <div className="space-y-2">
          {[...upcoming, ...past].map((v) => {
            const past_ = v.status === "cancelled" || v.status === "completed" || v.status === "no_show" || isPast(v.scheduled_at);
            return (
              <div
                key={v.id}
                className={`rounded-xl border bg-white/[0.02] px-4 py-3 flex items-start gap-3 ${
                  past_ ? "border-white/5 opacity-70" : "border-white/10"
                }`}
              >
                <CalendarCheck
                  className={`w-4 h-4 mt-0.5 shrink-0 ${
                    past_ ? "text-gray-600" : "text-eko-violet"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-white">
                      {fmtDateTime(v.scheduled_at, locale, v.timezone)}
                    </span>
                    <VisitStatusBadge status={v.status} />
                    <span className="text-[10px] text-gray-600">{v.duration_minutes} {t("visits.minutes")}</span>
                  </div>
                  {v.property_address && (
                    <div className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                      <MapPin className="w-3 h-3" />
                      {v.property_address}
                    </div>
                  )}
                  {v.notes && (
                    <div className="text-xs text-gray-500 mt-1 italic line-clamp-2">{v.notes}</div>
                  )}
                  <div className="text-[10px] text-gray-700 mt-1 font-mono truncate">
                    {v.calendar_provider} · {v.external_booking_id}
                  </div>
                </div>
                {!isViewer && (v.status === "scheduled" || v.status === "confirmed") && (
                  <button
                    type="button"
                    onClick={() => handleCancel(v.id)}
                    disabled={cancellingId === v.id}
                    className="p-1 rounded-md text-gray-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                    title={t("visits.cancelTitle")}
                  >
                    {cancellingId === v.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <X className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <BookingDialog
        open={bookingOpen}
        leadId={leadId}
        onClose={() => setBookingOpen(false)}
        onBooked={refresh}
      />
    </section>
  );
}

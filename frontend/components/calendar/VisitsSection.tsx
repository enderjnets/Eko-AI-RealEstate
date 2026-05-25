"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, CalendarPlus, Loader2, MapPin, X } from "lucide-react";
import { type Visit, visitsApi } from "@/lib/api";
import { VisitStatusBadge } from "@/components/ui/VisitStatusBadge";
import { BookingDialog } from "@/components/calendar/BookingDialog";

const TZ = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("es-ES", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TZ,
  });
}

function isPast(iso: string): boolean {
  return new Date(iso).getTime() < Date.now();
}

export function VisitsSection({ leadId }: { leadId: number }) {
  const [visits, setVisits] = useState<Visit[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bookingOpen, setBookingOpen] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    visitsApi
      .list(leadId)
      .then((data) => setVisits(data))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [leadId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCancel(visitId: number) {
    if (!confirm("¿Cancelar esta visita?")) return;
    setCancellingId(visitId);
    try {
      await visitsApi.cancel(visitId, "Cancelada desde dashboard");
      refresh();
    } catch (e: unknown) {
      alert(`No se pudo cancelar: ${(e as Error)?.message || e}`);
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
          Visitas
          {visits && (
            <span className="text-[10px] text-gray-600 normal-case tracking-normal">
              ({upcoming.length} próximas · {past.length} archivadas)
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={() => setBookingOpen(true)}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20"
        >
          <CalendarPlus className="w-3 h-3" />
          Agendar visita
        </button>
      </div>

      {loading && !visits && (
        <div className="flex items-center gap-2 text-sm text-gray-500 py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Cargando visitas…
        </div>
      )}
      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20">
          {error}
        </div>
      )}
      {visits && visits.length === 0 && (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 text-center text-gray-500 text-sm">
          Aún no hay visitas agendadas. Click en{" "}
          <span className="text-eko-violet">Agendar visita</span> para programar la primera.
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
                      {fmtDateTime(v.scheduled_at)}
                    </span>
                    <VisitStatusBadge status={v.status} />
                    <span className="text-[10px] text-gray-600">{v.duration_minutes} min</span>
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
                {(v.status === "scheduled" || v.status === "confirmed") && (
                  <button
                    type="button"
                    onClick={() => handleCancel(v.id)}
                    disabled={cancellingId === v.id}
                    className="p-1 rounded-md text-gray-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                    title="Cancelar visita"
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

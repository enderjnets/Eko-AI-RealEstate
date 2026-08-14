"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarPlus, Loader2, X } from "lucide-react";
import { type Slot, calendarApi, settingsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const DEFAULT_TZ =
  typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";

function fmtTime(iso: string, tz: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
}

function fmtDateKey(iso: string, tz: string, locale: string): string {
  return new Date(iso).toLocaleDateString(locale, {
    weekday: "long",
    day: "2-digit",
    month: "long",
    timeZone: tz,
  });
}

export function BookingDialog({
  open,
  leadId,
  onClose,
  onBooked,
  property,
}: {
  open: boolean;
  leadId: number;
  onClose: () => void;
  onBooked: () => void;
  /** Opened from a matched listing: which house, and its address prefilled. */
  property?: { id: number; address: string } | null;
}) {
  const { t, locale } = useI18n();
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [selected, setSelected] = useState<Slot | null>(null);
  const [address, setAddress] = useState(property?.address ?? "");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Book + display in the OFFICE timezone (from settings), not the browser's.
  const [tz, setTz] = useState(DEFAULT_TZ);

  useEffect(() => {
    if (!open) return;
    settingsApi
      .get()
      .then((s) => setTz(s.timezone || DEFAULT_TZ))
      .catch(() => {});
  }, [open]);

  // The dialog stays mounted between openings, so the address from the last
  // listing would otherwise still be sitting in the field for the next one.
  useEffect(() => {
    if (!open) return;
    setAddress(property?.address ?? "");
    // Notes too. They are about one specific viewing, so carrying them over
    // sends the note written for listing A out with listing B's booking.
    setNotes("");
  }, [open, property?.address]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    setSelected(null);
    calendarApi
      .slots(leadId, { days: 7, timezone: tz })
      .then((data) => setSlots(data.slots))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [open, leadId, tz]);

  const byDay = useMemo(() => {
    const grouped: Record<string, Slot[]> = {};
    for (const s of slots ?? []) {
      const key = fmtDateKey(s.start, tz, locale);
      (grouped[key] ||= []).push(s);
    }
    return grouped;
  }, [slots, tz, locale]);

  async function handleBook() {
    if (!selected || booking) return;
    setBooking(true);
    setError(null);
    try {
      await calendarApi.book(leadId, {
        start_time: selected.start,
        duration_minutes: 30,
        property_address: address.trim() || undefined,
        // Without the id the post-visit follow-up can only say "the property",
        // and nothing links the showing back to the listing it was for.
        property_id: property?.id,
        notes: notes.trim() || undefined,
        timezone: tz,
      });
      onBooked();
      onClose();
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setBooking(false);
    }
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative bg-eko-noir border border-white/10 rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <CalendarPlus className="w-4 h-4 text-eko-violet" />
            <h2 className="text-base font-semibold text-white">{t("booking.title")}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md text-gray-400 hover:text-white hover:bg-white/5"
            aria-label={t("booking.close")}
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-gray-400 py-8 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t("booking.loadingSlots")}
            </div>
          )}
          {error && (
            <div className="text-sm text-red-300 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20">
              {error}
            </div>
          )}
          {!loading && slots && slots.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-8">
              {t("booking.noSlots")}
            </p>
          )}

          {!loading &&
            Object.entries(byDay).map(([dayLabel, daySlots]) => (
              <div key={dayLabel}>
                <h3 className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">
                  {dayLabel}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {daySlots.map((s) => {
                    const selectedThis = selected?.start === s.start;
                    return (
                      <button
                        key={s.start}
                        type="button"
                        onClick={() => setSelected(s)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                          selectedThis
                            ? "bg-eko-violet text-white border-eko-violet"
                            : "bg-white/[0.03] text-gray-300 border-white/10 hover:bg-eko-violet/10 hover:border-eko-violet/30"
                        }`}
                      >
                        {fmtTime(s.start, tz, locale)}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}

          {selected && (
            <div className="pt-3 border-t border-white/5 space-y-3">
              <div className="rounded-md bg-eko-violet/10 border border-eko-violet/20 px-3 py-2 text-sm text-white">
                <span className="text-eko-violet font-medium">{t("booking.selected")}</span>{" "}
                {fmtDateKey(selected.start, tz, locale)} · {fmtTime(selected.start, tz, locale)} ({tz})
              </div>
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider text-gray-500 block mb-1">
                  {t("booking.address")} ({t("common.optional")})
                </span>
                <input
                  type="text"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder={t("booking.addressPlaceholder")}
                  className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
                />
              </label>
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider text-gray-500 block mb-1">
                  {t("booking.notes")} ({t("common.optional")})
                </span>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value.slice(0, 800))}
                  rows={2}
                  placeholder={t("booking.notesPlaceholder")}
                  className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50 resize-y"
                />
              </label>
            </div>
          )}
        </div>

        <footer className="px-5 py-3 border-t border-white/5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white border border-white/10 hover:bg-white/5"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={handleBook}
            disabled={!selected || booking}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {booking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CalendarPlus className="w-3.5 h-3.5" />}
            {t("booking.confirm")}
          </button>
        </footer>
      </div>
    </div>
  );
}

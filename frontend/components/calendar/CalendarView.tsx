"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Clock,
  Home,
  Loader2,
  MapPin,
  User,
  X,
} from "lucide-react";
import { type CalendarItem, visitsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const BROWSER_TZ =
  typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";

// YYYY-MM-DD for an instant rendered in a given tz (en-CA yields ISO date order).
function dayKey(iso: string, tz: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: tz });
}

function fmtTime(iso: string, tz: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
}

const KIND_ICON = { visit: Home, event: CalendarDays, followup: Clock } as const;
const KIND_ACCENT = {
  visit: "text-eko-violet",
  event: "text-eko-green",
  followup: "text-amber-300",
} as const;

export function CalendarView() {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<CalendarItem[] | null>(null);
  const [tz, setTz] = useState(BROWSER_TZ);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"agenda" | "month">("agenda");
  const [addOpen, setAddOpen] = useState(false);
  // Month grid cursor (calendar Y/M).
  const today = new Date();
  const [cursor, setCursor] = useState({ y: today.getFullYear(), m: today.getMonth() });

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    visitsApi
      .agenda(90)
      .then((r) => {
        setItems(r.items);
        setTz(r.timezone || BROWSER_TZ);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const todayKey = dayKey(new Date().toISOString(), tz);
  const tomorrowKey = dayKey(new Date(Date.now() + 86400000).toISOString(), tz);

  // Agenda: group by day key, in chronological order.
  const grouped = useMemo(() => {
    const g = new Map<string, CalendarItem[]>();
    for (const it of items ?? []) {
      const k = dayKey(it.scheduled_at, tz);
      (g.get(k) ?? g.set(k, []).get(k)!).push(it);
    }
    return [...g.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [items, tz]);

  function dayLabel(key: string): string {
    if (key === todayKey) return t("calendar.today");
    if (key === tomorrowKey) return t("calendar.tomorrow");
    // key is YYYY-MM-DD → render a friendly date
    const [y, m, d] = key.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(locale, {
      weekday: "long",
      day: "2-digit",
      month: "long",
    });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-white/10 overflow-hidden">
          {(["agenda", "month"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`px-3 py-1.5 text-xs font-medium ${
                view === v ? "bg-eko-violet text-white" : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}
            >
              {t(`calendar.${v}`)}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark"
        >
          <CalendarPlus className="w-3.5 h-3.5" />
          {t("calendar.addEvent")}
        </button>
      </div>

      {loading && !items && (
        <div className="flex items-center gap-2 text-sm text-gray-500 py-10 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> {t("calendar.loading")}
        </div>
      )}
      {error && (
        <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
          {error}
        </div>
      )}

      {items && view === "agenda" && (
        <AgendaList
          grouped={grouped}
          tz={tz}
          locale={locale}
          dayLabel={dayLabel}
          t={t}
        />
      )}

      {items && view === "month" && (
        <MonthGrid
          items={items}
          tz={tz}
          locale={locale}
          cursor={cursor}
          setCursor={setCursor}
          todayKey={todayKey}
          t={t}
        />
      )}

      {addOpen && (
        <AddEventDialog
          tz={tz}
          onClose={() => setAddOpen(false)}
          onSaved={() => {
            setAddOpen(false);
            refresh();
          }}
          t={t}
        />
      )}
    </div>
  );
}

// ── Agenda ───────────────────────────────────────────────────────────────

function ItemRow({
  it,
  tz,
  locale,
  t,
}: {
  it: CalendarItem;
  tz: string;
  locale: string;
  t: (k: string) => string;
}) {
  const Icon = KIND_ICON[it.kind] ?? CalendarDays;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3">
      <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${KIND_ACCENT[it.kind]}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-white">{fmtTime(it.scheduled_at, tz, locale)}</span>
          <span className="text-sm text-gray-200 truncate">{it.title}</span>
          <span className="text-[10px] uppercase tracking-wider text-gray-600">
            {t(`calendar.kind.${it.kind}`)}
          </span>
        </div>
        {it.lead_name && it.kind !== "event" && (
          <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-1">
            <User className="w-3 h-3" /> {it.lead_name}
          </div>
        )}
        {it.property_address && (
          <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-1">
            <MapPin className="w-3 h-3" /> {it.property_address}
          </div>
        )}
      </div>
      {it.lead_id && (
        <a href={`/leads/${it.lead_id}`} className="text-[11px] text-eko-violet hover:underline shrink-0">
          {t("calendar.openLead")}
        </a>
      )}
    </div>
  );
}

function AgendaList({
  grouped,
  tz,
  locale,
  dayLabel,
  t,
}: {
  grouped: [string, CalendarItem[]][];
  tz: string;
  locale: string;
  dayLabel: (k: string) => string;
  t: (k: string) => string;
}) {
  if (grouped.length === 0) {
    return (
      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-10 text-center text-gray-500 text-sm">
        {t("calendar.empty")}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      {grouped.map(([key, dayItems]) => (
        <div key={key}>
          <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2">{dayLabel(key)}</h3>
          <div className="space-y-2">
            {dayItems
              .slice()
              .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
              .map((it) => (
                <ItemRow key={`${it.kind}-${it.id}`} it={it} tz={tz} locale={locale} t={t} />
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Month grid ─────────────────────────────────────────────────────────────

function MonthGrid({
  items,
  tz,
  locale,
  cursor,
  setCursor,
  todayKey,
  t,
}: {
  items: CalendarItem[];
  tz: string;
  locale: string;
  cursor: { y: number; m: number };
  setCursor: (c: { y: number; m: number }) => void;
  todayKey: string;
  t: (k: string) => string;
}) {
  const byDay = useMemo(() => {
    const m = new Map<string, CalendarItem[]>();
    for (const it of items) {
      const k = dayKey(it.scheduled_at, tz);
      (m.get(k) ?? m.set(k, []).get(k)!).push(it);
    }
    return m;
  }, [items, tz]);

  const first = new Date(cursor.y, cursor.m, 1);
  const monthLabel = first.toLocaleDateString(locale, { month: "long", year: "numeric" });
  const startWeekday = first.getDay(); // 0=Sun
  const daysInMonth = new Date(cursor.y, cursor.m + 1, 0).getDate();
  const cells: ({ day: number; key: string } | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${cursor.y}-${String(cursor.m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ day: d, key });
  }

  const shift = (delta: number) => {
    const m = cursor.m + delta;
    setCursor({ y: cursor.y + Math.floor(m / 12), m: ((m % 12) + 12) % 12 });
  };

  const dow = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <button type="button" onClick={() => shift(-1)} className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-white/5">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-sm font-semibold text-white capitalize">{monthLabel}</span>
        <button type="button" onClick={() => shift(1)} className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-white/5">
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px] text-gray-600 mb-1">
        {dow.map((d) => (
          <div key={d}>{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((c, i) => {
          if (!c) return <div key={`e${i}`} />;
          const dayItems = byDay.get(c.key) ?? [];
          const isToday = c.key === todayKey;
          return (
            <div
              key={c.key}
              className={`min-h-[72px] rounded-lg border p-1 text-left ${
                isToday ? "border-eko-violet/50 bg-eko-violet/5" : "border-white/5 bg-white/[0.02]"
              }`}
            >
              <div className={`text-[10px] mb-0.5 ${isToday ? "text-eko-violet font-semibold" : "text-gray-500"}`}>
                {c.day}
              </div>
              <div className="space-y-0.5">
                {dayItems.slice(0, 3).map((it) => (
                  <div
                    key={`${it.kind}-${it.id}`}
                    title={it.title}
                    className={`truncate text-[9px] px-1 py-0.5 rounded ${
                      it.kind === "visit"
                        ? "bg-eko-violet/15 text-eko-violet"
                        : it.kind === "event"
                          ? "bg-eko-green/15 text-eko-green"
                          : "bg-amber-500/15 text-amber-300"
                    }`}
                  >
                    {fmtTime(it.scheduled_at, tz, locale)} {it.title}
                  </div>
                ))}
                {dayItems.length > 3 && (
                  <div className="text-[9px] text-gray-500 px-1">+{dayItems.length - 3}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-gray-600 mt-2">{t("calendar.monthWindowNote")}</p>
    </div>
  );
}

// ── Add event dialog ─────────────────────────────────────────────────────

function AddEventDialog({
  tz,
  onClose,
  onSaved,
  t,
}: {
  tz: string;
  onClose: () => void;
  onSaved: () => void;
  t: (k: string) => string;
}) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("10:00");
  const [duration, setDuration] = useState(60);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!title.trim() || !date || saving) return;
    setSaving(true);
    setError(null);
    try {
      // Send a NAIVE local wall-clock; the backend localizes it to the office tz.
      await visitsApi.createEvent({
        title: title.trim(),
        scheduled_at: `${date}T${time}:00`,
        duration_minutes: duration,
        notes: notes.trim() || undefined,
      });
      onSaved();
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative bg-eko-noir border border-white/10 rounded-2xl max-w-md w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <CalendarPlus className="w-4 h-4 text-eko-violet" /> {t("calendar.newEvent")}
          </h2>
          <button type="button" onClick={onClose} className="p-1 rounded-md text-gray-400 hover:text-white hover:bg-white/5">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs text-gray-400">{t("calendar.fTitle")}</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-gray-400">{t("calendar.fDate")}</span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
              />
            </label>
            <label className="block">
              <span className="text-xs text-gray-400">{t("calendar.fTime")}</span>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-gray-400">{t("calendar.fDuration")}</span>
            <input
              type="number"
              min={5}
              max={600}
              value={duration}
              onChange={(e) => setDuration(Math.max(5, Math.min(600, Number(e.target.value) || 60)))}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-400">{t("calendar.fNotes")}</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 800))}
              rows={2}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50 resize-y"
            />
          </label>
          <p className="text-[10px] text-gray-600">{t("calendar.tzNote")} {tz}</p>
          {error && <p className="text-[11px] text-red-300">{error}</p>}
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button type="button" onClick={onClose} className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white border border-white/10 hover:bg-white/5">
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!title.trim() || !date || saving}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CalendarPlus className="w-3.5 h-3.5" />}
            {t("calendar.save")}
          </button>
        </div>
      </div>
    </div>
  );
}

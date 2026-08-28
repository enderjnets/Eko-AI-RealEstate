"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, Loader2, Plus, Trash2 } from "lucide-react";
import {
  ActivityAvailability,
  AppointmentActivity,
  AvailabilityWindow,
  MyAvailability as MyAvailabilityData,
  availabilityApi,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// 0 = Monday, matching the backend and Python's `date.weekday()`. Not
// `Date.getDay()`, which starts on Sunday — the mismatch is a classic
// off-by-one that would silently move every window one day.
const DAY_KEYS = [
  "availability.day.mon",
  "availability.day.tue",
  "availability.day.wed",
  "availability.day.thu",
  "availability.day.fri",
  "availability.day.sat",
  "availability.day.sun",
] as const;

function emptyWindow(): AvailabilityWindow {
  return { days: [], start: "09:00", end: "17:00" };
}

export function MyAvailability() {
  const { t } = useI18n();
  const [data, setData] = useState<MyAvailabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<AppointmentActivity>("showing");
  const [draft, setDraft] = useState<AvailabilityWindow[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await availabilityApi.mine();
      setData(body);
      const first = body.activities.find((a) => a.activity === current);
      setDraft(first ? first.windows.map((w) => ({ ...w, days: [...w.days] })) : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
    // `current` deliberately excluded: switching tabs must not refetch and
    // silently discard unsaved edits. `selectActivity` handles the swap.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function selectActivity(activity: AppointmentActivity) {
    const found = data?.activities.find((a) => a.activity === activity);
    setCurrent(activity);
    setDraft(found ? found.windows.map((w) => ({ ...w, days: [...w.days] })) : []);
    setSaved(false);
    setError(null);
  }

  function toggleDay(index: number, day: number) {
    setDraft((prev) =>
      prev.map((w, i) =>
        i === index
          ? {
              ...w,
              days: w.days.includes(day)
                ? w.days.filter((d) => d !== day)
                : [...w.days, day].sort((a, b) => a - b),
            }
          : w,
      ),
    );
    setSaved(false);
  }

  function patchWindow(index: number, patch: Partial<AvailabilityWindow>) {
    setDraft((prev) => prev.map((w, i) => (i === index ? { ...w, ...patch } : w)));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const stored = await availabilityApi.setActivity(current, { windows: draft });
      // Show what Cal.com kept, not what was typed: if it normalised or
      // dropped something, the agent must see the hours actually in force.
      setDraft(stored.windows.map((w) => ({ ...w, days: [...w.days] })));
      setData((prev) =>
        prev
          ? {
              ...prev,
              activities: prev.activities.map((a) =>
                a.activity === current ? stored : a,
              ),
            }
          : prev,
      );
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t("common.loading")}
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-300">
        {error}
      </div>
    );
  }

  const activity: ActivityAvailability | undefined = data?.activities.find(
    (a) => a.activity === current,
  );

  return (
    <div className="space-y-6">
      {data?.unavailable_reason && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-300 flex gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-medium">{t("availability.inert.title")}</div>
            <div className="text-amber-200/80 mt-1">{data.unavailable_reason}</div>
          </div>
        </div>
      )}

      <div className="text-sm text-gray-400">
        {t("availability.intro", { timezone: data?.timezone ?? "UTC" })}
      </div>

      <div className="flex flex-wrap gap-2">
        {(data?.activities ?? []).map((a) => (
          <button
            key={a.activity}
            onClick={() => selectActivity(a.activity)}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              a.activity === current
                ? "bg-eko-violet text-white"
                : "bg-white/5 text-gray-300 hover:bg-white/10"
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>

      {activity && (
        <div className="text-xs text-gray-500">
          {t("availability.duration", { minutes: String(activity.duration_minutes) })}
        </div>
      )}

      <div className="space-y-3">
        {draft.length === 0 && (
          <div className="rounded-lg border border-white/10 bg-white/5 p-4 text-sm text-gray-400">
            {t("availability.empty")}
          </div>
        )}

        {draft.map((w, i) => (
          <div
            key={i}
            className="rounded-lg border border-white/10 bg-white/5 p-4 space-y-3"
          >
            <div className="flex flex-wrap gap-1.5">
              {DAY_KEYS.map((key, day) => (
                <button
                  key={key}
                  onClick={() => toggleDay(i, day)}
                  className={`w-11 py-1 rounded text-xs transition-colors ${
                    w.days.includes(day)
                      ? "bg-eko-violet text-white"
                      : "bg-white/5 text-gray-400 hover:bg-white/10"
                  }`}
                >
                  {t(key)}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                type="time"
                value={w.start}
                onChange={(e) => patchWindow(i, { start: e.target.value })}
                className="bg-white/5 border border-white/10 rounded px-2 py-1 text-sm text-white"
              />
              <span className="text-gray-500 text-sm">–</span>
              <input
                type="time"
                value={w.end}
                onChange={(e) => patchWindow(i, { end: e.target.value })}
                className="bg-white/5 border border-white/10 rounded px-2 py-1 text-sm text-white"
              />
              <button
                onClick={() => {
                  setDraft((prev) => prev.filter((_, k) => k !== i));
                  setSaved(false);
                }}
                aria-label={t("availability.removeWindow")}
                className="ml-auto p-1.5 rounded text-gray-400 hover:text-red-300 hover:bg-red-500/10"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => {
            setDraft((prev) => [...prev, emptyWindow()]);
            setSaved(false);
          }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-white/5 text-gray-300 hover:bg-white/10"
        >
          <Plus className="w-4 h-4" />
          {t("availability.addWindow")}
        </button>
        <button
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-md text-sm bg-eko-violet text-white hover:opacity-90 disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {t("common.save")}
        </button>
        {saved && (
          <span className="inline-flex items-center gap-1 text-sm text-green-400">
            <Check className="w-4 h-4" />
            {t("availability.saved")}
          </span>
        )}
      </div>

      {error && data && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}

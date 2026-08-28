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
  // One draft per activity, not one shared draft. With a single draft,
  // switching tabs overwrote it from the server copy and unsaved edits vanished
  // with no warning — the comment on `load` claimed tab switching would not do
  // that, and `selectActivity` did exactly it. An audit caught the gap between
  // the comment and the code.
  const [drafts, setDrafts] = useState<Partial<Record<AppointmentActivity, AvailabilityWindow[]>>>({});
  const draft = drafts[current] ?? [];
  const setDraft = useCallback(
    (next: AvailabilityWindow[] | ((prev: AvailabilityWindow[]) => AvailabilityWindow[])) => {
      setDrafts((prev) => {
        const previous = prev[current] ?? [];
        return {
          ...prev,
          [current]: typeof next === "function" ? next(previous) : next,
        };
      });
    },
    [current],
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await availabilityApi.mine();
      setData(body);
      // Seed every activity at once, so switching tabs never needs the server.
      const seeded: Partial<Record<AppointmentActivity, AvailabilityWindow[]>> = {};
      for (const a of body.activities) {
        seeded[a.activity] = a.windows.map((w) => ({ ...w, days: [...w.days] }));
      }
      setDrafts(seeded);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function selectActivity(activity: AppointmentActivity) {
    // Only the selection changes. The other tabs' drafts stay exactly as the
    // person left them, which is what "switching tabs must not discard unsaved
    // edits" actually requires.
    setCurrent(activity);
    setSaved(false);
    setError(null);
  }

  /** Has this tab been edited since the last load or save? Drives the marker
      that tells somebody they have something unsaved before they walk away. */
  function isDirty(activity: AppointmentActivity): boolean {
    const server = data?.activities.find((a) => a.activity === activity)?.windows ?? [];
    const local = drafts[activity];
    if (!local) return false;
    return JSON.stringify(local) !== JSON.stringify(server);
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
  // Nothing here can be saved while the calendar is inert: the PUT answers 409.
  // Leaving Add/Save enabled turned the amber notice into a dead end — press
  // Save, get a raw error. The notice explains; the controls must agree with it.
  const inert = Boolean(data?.unavailable_reason);

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
            {isDirty(a.activity) && (
              <span
                className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-amber-400 align-middle"
                aria-label={t("availability.unsaved")}
              />
            )}
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
          disabled={inert}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm bg-white/5 text-gray-300 hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus className="w-4 h-4" />
          {t("availability.addWindow")}
        </button>
        <button
          onClick={save}
          disabled={saving || inert}
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

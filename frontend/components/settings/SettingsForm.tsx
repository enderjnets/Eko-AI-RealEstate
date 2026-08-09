"use client";

import { useEffect, useState } from "react";
import { Building2, Check, Loader2, RotateCcw } from "lucide-react";
import { type AgencySettings, settingsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const KNOWN_LANGS: { code: string; label: string }[] = [
  { code: "es", label: "Español" },
  { code: "en", label: "English" },
  { code: "pt", label: "Português" },
  { code: "fr", label: "Français" },
];

const BROWSER_TZ =
  typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";

// A short curated list; the office's own tz is always added so the <select> can
// show it even if it's not here.
const COMMON_TZS = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
  "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
  "America/Mexico_City", "America/Bogota", "America/Argentina/Buenos_Aires",
  "America/Sao_Paulo", "Europe/Madrid", "Europe/London", "UTC",
];

type Hours = Record<string, { open: string; close: string } | null>;

export function SettingsForm() {
  const { t } = useI18n();
  const [data, setData] = useState<AgencySettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    settingsApi
      .get()
      .then(async (d) => {
        // Auto-configure the timezone by default: if it's still the unset default
        // (UTC) and the browser is in a different zone, detect + persist it once so
        // the voice agent books in the right local time without manual setup.
        if ((!d.timezone || d.timezone === "UTC") && BROWSER_TZ && BROWSER_TZ !== "UTC") {
          try {
            return setData(await settingsApi.update({ timezone: BROWSER_TZ }));
          } catch {
            return setData({ ...d, timezone: BROWSER_TZ });
          }
        }
        setData(d);
      })
      .catch((e) => setError(String((e as Error)?.message || e)))
      .finally(() => setLoading(false));
  }, []);

  function set<K extends keyof AgencySettings>(key: K, value: AgencySettings[K]) {
    setSaved(false);
    setData((d) => (d ? { ...d, [key]: value } : d));
  }

  function toggleLang(code: string) {
    if (!data) return;
    const has = data.languages.includes(code);
    const next = has ? data.languages.filter((l) => l !== code) : [...data.languages, code];
    if (next.length === 0) return; // never allow zero languages
    set("languages", next);
  }

  function setDay(day: string, value: { open: string; close: string } | null) {
    if (!data) return;
    set("business_hours", { ...(data.business_hours as Hours), [day]: value });
  }

  async function handleSave() {
    if (!data || saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await settingsApi.update({
        agency_name: data.agency_name,
        agency_phone: data.agency_phone,
        agent_persona: data.agent_persona,
        greeting_template: data.greeting_template,
        languages: data.languages,
        timezone: data.timezone,
        business_hours: data.business_hours,
      });
      setData(updated);
      setSaved(true);
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("settings.loading")}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
        {t("settings.loadError")}{error ? `: ${error}` : ""}.
      </div>
    );
  }

  const hours = data.business_hours as Hours;

  return (
    <div className="space-y-8">
      {/* Identidad */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <Building2 className="w-4 h-4 text-eko-violet" /> {t("settings.identity")}
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          {t("settings.identityHint")}
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-xs text-gray-400">{t("settings.agencyName")}</span>
            <input
              value={data.agency_name}
              onChange={(e) => set("agency_name", e.target.value)}
              maxLength={160}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-400">{t("settings.agencyPhone")}</span>
            <input
              value={data.agency_phone ?? ""}
              onChange={(e) => set("agency_phone", e.target.value || null)}
              maxLength={32}
              placeholder="+1-305-555-0100"
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-400">{t("settings.bookingEmail")}</span>
            <input
              type="email"
              value={data.booking_contact_email ?? ""}
              onChange={(e) => set("booking_contact_email", e.target.value || null)}
              maxLength={255}
              placeholder="visits@youragency.com"
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
            />
            <span className="mt-1 block text-[11px] text-gray-500">
              {t("settings.bookingEmailHelp")}
            </span>
          </label>
        </div>
      </section>

      {/* Persona + saludo */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1">{t("settings.persona")}</h2>
        <p className="text-xs text-gray-500 mb-4">
          {t("settings.personaHint", { token: "{agency_name}" })}
        </p>
        <label className="block mb-4">
          <span className="text-xs text-gray-400">{t("settings.personaLabel")}</span>
          <textarea
            value={data.agent_persona}
            onChange={(e) => set("agent_persona", e.target.value)}
            rows={5}
            className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50 resize-y leading-relaxed"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-400">{t("settings.greeting")}</span>
          <textarea
            value={data.greeting_template}
            onChange={(e) => set("greeting_template", e.target.value)}
            rows={3}
            className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50 resize-y leading-relaxed"
          />
        </label>
      </section>

      {/* Idiomas */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1">{t("settings.languages")}</h2>
        <p className="text-xs text-gray-500 mb-4">
          {t("settings.languagesHint")}
        </p>
        <div className="flex flex-wrap gap-2">
          {KNOWN_LANGS.map(({ code, label }) => {
            const on = data.languages.includes(code);
            return (
              <button
                key={code}
                type="button"
                onClick={() => toggleLang(code)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  on
                    ? "bg-eko-violet/15 text-eko-violet border-eko-violet/40"
                    : "bg-white/[0.03] text-gray-400 border-white/10 hover:border-white/20"
                }`}
              >
                {on && <Check className="w-3 h-3 inline mr-1" />}
                {label} <span className="text-gray-600">·{code}</span>
              </button>
            );
          })}
        </div>
      </section>

      {/* Zona horaria */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1">{t("settings.timezone")}</h2>
        <p className="text-xs text-gray-500 mb-4">{t("settings.timezoneHint")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={data.timezone}
            onChange={(e) => set("timezone", e.target.value)}
            className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
          >
            {Array.from(new Set([data.timezone, ...COMMON_TZS])).map((z) => (
              <option key={z} value={z} className="bg-eko-noir">
                {z}
              </option>
            ))}
          </select>
          {data.timezone !== BROWSER_TZ && BROWSER_TZ && (
            <button
              type="button"
              onClick={() => set("timezone", BROWSER_TZ)}
              className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium border border-white/10 text-gray-300 hover:border-eko-violet/40 hover:text-eko-violet"
            >
              {t("settings.detectTz")} ({BROWSER_TZ})
            </button>
          )}
        </div>
      </section>

      {/* Horario */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1">{t("settings.hours")}</h2>
        <p className="text-xs text-gray-500 mb-4">
          {t("settings.hoursHint")}
        </p>
        <div className="space-y-2">
          {DAY_KEYS.map((key) => {
            const v = hours?.[key] ?? null;
            const open = v !== null;
            return (
              <div key={key} className="flex items-center gap-3 text-sm">
                <span className="w-24 text-gray-300">{t(`day.${key}`)}</span>
                <button
                  type="button"
                  onClick={() => setDay(key, open ? null : { open: "09:00", close: "19:00" })}
                  className={`px-2 py-0.5 rounded text-[11px] border ${
                    open
                      ? "bg-eko-green/15 text-eko-green border-eko-green/30"
                      : "bg-gray-500/15 text-gray-400 border-gray-500/30"
                  }`}
                >
                  {open ? t("settings.open") : t("settings.closed")}
                </button>
                {open && (
                  <>
                    <input
                      type="time"
                      value={v!.open}
                      onChange={(e) => setDay(key, { open: e.target.value, close: v!.close })}
                      className="px-2 py-1 rounded bg-white/[0.03] border border-white/10 text-xs text-white"
                    />
                    <span className="text-gray-600">–</span>
                    <input
                      type="time"
                      value={v!.close}
                      onChange={(e) => setDay(key, { open: v!.open, close: e.target.value })}
                      className="px-2 py-1 rounded bg-white/[0.03] border border-white/10 text-xs text-white"
                    />
                  </>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Save bar */}
      <div className="flex items-center justify-end gap-3 sticky bottom-4">
        {error && (
          <span className="text-[11px] text-red-300 px-2 py-1 rounded bg-red-500/10 border border-red-500/20">
            {error}
          </span>
        )}
        {saved && !error && (
          <span className="text-[11px] text-eko-green flex items-center gap-1">
            <Check className="w-3.5 h-3.5" /> {t("settings.saved")}
          </span>
        )}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50 shadow-lg shadow-eko-violet/20"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
          {t("settings.saveChanges")}
        </button>
      </div>
    </div>
  );
}

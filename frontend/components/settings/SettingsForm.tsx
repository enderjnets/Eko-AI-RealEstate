"use client";

import { useEffect, useState } from "react";
import { Building2, Check, Loader2, RotateCcw } from "lucide-react";
import { type AgencySettings, settingsApi } from "@/lib/api";

const DAYS: { key: string; label: string }[] = [
  { key: "monday", label: "Lunes" },
  { key: "tuesday", label: "Martes" },
  { key: "wednesday", label: "Miércoles" },
  { key: "thursday", label: "Jueves" },
  { key: "friday", label: "Viernes" },
  { key: "saturday", label: "Sábado" },
  { key: "sunday", label: "Domingo" },
];

const KNOWN_LANGS: { code: string; label: string }[] = [
  { code: "es", label: "Español" },
  { code: "en", label: "English" },
  { code: "pt", label: "Português" },
  { code: "fr", label: "Français" },
];

type Hours = Record<string, { open: string; close: string } | null>;

export function SettingsForm() {
  const [data, setData] = useState<AgencySettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    settingsApi
      .get()
      .then(setData)
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
        <Loader2 className="w-4 h-4 animate-spin" /> Cargando configuración…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-sm text-red-300 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
        No se pudo cargar la configuración{error ? `: ${error}` : ""}.
      </div>
    );
  }

  const hours = data.business_hours as Hours;

  return (
    <div className="space-y-8">
      {/* Identidad */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <Building2 className="w-4 h-4 text-eko-violet" /> Identidad de la inmobiliaria
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          El nombre y teléfono que tu agente IA usa al presentarse.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-xs text-gray-400">Nombre de la agencia</span>
            <input
              value={data.agency_name}
              onChange={(e) => set("agency_name", e.target.value)}
              maxLength={160}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-400">Teléfono (opcional)</span>
            <input
              value={data.agency_phone ?? ""}
              onChange={(e) => set("agency_phone", e.target.value || null)}
              maxLength={32}
              placeholder="+1-305-555-0100"
              className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
            />
          </label>
        </div>
      </section>

      {/* Persona + saludo */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1">Personalidad del agente</h2>
        <p className="text-xs text-gray-500 mb-4">
          Instrucciones de sistema que guían el tono y el comportamiento de las respuestas
          automáticas. Usá <code className="text-eko-violet">{"{agency_name}"}</code> y se
          reemplaza por el nombre de la agencia.
        </p>
        <label className="block mb-4">
          <span className="text-xs text-gray-400">Persona (system prompt)</span>
          <textarea
            value={data.agent_persona}
            onChange={(e) => set("agent_persona", e.target.value)}
            rows={5}
            className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50 resize-y leading-relaxed"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-400">Saludo inicial</span>
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
        <h2 className="text-sm font-semibold text-white mb-1">Idiomas</h2>
        <p className="text-xs text-gray-500 mb-4">
          El agente detecta el idioma del cliente y responde en el más cercano de esta lista.
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

      {/* Horario */}
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
        <h2 className="text-sm font-semibold text-white mb-1">Horario de atención</h2>
        <p className="text-xs text-gray-500 mb-4">
          Informativo: el agente responde 24/7, pero usa este horario para fijar expectativas
          (&ldquo;te contacta un agente humano mañana a las 9&rdquo;).
        </p>
        <div className="space-y-2">
          {DAYS.map(({ key, label }) => {
            const v = hours?.[key] ?? null;
            const open = v !== null;
            return (
              <div key={key} className="flex items-center gap-3 text-sm">
                <span className="w-24 text-gray-300">{label}</span>
                <button
                  type="button"
                  onClick={() => setDay(key, open ? null : { open: "09:00", close: "19:00" })}
                  className={`px-2 py-0.5 rounded text-[11px] border ${
                    open
                      ? "bg-eko-green/15 text-eko-green border-eko-green/30"
                      : "bg-gray-500/15 text-gray-400 border-gray-500/30"
                  }`}
                >
                  {open ? "Abierto" : "Cerrado"}
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
            <Check className="w-3.5 h-3.5" /> Guardado
          </span>
        )}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50 shadow-lg shadow-eko-violet/20"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
          Guardar cambios
        </button>
      </div>
    </div>
  );
}

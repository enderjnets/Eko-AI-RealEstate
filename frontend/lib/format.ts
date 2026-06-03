/**
 * Display formatters shared across dashboard components. Locale-aware: pass the
 * active `lang` ("en" | "es"); defaults to English. Budgets are USD (USA product).
 */

type Lang = "en" | "es";

const REL = {
  en: { now: "just now", min: (n: number) => `${n} min ago`, h: (n: number) => `${n} h ago`, d: (n: number) => `${n} d ago`, w: (n: number) => `${n} w ago` },
  es: { now: "ahora mismo", min: (n: number) => `hace ${n} min`, h: (n: number) => `hace ${n} h`, d: (n: number) => `hace ${n} d`, w: (n: number) => `hace ${n} sem` },
};

function loc(lang: Lang): string {
  return lang === "es" ? "es-ES" : "en-US";
}

export function relativeTime(isoString: string | null, lang: Lang = "en"): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  const r = REL[lang];
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return r.now;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return r.min(minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return r.h(hours);
  const days = Math.floor(hours / 24);
  if (days < 7) return r.d(days);
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return r.w(weeks);
  return d.toLocaleDateString(loc(lang), { day: "2-digit", month: "short" });
}

export function exactTime(isoString: string, lang: Lang = "en", timezone?: string): string {
  return new Date(isoString).toLocaleString(loc(lang), {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    ...(timezone ? { timeZone: timezone } : {}),
  });
}

export function formatBudget(min: string | null, max: string | null, lang: Lang = "en"): string | null {
  if (!min && !max) return null;
  const fmt = (v: string) =>
    Number(v).toLocaleString(loc(lang), { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (min && max && min !== max) return `${fmt(min)} – ${fmt(max)}`;
  if (max) return `≤ ${fmt(max)}`;
  if (min) return `≥ ${fmt(min)}`;
  return null;
}

export function shortPhone(phone: string): string {
  return phone.replace(/[^\d+]/g, "");
}

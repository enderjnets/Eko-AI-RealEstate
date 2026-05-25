/**
 * Display formatters shared across dashboard components.
 */

export function relativeTime(isoString: string | null): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return "ahora mismo";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `hace ${days} d`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `hace ${weeks} sem`;
  return d.toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
}

export function exactTime(isoString: string): string {
  return new Date(isoString).toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBudget(min: string | null, max: string | null): string | null {
  if (!min && !max) return null;
  const fmt = (v: string) => `${Number(v).toLocaleString("es-ES", { maximumFractionDigits: 0 })}€`;
  if (min && max && min !== max) return `${fmt(min)} – ${fmt(max)}`;
  if (max) return `≤ ${fmt(max)}`;
  if (min) return `≥ ${fmt(min)}`;
  return null;
}

export function shortPhone(phone: string): string {
  // Strip leading +, group last 4 visible.
  const clean = phone.replace(/[^\d+]/g, "");
  return clean;
}

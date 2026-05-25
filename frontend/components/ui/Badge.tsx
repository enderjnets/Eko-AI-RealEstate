import type { LeadIntent, LeadStatus } from "@/lib/api";

const STATUS_LABEL: Record<LeadStatus, string> = {
  new: "Nuevo",
  qualified: "Cualificado",
  visiting: "Visitando",
  post_visit: "Post-visita",
  won: "Cerrado",
  lost: "Perdido",
  paused: "Pausado",
};

const STATUS_COLOR: Record<LeadStatus, string> = {
  new: "bg-eko-violet/15 text-eko-violet border-eko-violet/30",
  qualified: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  visiting: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  post_visit: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  won: "bg-eko-green/15 text-eko-green border-eko-green/30",
  lost: "bg-red-500/15 text-red-400 border-red-500/30",
  paused: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

export function StatusBadge({ status }: { status: LeadStatus }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border ${STATUS_COLOR[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

const INTENT_LABEL: Record<LeadIntent, string> = {
  rent: "Alquiler",
  buy: "Compra",
  valuation: "Tasación",
  other: "Otro",
};

const INTENT_COLOR: Record<LeadIntent, string> = {
  rent: "bg-eko-magenta/15 text-eko-magenta border-eko-magenta/30",
  buy: "bg-eko-violet/15 text-eko-violet border-eko-violet/30",
  valuation: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  other: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

export function IntentBadge({ intent }: { intent: LeadIntent | null }) {
  if (!intent) return <span className="text-gray-600 text-[11px]">—</span>;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border ${INTENT_COLOR[intent]}`}
    >
      {INTENT_LABEL[intent]}
    </span>
  );
}

import { Bath, BedDouble, ExternalLink, MapPin, Ruler } from "lucide-react";
import type { Property } from "@/lib/api";

export function formatPrice(price: string | null): string {
  if (price === null) return "—";
  const n = Number(price);
  if (Number.isNaN(n)) return "—";
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
  // Heuristic: small amounts are monthly rents.
  return n < 10000 ? `${formatted}/mo` : formatted;
}

const TYPE_LABEL: Record<string, string> = {
  condo: "Condo",
  single_family: "Casa",
  townhouse: "Townhouse",
  apartment: "Apartamento",
  loft: "Loft",
  multi_unit: "Multi-unidad",
};

export function PropertyCard({ p, compact = false }: { p: Property; compact?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden hover:border-eko-violet/30 transition-colors">
      <div className={`bg-gradient-to-br from-eko-violet/20 to-eko-magenta/10 flex items-center justify-center ${compact ? "h-20" : "h-32"}`}>
        {p.photos?.[0] ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={p.photos[0]} alt={p.title} className="w-full h-full object-cover" />
        ) : (
          <MapPin className="w-6 h-6 text-eko-violet/50" />
        )}
      </div>
      <div className="p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="text-sm font-semibold text-white leading-snug line-clamp-2">{p.title}</div>
          <div className="text-sm font-bold text-eko-green whitespace-nowrap">{formatPrice(p.price)}</div>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px] text-gray-500">
          <MapPin className="w-3 h-3" />
          <span>{[p.zone, p.city].filter(Boolean).join(", ") || "—"}</span>
          {p.property_type && (
            <span className="ml-auto px-1.5 py-0.5 rounded bg-eko-violet/10 text-eko-violet border border-eko-violet/20">
              {TYPE_LABEL[p.property_type] || p.property_type}
            </span>
          )}
        </div>
        <div className="mt-2 flex items-center gap-3 text-[11px] text-gray-400">
          {p.bedrooms != null && (
            <span className="flex items-center gap-1"><BedDouble className="w-3 h-3" />{p.bedrooms}</span>
          )}
          {p.bathrooms != null && (
            <span className="flex items-center gap-1"><Bath className="w-3 h-3" />{Number(p.bathrooms)}</span>
          )}
          {p.sqft != null && (
            <span className="flex items-center gap-1"><Ruler className="w-3 h-3" />{p.sqft.toLocaleString()} ft²</span>
          )}
          {p.url && (
            <a href={p.url} target="_blank" rel="noopener noreferrer" className="ml-auto text-gray-500 hover:text-eko-violet" title="Ver ficha">
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

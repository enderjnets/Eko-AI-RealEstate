"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Home, Loader2, Send } from "lucide-react";
import { type Property, leadsApi } from "@/lib/api";
import { PropertyCard, formatPrice } from "@/components/properties/PropertyCard";

function propertyBlurb(p: Property): string {
  const bits = [
    p.title,
    formatPrice(p.price),
    [p.bedrooms ? `${p.bedrooms} hab` : null, p.bathrooms ? `${Number(p.bathrooms)} baños` : null]
      .filter(Boolean)
      .join(" · "),
    p.address,
    p.url,
  ].filter(Boolean);
  return `Te comparto una propiedad que puede encajar:\n\n${bits.join("\n")}`;
}

export function MatchesSection({ leadId }: { leadId: number }) {
  const router = useRouter();
  const [matches, setMatches] = useState<Property[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [sentIds, setSentIds] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    leadsApi
      .matches(leadId)
      .then((m) => mounted && setMatches(m))
      .catch((e) => mounted && setError(String((e as Error)?.message || e)))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [leadId]);

  async function sendProperty(p: Property) {
    if (sendingId) return;
    setSendingId(p.id);
    setError(null);
    try {
      const res = await leadsApi.sendMessage(leadId, propertyBlurb(p));
      if (res.status === "error") {
        setError(res.error || "No se pudo enviar");
        return;
      }
      setSentIds((prev) => new Set(prev).add(p.id));
      router.refresh();
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setSendingId(null);
    }
  }

  if (loading) {
    return (
      <section className="mt-6">
        <SectionHeader />
        <div className="flex items-center gap-2 text-gray-500 text-sm py-4">
          <Loader2 className="w-4 h-4 animate-spin" /> Buscando propiedades…
        </div>
      </section>
    );
  }

  return (
    <section className="mt-6">
      <SectionHeader count={matches?.length ?? 0} />
      {error && (
        <div className="text-[11px] text-red-300 mb-2 px-2 py-1 rounded bg-red-500/10 border border-red-500/20">
          {error}
        </div>
      )}
      {!matches || matches.length === 0 ? (
        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6 text-center text-gray-500 text-sm">
          No hay listings que encajen con la zona / presupuesto / intención de este lead.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {matches.map((p) => (
            <div key={p.id} className="relative">
              <PropertyCard p={p} compact />
              <button
                type="button"
                onClick={() => sendProperty(p)}
                disabled={sendingId === p.id || sentIds.has(p.id)}
                className="mt-1.5 w-full inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[11px] font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20 disabled:opacity-60"
              >
                {sentIds.has(p.id) ? (
                  <><Check className="w-3 h-3" /> Enviado al lead</>
                ) : sendingId === p.id ? (
                  <><Loader2 className="w-3 h-3 animate-spin" /> Enviando…</>
                ) : (
                  <><Send className="w-3 h-3" /> Enviar al lead</>
                )}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SectionHeader({ count }: { count?: number }) {
  return (
    <h2 className="text-sm uppercase tracking-wider text-gray-500 mb-3 flex items-center gap-2">
      <Home className="w-3.5 h-3.5" />
      Propiedades sugeridas
      {count != null && (
        <span className="text-[10px] text-gray-600 normal-case tracking-normal">({count})</span>
      )}
    </h2>
  );
}

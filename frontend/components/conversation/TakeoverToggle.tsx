"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Bot, UserCheck, Loader2 } from "lucide-react";
import { leadsApi } from "@/lib/api";

export function TakeoverToggle({
  leadId,
  initial,
}: {
  leadId: number;
  initial: boolean;
}) {
  const router = useRouter();
  const [value, setValue] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function toggle() {
    const next = !value;
    setValue(next);
    setError(null);
    leadsApi
      .patch(leadId, { human_takeover: next })
      .then(() => {
        startTransition(() => router.refresh());
      })
      .catch((e) => {
        setError(String(e.message || e));
        setValue(!next);
      });
  }

  return (
    <div className="flex flex-col gap-1 items-end">
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
          value
            ? "bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/25"
            : "bg-eko-violet/15 text-eko-violet border-eko-violet/30 hover:bg-eko-violet/25"
        } disabled:opacity-60 disabled:cursor-wait`}
        title={
          value
            ? "Estás respondiendo manualmente. El agente IA está pausado para este lead."
            : "El agente IA responde automáticamente. Click para tomar control humano."
        }
      >
        {pending ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : value ? (
          <UserCheck className="w-3.5 h-3.5" />
        ) : (
          <Bot className="w-3.5 h-3.5" />
        )}
        {value ? "Humano (IA pausada)" : "Agente IA activo"}
      </button>
      {error && <span className="text-[10px] text-red-400">{error}</span>}
    </div>
  );
}

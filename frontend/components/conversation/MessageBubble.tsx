import { Bot, Phone, User2 } from "lucide-react";
import type { Message } from "@/lib/api";
import { exactTime } from "@/lib/format";

const STATUS_LABEL: Record<Message["wa_status"], string> = {
  pending: "Pendiente",
  sent: "Enviado",
  delivered: "Entregado",
  read: "Leído",
  failed: "Fallo",
};

export function MessageBubble({ msg }: { msg: Message }) {
  const isInbound = msg.direction === "inbound";
  const isHuman = msg.sender === "human";
  const isAgent = msg.sender === "agent";

  const Icon = isInbound ? User2 : isAgent ? Bot : Phone;
  const senderLabel = isInbound ? "Cliente" : isAgent ? "Agente IA" : "Tú";

  return (
    <div className={`flex ${isInbound ? "justify-start" : "justify-end"} gap-2`}>
      {isInbound && (
        <div className="w-7 h-7 rounded-full bg-white/5 border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
          <Icon className="w-3.5 h-3.5 text-gray-400" aria-hidden />
        </div>
      )}
      <div className={`max-w-[78%] ${isInbound ? "" : "items-end"}`}>
        <div className="flex items-center gap-1.5 mb-0.5 text-[10px] text-gray-500">
          <span>{senderLabel}</span>
          {isAgent && msg.llm_provider && (
            <span className="text-[10px] px-1 rounded bg-eko-violet/10 text-eko-violet border border-eko-violet/20">
              {msg.llm_provider}
            </span>
          )}
          {isHuman && (
            <span className="text-[10px] px-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
              manual
            </span>
          )}
          <span>· {exactTime(msg.created_at)}</span>
        </div>
        <div
          className={`px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap leading-relaxed ${
            isInbound
              ? "bg-white/[0.05] border border-white/10 text-gray-100 rounded-tl-sm"
              : isHuman
              ? "bg-amber-500/10 border border-amber-500/20 text-amber-50 rounded-tr-sm"
              : "bg-eko-violet/15 border border-eko-violet/25 text-white rounded-tr-sm"
          }`}
        >
          {msg.content}
        </div>
        {!isInbound && (
          <div className="text-[10px] text-gray-600 mt-0.5 text-right">
            {STATUS_LABEL[msg.wa_status]}
          </div>
        )}
      </div>
      {!isInbound && (
        <div
          className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
            isHuman
              ? "bg-amber-500/15 border border-amber-500/30"
              : "bg-eko-violet/15 border border-eko-violet/30"
          }`}
        >
          <Icon className={`w-3.5 h-3.5 ${isHuman ? "text-amber-400" : "text-eko-violet"}`} aria-hidden />
        </div>
      )}
    </div>
  );
}

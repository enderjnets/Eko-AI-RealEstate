"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Send, Sparkles } from "lucide-react";
import { type SuggestionsResult, leadsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const MAX_LEN = 4000;

export function Composer({ leadId, channel }: { leadId: number; channel: string }) {
  const router = useRouter();
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [sending, setSending] = useState(false);
  const [, startTransition] = useTransition();

  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);

  async function handleSend() {
    if (!text.trim() || sending) return;
    setError(null);
    setSending(true);
    try {
      const result = await leadsApi.sendMessage(leadId, text.trim());
      if (result.status === "error") {
        setError(result.error || t("composer.unknownError"));
        return;
      }
      setText("");
      setSuggestions(null);
      // Refresh server data so the new outbound shows in the chat.
      startTransition(() => router.refresh());
    } catch (e: unknown) {
      setError(String((e as Error)?.message || e));
    } finally {
      setSending(false);
    }
  }

  async function handleSuggest() {
    if (suggesting) return;
    setSuggestionsError(null);
    setSuggestions(null);
    setSuggesting(true);
    try {
      const result: SuggestionsResult = await leadsApi.suggestions(leadId, 3);
      if (result.error && result.suggestions.length === 0) {
        setSuggestionsError(result.error);
        return;
      }
      setSuggestions(result.suggestions);
    } catch (e: unknown) {
      setSuggestionsError(String((e as Error)?.message || e));
    } finally {
      setSuggesting(false);
    }
  }

  return (
    <section className="mt-6 rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs uppercase tracking-wider text-gray-500">
          {t("composer.title", { channel })}
        </h3>
        <button
          type="button"
          onClick={handleSuggest}
          disabled={suggesting}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border border-eko-violet/30 bg-eko-violet/10 text-eko-violet hover:bg-eko-violet/20 disabled:opacity-60"
          title={t("composer.suggestTitle")}
        >
          {suggesting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
          {t("composer.suggest")}
        </button>
      </div>

      {suggestionsError && (
        <div className="text-[11px] text-red-300 mb-2 px-2 py-1 rounded bg-red-500/10 border border-red-500/20">
          {t("composer.suggestError")} {suggestionsError}
        </div>
      )}

      {suggestions && suggestions.length > 0 && (
        <div className="space-y-2 mb-3">
          {suggestions.map((s, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setText(s)}
              className="block w-full text-left text-sm text-gray-100 px-3 py-2 rounded-lg border border-white/10 bg-white/[0.03] hover:bg-eko-violet/10 hover:border-eko-violet/30 transition-colors leading-snug"
              title={t("composer.useSuggestion")}
            >
              <span className="text-[10px] text-eko-violet mr-2 font-medium">{i + 1}</span>
              {s}
            </button>
          ))}
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, MAX_LEN))}
        placeholder={t("composer.placeholder")}
        rows={4}
        className="w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50 resize-y leading-relaxed"
      />
      <div className="flex items-center justify-between mt-2">
        <div className="text-[10px] text-gray-600">
          {text.length}/{MAX_LEN} {t("composer.chars")}
        </div>
        <div className="flex items-center gap-2">
          {error && <span className="text-[11px] text-red-400 mr-2">{error}</span>}
          <button
            type="button"
            onClick={handleSend}
            disabled={!text.trim() || sending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            {t("composer.send")}
          </button>
        </div>
      </div>
    </section>
  );
}

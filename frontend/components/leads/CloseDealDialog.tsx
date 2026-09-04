"use client";

/**
 * What kind of business did we just close.
 *
 * Until this existed, "mark won" wrote a status and nothing else, so the
 * dashboard could say "we won three" and never what those three were — a
 * listing that sold, a buyer who bought and a rental are three different
 * businesses with three different economics behind one word.
 *
 * The kind is required and the amount is not, deliberately. The kind is known
 * the moment the deal closes and is unrecoverable afterwards: nobody remembers
 * in March what a particular close in September was. The commission often is
 * not known that day, and demanding it would fill the column with guesses that
 * later get averaged as if they were facts.
 */

import { useState } from "react";
import { Loader2, X } from "lucide-react";
import { WON_KINDS, type WonKind } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface Props {
  open: boolean;
  saving: boolean;
  onCancel: () => void;
  onConfirm: (kind: WonKind, value?: number) => void;
}

export function CloseDealDialog({ open, saving, onCancel, onConfirm }: Props) {
  const { t } = useI18n();
  const [kind, setKind] = useState<WonKind | "">("");
  const [amount, setAmount] = useState("");

  if (!open) return null;

  const parsed = amount.trim() === "" ? undefined : Number(amount);
  const amountInvalid = parsed !== undefined && (!Number.isFinite(parsed) || parsed < 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 p-0 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t("lead.close.title")}
    >
      <div className="w-full sm:max-w-sm rounded-t-2xl sm:rounded-2xl border border-white/10 bg-eko-noir p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-white">{t("lead.close.title")}</h2>
            <p className="text-xs text-white/50 mt-1">{t("lead.close.why")}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label={t("common.cancel")}
            className="text-white/40 hover:text-white p-1 -m-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <label className="block space-y-1.5">
          <span className="text-xs text-white/60">{t("lead.close.kind")}</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as WonKind | "")}
            className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2.5 text-sm text-white"
          >
            <option value="">{t("lead.close.pick")}</option>
            {WON_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`lead.close.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1.5">
          <span className="text-xs text-white/60">{t("lead.close.amount")}</span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder={t("lead.close.amountHint")}
            className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2.5 text-sm text-white"
          />
        </label>

        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-lg border border-white/10 px-3 py-2.5 text-sm text-white/70 hover:text-white"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            disabled={!kind || saving || amountInvalid}
            onClick={() => kind && onConfirm(kind, parsed)}
            className="flex-1 rounded-lg bg-eko-violet px-3 py-2.5 text-sm font-medium text-white disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {t("lead.close.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

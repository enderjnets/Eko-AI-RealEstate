"use client";

import { useEffect, useState } from "react";
import { Building2, Eye, Loader2, Mail, MapPin, Phone, Trash2, UserPlus } from "lucide-react";
import { type DemoAccount, accountsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { exactTime } from "@/lib/format";

function cleanError(e: unknown): string {
  return String((e as Error)?.message || e).replace(/^API \d+:\s*/, "");
}

export function RegistrationsPanel() {
  const { t, lang } = useI18n();
  const [accounts, setAccounts] = useState<DemoAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  function load() {
    accountsApi
      .list()
      .then(setAccounts)
      .catch((e) => setError(cleanError(e)));
  }

  useEffect(load, []);

  async function remove(a: DemoAccount) {
    if (busy) return;
    if (!window.confirm(`${t("settings.registrations.remove")}: ${a.email}?`)) return;
    setBusy(a.id);
    setError(null);
    try {
      await accountsApi.remove(a.id);
      load();
    } catch (err) {
      setError(cleanError(err));
    } finally {
      setBusy(null);
    }
  }

  const location = (a: DemoAccount) => [a.state, a.country].filter(Boolean).join(", ");

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
      <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
        <UserPlus className="w-4 h-4 text-eko-violet" /> {t("settings.registrations.title")}
        {accounts && (
          <span className="text-[10px] text-gray-600 font-normal">({accounts.length})</span>
        )}
      </h2>
      <p className="text-xs text-gray-500 mb-4">{t("settings.registrations.subtitle")}</p>

      {error && (
        <div className="text-[11px] text-red-300 px-2 py-1.5 mb-3 rounded bg-red-500/10 border border-red-500/20">
          {error}
        </div>
      )}

      {accounts === null && !error && (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> …
        </div>
      )}

      {accounts !== null && accounts.length === 0 && (
        <p className="text-xs text-gray-500">{t("settings.registrations.empty")}</p>
      )}

      {accounts !== null && accounts.length > 0 && (
        <ul className="divide-y divide-white/5">
          {accounts.map((a) => (
            <li key={a.id} className="flex items-start gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-white">{a.name}</span>
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border border-amber-500/30 bg-amber-500/10 text-amber-300">
                    <Eye className="w-3 h-3" /> {t("settings.registrations.viewer")}
                  </span>
                </div>
                <div className="mt-1 flex flex-col gap-0.5 text-xs text-gray-400">
                  <span className="inline-flex items-center gap-1.5 truncate">
                    <Mail className="w-3 h-3 shrink-0" /> {a.email}
                  </span>
                  {a.phone && (
                    <span className="inline-flex items-center gap-1.5">
                      <Phone className="w-3 h-3 shrink-0" /> {a.phone}
                    </span>
                  )}
                  {a.company && (
                    <span className="inline-flex items-center gap-1.5 truncate">
                      <Building2 className="w-3 h-3 shrink-0" /> {a.company}
                    </span>
                  )}
                  {(location(a) || a.address) && (
                    <span className="inline-flex items-center gap-1.5 truncate">
                      <MapPin className="w-3 h-3 shrink-0" />
                      {[a.address, location(a)].filter(Boolean).join(" · ")}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-[10px] text-gray-600">
                  {t("settings.registrations.registered")} {exactTime(a.created_at, lang)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => remove(a)}
                disabled={busy === a.id}
                title={t("settings.registrations.remove")}
                className="shrink-0 p-1 rounded-md text-gray-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-50"
              >
                {busy === a.id ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Trash2 className="w-3.5 h-3.5" />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

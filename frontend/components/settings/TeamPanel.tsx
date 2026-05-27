"use client";

import { useEffect, useState } from "react";
import { Crown, Loader2, Plus, Shield, Trash2, Users } from "lucide-react";
import { type Role, type TeamMember, teamApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function cleanError(e: unknown): string {
  const msg = String((e as Error)?.message || e);
  return msg.replace(/^API \d+:\s*/, "");
}

export function TeamPanel() {
  const { t } = useI18n();
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<Role>("member");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // email being mutated

  function load() {
    teamApi
      .list()
      .then(setMembers)
      .catch((e) => setError(cleanError(e)));
  }

  useEffect(load, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const email = newEmail.trim().toLowerCase();
    if (!email || adding) return;
    setAdding(true);
    setError(null);
    try {
      await teamApi.add(email, newRole);
      setNewEmail("");
      setNewRole("member");
      load();
    } catch (err) {
      setError(cleanError(err));
    } finally {
      setAdding(false);
    }
  }

  async function changeRole(m: TeamMember) {
    if (m.immutable || busy) return;
    setBusy(m.email);
    setError(null);
    try {
      await teamApi.updateRole(m.email, m.role === "admin" ? "member" : "admin");
      load();
    } catch (err) {
      setError(cleanError(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove(m: TeamMember) {
    if (m.immutable || busy) return;
    if (!window.confirm(`${t("settings.team.remove")}: ${m.email}?`)) return;
    setBusy(m.email);
    setError(null);
    try {
      await teamApi.remove(m.email);
      load();
    } catch (err) {
      setError(cleanError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
      <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
        <Users className="w-4 h-4 text-eko-violet" /> {t("settings.team.title")}
      </h2>
      <p className="text-xs text-gray-500 mb-4">{t("settings.team.subtitle")}</p>

      <form onSubmit={add} className="flex flex-col sm:flex-row gap-2 mb-4">
        <input
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          placeholder={t("settings.team.addPlaceholder")}
          className="flex-1 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50"
        />
        <select
          value={newRole}
          onChange={(e) => setNewRole(e.target.value as Role)}
          className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
        >
          <option value="member">{t("settings.team.roleMember")}</option>
          <option value="admin">{t("settings.team.roleAdmin")}</option>
        </select>
        <button
          type="submit"
          disabled={adding || !newEmail.trim()}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50"
        >
          {adding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          {adding ? t("settings.team.adding") : t("settings.team.add")}
        </button>
      </form>

      {error && (
        <div className="text-[11px] text-red-300 px-2 py-1.5 mb-3 rounded bg-red-500/10 border border-red-500/20">
          {error}
        </div>
      )}

      {members === null && !error && (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> …
        </div>
      )}

      {members !== null && members.length === 0 && (
        <p className="text-xs text-gray-500">{t("settings.team.empty")}</p>
      )}

      {members !== null && members.length > 0 && (
        <ul className="divide-y divide-white/5">
          {members.map((m) => (
            <li key={m.email} className="flex items-center gap-3 py-2.5">
              <span
                className={`shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border ${
                  m.role === "admin"
                    ? "bg-eko-violet/15 text-eko-violet border-eko-violet/40"
                    : "bg-white/[0.03] text-gray-400 border-white/10"
                }`}
              >
                {m.role === "admin" ? <Shield className="w-3 h-3" /> : null}
                {m.role === "admin" ? t("settings.team.roleAdmin") : t("settings.team.roleMember")}
              </span>
              <span className="flex-1 text-sm text-gray-200 truncate" title={m.email}>
                {m.email}
              </span>
              {m.immutable ? (
                <span
                  className="shrink-0 inline-flex items-center gap-1 text-[10px] text-amber-300/80"
                  title={t("settings.team.ownerHint")}
                >
                  <Crown className="w-3 h-3" /> {t("settings.team.owner")}
                </span>
              ) : (
                <div className="shrink-0 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => changeRole(m)}
                    disabled={busy === m.email}
                    className="text-[11px] text-gray-400 hover:text-white disabled:opacity-50"
                  >
                    {m.role === "admin"
                      ? t("settings.team.makeMember")
                      : t("settings.team.makeAdmin")}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(m)}
                    disabled={busy === m.email}
                    title={t("settings.team.remove")}
                    className="text-gray-500 hover:text-red-400 disabled:opacity-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

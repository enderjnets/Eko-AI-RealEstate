"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, Zap } from "lucide-react";
import { authApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";

export default function RegisterPage() {
  const router = useRouter();
  const { t } = useI18n();
  const [f, setF] = useState({
    name: "",
    email: "",
    password: "",
    phone: "",
    company: "",
    address: "",
    state: "",
    country: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (f.password.length < 8) {
      setError(t("register.errorPassword"));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await authApi.register({
        name: f.name.trim(),
        email: f.email.trim(),
        password: f.password,
        phone: f.phone.trim() || undefined,
        company: f.company.trim() || undefined,
        address: f.address.trim() || undefined,
        state: f.state.trim() || undefined,
        country: f.country.trim() || undefined,
      });
      router.replace("/leads");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("already_registered")) setError(t("register.errorDup"));
      else if (msg.includes("invalid_email")) setError(t("register.errorEmail"));
      else setError(t("register.errorGeneric"));
      setLoading(false);
    }
  }

  const field = (key: keyof typeof f, label: string, type = "text", required = false) => (
    <label className="block">
      <span className="text-xs text-gray-400">
        {label}
        {required && <span className="text-eko-violet"> *</span>}
      </span>
      <input
        type={type}
        value={f[key]}
        onChange={set(key)}
        required={required}
        autoComplete={type === "password" ? "new-password" : "on"}
        className="mt-1 w-full px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
      />
    </label>
  );

  return (
    <main className="min-h-screen flex items-center justify-center px-6 py-10">
      <div className="absolute top-4 right-4">
        <LanguageSwitcher />
      </div>
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-white/[0.02] p-7"
      >
        <div className="flex items-center gap-2.5 mb-6">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-eko-violet to-eko-magenta flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div className="font-semibold text-white">
            Eko AI <span className="text-eko-violet">Realtors</span>
          </div>
        </div>

        <h1 className="text-lg font-semibold text-white mb-1">{t("register.title")}</h1>
        <p className="text-xs text-gray-500 mb-5">{t("register.subtitle")}</p>

        <div className="space-y-3">
          {field("name", t("register.name"), "text", true)}
          <div className="grid sm:grid-cols-2 gap-3">
            {field("email", t("register.email"), "email", true)}
            {field("password", t("register.password"), "password", true)}
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {field("phone", t("register.phone"), "tel")}
            {field("company", t("register.company"))}
          </div>
          {field("address", t("register.address"))}
          <div className="grid sm:grid-cols-2 gap-3">
            {field("state", t("register.state"))}
            {field("country", t("register.country"))}
          </div>
        </div>

        {error && <p className="text-[11px] text-red-400 mt-3">{error}</p>}

        <button
          type="submit"
          disabled={loading || !f.name || !f.email || !f.password}
          className="mt-5 w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? t("register.submitting") : t("register.submit")}
        </button>

        <p className="text-[11px] text-gray-500 mt-4 text-center">
          {t("register.haveAccount")}{" "}
          <Link href="/login" className="text-eko-violet hover:underline">
            {t("register.signIn")}
          </Link>
        </p>
      </form>
    </main>
  );
}

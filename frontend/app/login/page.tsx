"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Lock, Zap } from "lucide-react";
import { GoogleOAuthProvider, GoogleLogin, type CredentialResponse } from "@react-oauth/google";
import { authApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    authApi
      .me()
      .then((m) => setGoogleEnabled(Boolean(m.google_signin_enabled) && Boolean(GOOGLE_CLIENT_ID)))
      .catch(() => setGoogleEnabled(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      await authApi.login(password);
      router.replace("/leads");
    } catch {
      setError(t("auth.invalid"));
      setLoading(false);
    }
  }

  async function handleGoogleCredential(resp: CredentialResponse) {
    if (!resp.credential) {
      setError(t("auth.googleFailed"));
      return;
    }
    setGoogleLoading(true);
    setError(null);
    try {
      await authApi.loginGoogle(resp.credential);
      router.replace("/leads");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setError(msg.includes("not_in_allow_list") ? t("auth.googleDenied") : t("auth.googleFailed"));
      setGoogleLoading(false);
    }
  }

  const formCard = (
    <main className="min-h-screen flex items-center justify-center px-6">
      <div className="absolute top-4 right-4">
        <LanguageSwitcher />
      </div>
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-white/10 bg-white/[0.02] p-7"
      >
        <div className="flex items-center gap-2.5 mb-6">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-eko-violet to-eko-magenta flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div className="font-semibold text-white">
            Eko AI <span className="text-eko-violet">Realtors</span>
          </div>
        </div>

        <h1 className="text-lg font-semibold text-white mb-1">{t("auth.login.title")}</h1>
        <p className="text-xs text-gray-500 mb-5">{t("auth.login.subtitle")}</p>

        <label className="block">
          <span className="text-xs text-gray-400">{t("auth.password")}</span>
          <div className="relative mt-1">
            <Lock className="w-3.5 h-3.5 text-gray-600 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-sm text-white focus:outline-none focus:border-eko-violet/50"
            />
          </div>
        </label>

        {error && <p className="text-[11px] text-red-400 mt-2">{error}</p>}

        <button
          type="submit"
          disabled={loading || !password}
          className="mt-5 w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-eko-violet text-white hover:bg-eko-violet-dark disabled:opacity-50"
        >
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {loading ? t("auth.signingIn") : t("auth.signIn")}
        </button>

        {googleEnabled && (
          <>
            <div className="flex items-center gap-3 my-5">
              <div className="flex-1 h-px bg-white/10" />
              <span className="text-[10px] uppercase tracking-wider text-gray-500">{t("auth.or")}</span>
              <div className="flex-1 h-px bg-white/10" />
            </div>
            <div className="flex justify-center">
              {googleLoading ? (
                <div className="flex items-center gap-2 text-xs text-gray-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {t("auth.googleSigningIn")}
                </div>
              ) : (
                <GoogleLogin
                  onSuccess={handleGoogleCredential}
                  onError={() => setError(t("auth.googleFailed"))}
                  text="signin_with"
                  theme="filled_black"
                  shape="rectangular"
                  width="280"
                />
              )}
            </div>
          </>
        )}
      </form>
    </main>
  );

  if (GOOGLE_CLIENT_ID) {
    return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{formCard}</GoogleOAuthProvider>;
  }
  return formCard;
}

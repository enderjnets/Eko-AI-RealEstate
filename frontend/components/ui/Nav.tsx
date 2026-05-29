"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BarChart3, Home, Inbox, LogOut, Search, Settings, Zap } from "lucide-react";
import { authApi, inboxApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { VersionButton } from "@/components/ui/VersionButton";

export function Nav() {
  const { t } = useI18n();
  const router = useRouter();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [pending, setPending] = useState(0);

  useEffect(() => {
    authApi
      .me()
      .then((m) => {
        setAuthEnabled(m.auth_enabled);
        setIsAdmin(m.role === "admin");
      })
      .catch(() => {});
    inboxApi
      .count()
      .then((c) => setPending(c.pending))
      .catch(() => {});
  }, []);

  async function logout() {
    try {
      await authApi.logout();
    } finally {
      router.replace("/login");
    }
  }

  return (
    <nav className="border-b border-white/5 bg-eko-noir/80 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-eko-violet to-eko-magenta flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div className="leading-tight">
            <div className="font-semibold text-sm text-white">
              Eko AI <span className="text-eko-violet">Realtors</span>
            </div>
            <div className="text-[10px] text-gray-500 uppercase tracking-wider">
              {t("nav.subtitle")}
            </div>
          </div>
        </Link>

        <div className="flex items-center gap-1">
          <Link
            href="/discovery"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
          >
            <Search className="w-3.5 h-3.5" />
            {t("nav.discovery")}
          </Link>
          <Link
            href="/leads"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors"
          >
            {t("nav.leads")}
          </Link>
          <Link
            href="/inbox"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
          >
            <Inbox className="w-3.5 h-3.5" />
            {t("nav.inbox")}
            {pending > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                {pending}
              </span>
            )}
          </Link>
          <Link
            href="/properties"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
          >
            <Home className="w-3.5 h-3.5" />
            {t("nav.properties")}
          </Link>
          <Link
            href="/analytics"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            {t("nav.analytics")}
          </Link>
          {isAdmin && (
            <Link
              href="/settings"
              className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <Settings className="w-3.5 h-3.5" />
              {t("nav.settings")}
            </Link>
          )}
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 rounded-md text-sm text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
            title="OpenAPI docs (backend Swagger UI)"
          >
            {t("nav.api")}
          </a>
          <LanguageSwitcher />
          <VersionButton />
          {authEnabled && (
            <button
              type="button"
              onClick={logout}
              title={t("auth.logout")}
              className="px-2.5 py-1.5 rounded-md text-sm text-gray-400 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}

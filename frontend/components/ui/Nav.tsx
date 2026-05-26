"use client";

import Link from "next/link";
import { Home, Settings, Zap } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";

export function Nav() {
  const { t } = useI18n();
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
            href="/leads"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors"
          >
            {t("nav.leads")}
          </Link>
          <Link
            href="/properties"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
          >
            <Home className="w-3.5 h-3.5" />
            {t("nav.properties")}
          </Link>
          <Link
            href="/settings"
            className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
          >
            <Settings className="w-3.5 h-3.5" />
            {t("nav.settings")}
          </Link>
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
        </div>
      </div>
    </nav>
  );
}

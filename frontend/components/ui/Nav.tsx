"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  CalendarDays,
  Home,
  Inbox,
  LogOut,
  Mail,
  MessageCircle,
  MessageSquare,
  Phone,
  Search,
  Settings,
  Users,
  Zap,
} from "lucide-react";
import { authApi, inboxApi, type InboxItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { VersionButton } from "@/components/ui/VersionButton";

const MAX_MENU_ITEMS = 6;

function channelIcon(ch: string | null) {
  switch (ch) {
    case "voice":
      return Phone;
    case "email":
      return Mail;
    case "whatsapp":
      return MessageCircle;
    default:
      return MessageSquare; // sms
  }
}

export function Nav() {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [attention, setAttention] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuItems, setMenuItems] = useState<InboxItem[]>([]);
  const [menuLoading, setMenuLoading] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
      .then((c) => setAttention(c.attention))
      .catch(() => {});
  }, []);

  // Close the dropdown on outside click / ESC.
  useEffect(() => {
    if (!menuOpen) return;
    function onDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  // Close on navigation.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  function toggleMenu() {
    const next = !menuOpen;
    setMenuOpen(next);
    if (next) {
      setMenuLoading(true);
      inboxApi
        .list({ filter: "attention" })
        .then((r) => setMenuItems(r.items.slice(0, MAX_MENU_ITEMS)))
        .catch(() => setMenuItems([]))
        .finally(() => setMenuLoading(false));
    }
  }

  async function logout() {
    try {
      await authApi.logout();
    } finally {
      router.replace("/login");
    }
  }

  const isActive = (href: string) =>
    href === "/leads" ? pathname.startsWith("/leads") : pathname.startsWith(href);

  const tabs = [
    { href: "/discovery", label: t("nav.discovery"), Icon: Search },
    { href: "/leads", label: t("nav.leads"), Icon: Users },
    { href: "/inbox", label: t("nav.inbox"), Icon: Inbox, dot: attention > 0 },
    { href: "/calendar", label: t("nav.calendar"), Icon: CalendarDays },
    { href: "/properties", label: t("nav.properties"), Icon: Home },
    { href: "/analytics", label: t("nav.stats"), Icon: BarChart3 },
  ];

  return (
    <>
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

          {/* Desktop links — hidden on phones (the bottom tab bar replaces them). */}
          <div className="hidden md:flex items-center gap-1">
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

            {/* Inbox — button opens a dropdown with quick access to new/pending comms. */}
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={toggleMenu}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
              >
                <Inbox className="w-3.5 h-3.5" />
                {t("nav.inbox")}
                {attention > 0 && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    {attention}
                  </span>
                )}
              </button>

              {menuOpen && (
                <div
                  role="menu"
                  className="absolute right-0 mt-2 w-80 rounded-xl border border-white/10 bg-eko-noir/95 backdrop-blur-md shadow-2xl z-50 overflow-hidden"
                >
                  <Link
                    href="/inbox"
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center justify-between px-4 py-3 text-sm text-white hover:bg-white/5 border-b border-white/10"
                  >
                    <span className="inline-flex items-center gap-2">
                      <Inbox className="w-4 h-4 text-eko-violet" />
                      {t("nav.inboxGoTo")}
                    </span>
                    {attention > 0 && (
                      <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                        {attention}
                      </span>
                    )}
                  </Link>

                  <div className="px-4 pt-2.5 pb-1 text-[10px] uppercase tracking-wider text-gray-500">
                    {t("nav.inboxNew")}
                  </div>
                  <div className="max-h-80 overflow-y-auto pb-1">
                    {menuLoading ? (
                      <div className="px-4 py-6 text-center text-xs text-gray-500">…</div>
                    ) : menuItems.length === 0 ? (
                      <div className="px-4 py-6 text-center text-xs text-gray-500">
                        {t("nav.inboxEmpty")}
                      </div>
                    ) : (
                      menuItems.map((it) => {
                        const CIcon = channelIcon(it.last_channel);
                        return (
                          <Link
                            key={it.lead_id}
                            href={`/leads/${it.lead_id}`}
                            onClick={() => setMenuOpen(false)}
                            className="flex items-start gap-2.5 px-4 py-2.5 hover:bg-white/5 border-b border-white/5 last:border-0"
                          >
                            <CIcon className="w-3.5 h-3.5 mt-0.5 text-eko-violet shrink-0" />
                            <span className="min-w-0 flex-1">
                              <span className="flex items-center justify-between gap-2">
                                <span className="text-sm text-white truncate">
                                  {it.name || it.identifier}
                                </span>
                                {it.needs_response && (
                                  <span
                                    className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"
                                    aria-label="awaiting reply"
                                  />
                                )}
                              </span>
                              {it.last_preview && (
                                <span className="block text-xs text-gray-500 truncate">
                                  {it.last_preview}
                                </span>
                              )}
                            </span>
                          </Link>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>

            <Link
              href="/properties"
              className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <Home className="w-3.5 h-3.5" />
              {t("nav.properties")}
            </Link>
            <Link
              href="/calendar"
              className="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <CalendarDays className="w-3.5 h-3.5" />
              {t("nav.calendar")}
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
          </div>

          {/* Actions — always visible. On phones this is the whole right side. */}
          <div className="flex items-center gap-1">
            {/* Settings isn't in the bottom tab bar, so expose it here on phones. */}
            {isAdmin && (
              <Link
                href="/settings"
                title={t("nav.settings")}
                aria-label={t("nav.settings")}
                className="md:hidden inline-flex items-center justify-center min-w-[40px] h-10 rounded-md text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
              >
                <Settings className="w-4 h-4" />
              </Link>
            )}
            <LanguageSwitcher />
            <div className="hidden sm:block">
              <VersionButton />
            </div>
            {authEnabled && (
              <button
                type="button"
                onClick={logout}
                title={t("auth.logout")}
                aria-label={t("auth.logout")}
                className="inline-flex items-center justify-center min-w-[40px] h-10 sm:h-auto sm:min-w-0 sm:px-2.5 sm:py-1.5 rounded-md text-sm text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* Bottom tab bar — native-app navigation on phones only. */}
      <nav
        aria-label="Primary"
        className="eko-tabbar md:hidden fixed inset-x-0 bottom-0 z-50 flex border-t border-white/10 bg-eko-noir/90 backdrop-blur-lg pb-[env(safe-area-inset-bottom,0px)]"
      >
        {tabs.map(({ href, label, Icon, dot }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`relative flex-1 flex flex-col items-center justify-center gap-1 min-h-[56px] py-2 text-[10px] font-medium transition-colors ${
                active ? "text-eko-violet" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              <Icon className="w-[21px] h-[21px]" />
              <span>{label}</span>
              {dot && (
                <span className="absolute top-[7px] left-[calc(50%+8px)] w-2 h-2 rounded-full bg-amber-400 border-[1.5px] border-eko-noir" />
              )}
            </Link>
          );
        })}
      </nav>
    </>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  CalendarClock,
  CalendarDays,
  Clapperboard,
  Eye,
  FileCode,
  Home,
  Inbox,
  LogOut,
  Mail,
  MessageCircle,
  MessageSquare,
  Phone,
  PhoneCall,
  Search,
  Settings,
  Users,
  Zap,
} from "lucide-react";
import { authApi, inboxApi, type InboxItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { usePlatformOperator } from "@/lib/useViewer";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { OverflowMenu } from "@/components/ui/OverflowMenu";
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
  const isOperator = usePlatformOperator();
  const router = useRouter();
  const pathname = usePathname();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [isViewer, setIsViewer] = useState(false);
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
        setIsViewer(Boolean(m.auth_enabled) && m.role === "viewer");
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

  // Five links plus a "More" tab, instead of seven crammed labels. The bar now
  // covers phones AND tablets (`lg:hidden`), so it has to hold up from 320px to
  // 1023px on one set of classes.
  const tabs = [
    // Operator-only; see app/discovery/page.tsx.
    ...(isOperator ? [{ href: "/discovery", label: t("nav.discovery"), Icon: Search }] : []),
    { href: "/leads", label: t("nav.leads"), Icon: Users },
    // On the phone by necessity, not for symmetry: the clip is filmed and
    // uploaded here, and the desktop row does not exist below `lg`.
    { href: "/content", label: t("nav.tab.content"), Icon: Clapperboard },
    { href: "/inbox", label: t("nav.inbox"), Icon: Inbox, dot: attention > 0 },
    { href: "/calendar", label: t("nav.tab.calendar"), Icon: CalendarDays },
  ];

  // What "More" holds. `/console` is the reason this exists: the call console
  // was in NO phone navigation at all — not in the tab array, and the desktop
  // row is hidden — so the one screen a realtor needs while standing in a
  // driveway was unreachable from the only device she has with her.
  const overflowTabs = [
    { href: "/console", label: t("console.title"), Icon: PhoneCall },
    { href: "/properties", label: t("nav.properties"), Icon: Home },
    { href: "/analytics", label: t("nav.analytics"), Icon: BarChart3 },
    // On the phone by necessity, like the clip upload above: an agent adjusts
    // her hours between showings, from the car, not at a desk.
    { href: "/availability", label: t("nav.availability"), Icon: CalendarClock },
  ];

  return (
    <>
      <nav className="border-b border-white/5 bg-eko-noir/80 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
          {/* /leads, not /. Since v0.44.0 the root is the public marketing
              page, so the dashboard logo pointed staff out of the dashboard. */}
          <Link href="/leads" className="flex items-center gap-2.5 shrink-0">
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

          {/* Desktop links — hidden on phones (the bottom tab bar replaces them).
              No `overflow` here, and that is load-bearing: the Inbox dropdown
              below is absolutely positioned INSIDE this container, and CSS
              computes `overflow-y: visible` to `auto` as soon as `overflow-x`
              is not visible. Scrolling the row sideways therefore clipped the
              402px dropdown to zero visible pixels on every page — measured,
              not theorised. Still true, and still the reason this row is not a
              scroller.

              The row now starts at `lg` (1024), not `md` (768): the items never
              fitted in a 768px tablet, which is what the old note called
              backlog. Between `lg` and `xl` the tail of the row moves into an
              overflow menu instead of being clipped; at `xl` and up the layout
              is exactly what it always was. If you change this breakpoint,
              change `globals.css` too — it hard-codes the matching width for
              the padding that keeps the tab bar off the content. */}
          <div className="hidden lg:flex items-center gap-1">
            {/* `isOperator`, at last. The whole `/discovery` API sits behind
                `require_platform_admin`, and the bottom tab bar has always
                gated it — only this link did not, so an ordinary member saw it,
                clicked it and was handed a 403. Two navs, one route, one rule. */}
            {isOperator && (
              <Link
                href="/discovery"
                className="hidden 2xl:inline-flex px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors items-center gap-1.5"
              >
                <Search className="w-3.5 h-3.5" />
                {t("nav.discovery")}
              </Link>
            )}
            <Link
              href="/leads"
              className="px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors"
            >
              {t("nav.leads")}
            </Link>
            <Link
              href="/console"
              className="px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <PhoneCall className="w-3.5 h-3.5" />
              {t("console.title")}
            </Link>
            <Link
              href="/content"
              className="px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <Clapperboard className="w-3.5 h-3.5" />
              {t("nav.content")}
            </Link>

            {/* Inbox — button opens a dropdown with quick access to new/pending comms. */}
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={toggleMenu}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                className="px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
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
              className="hidden 2xl:inline-flex px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors items-center gap-1.5"
            >
              <Home className="w-3.5 h-3.5" />
              {t("nav.properties")}
            </Link>
            <Link
              href="/calendar"
              className="px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors inline-flex items-center gap-1.5"
            >
              <CalendarDays className="w-3.5 h-3.5" />
              {t("nav.calendar")}
            </Link>
            <Link
              href="/analytics"
              className="hidden 2xl:inline-flex px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors items-center gap-1.5"
            >
              <BarChart3 className="w-3.5 h-3.5" />
              {t("nav.analytics")}
            </Link>
            {isAdmin && (
              <Link
                href="/settings"
                className="hidden 2xl:inline-flex px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-white/5 transition-colors items-center gap-1.5"
              >
                <Settings className="w-3.5 h-3.5" />
                {t("nav.settings")}
              </Link>
            )}
            {/* Wide screens only: it points at the backend's Swagger UI, which
                is a developer's link, and it was the item being clipped once
                Contenido joined a bar that was already too full. */}
            <a
              href="/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden 2xl:inline-block px-2 xl:px-3 py-1.5 rounded-md text-sm text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
              title="OpenAPI docs (backend Swagger UI)"
            >
              {t("nav.api")}
            </a>

            {/* 1024–1279: the five links above that are `hidden xl:inline-flex`
                live here instead. The trigger disappears at `xl`, where they
                are all back in the row and this would be a second way to reach
                the same pages.

                Role gates repeated, not delegated: an item that is hidden from
                the row for a reason must be hidden here for the same reason, or
                the menu becomes the back door to it. */}
            <OverflowMenu
              label={t("nav.more")}
              className="2xl:hidden"
              items={[
                ...(isOperator
                  ? [{ href: "/discovery", label: t("nav.discovery"), Icon: Search }]
                  : []),
                { href: "/properties", label: t("nav.properties"), Icon: Home },
                { href: "/analytics", label: t("nav.analytics"), Icon: BarChart3 },
                // Every member, not just admins: this is a person's own working
                // hours, and gating it on `isAdmin` would mean the agent whose
                // time it is could not set it.
                { href: "/availability", label: t("nav.availability"), Icon: CalendarClock },
                ...(isAdmin
                  ? [{ href: "/settings", label: t("nav.settings"), Icon: Settings }]
                  : []),
                { href: "/docs", label: t("nav.api"), Icon: FileCode, external: true },
              ]}
            />
          </div>

          {/* Actions — always visible. On phones this is the whole right side. */}
          <div className="flex items-center gap-1 shrink-0">
            {/* Settings isn't in the bottom tab bar, so expose it here on phones. */}
            {isAdmin && (
              <Link
                href="/settings"
                title={t("nav.settings")}
                aria-label={t("nav.settings")}
                className="lg:hidden inline-flex items-center justify-center min-w-[40px] h-10 rounded-md text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
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

      {isViewer && (
        <div className="bg-amber-500/10 border-b border-amber-500/20 text-amber-300 text-[11px] px-4 py-1.5 flex items-center justify-center gap-1.5">
          <Eye className="w-3.5 h-3.5 shrink-0" />
          <span>{t("auth.viewOnlyBanner")}</span>
        </div>
      )}

      {/* Bottom tab bar — native-app navigation on phones only. */}
      <nav
        aria-label="Primary"
        className="eko-tabbar lg:hidden fixed inset-x-0 bottom-0 z-50 flex border-t border-white/10 bg-eko-noir/90 backdrop-blur-lg pb-[env(safe-area-inset-bottom,0px)]"
      >
        {tabs.map(({ href, label, Icon, dot }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`relative flex-1 min-w-0 flex flex-col items-center justify-center gap-1 min-h-[56px] py-2 text-[10px] font-medium transition-colors ${
                active ? "text-eko-violet" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              <Icon className="w-[21px] h-[21px] shrink-0" />
              <span className="max-w-full truncate px-0.5">{label}</span>
              {dot && (
                <span className="absolute top-[7px] left-[calc(50%+8px)] w-2 h-2 rounded-full bg-amber-400 border-[1.5px] border-eko-noir" />
              )}
            </Link>
          );
        })}
        {/* `direction="up"`: this bar is pinned to the bottom of the viewport,
            so a panel that opens downward opens off-screen entirely. */}
        <OverflowMenu
          label={t("nav.more")}
          variant="tab"
          direction="up"
          items={overflowTabs}
        />
      </nav>
    </>
  );
}

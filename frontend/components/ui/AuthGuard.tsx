"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { isPublicPath } from "@/lib/hosts";

/**
 * Routes this guard must never gate — DERIVED from the brand site's own list,
 * not a second copy of it.
 *
 * It used to be a hand-written Set, and that is exactly how `/fall` shipped
 * broken: the page was added to `lib/hosts.ts` so the middleware would serve it
 * on the brand domain, the routing test went green, and this file — the OTHER
 * allow-list, the one nothing tested — still bounced every visitor to /login.
 * Worse than the bounce: that page declares `robots: index`, so what Google
 * would have crawled and indexed is the "Checking session…" spinner.
 *
 * Deriving instead of copying makes the dangerous direction impossible. A new
 * public page is added in ONE place and is ungated here for free; forgetting is
 * no longer a thing that can happen.
 *
 * `/login` and `/register` are added on top rather than folded into the shared
 * list, and the asymmetry is deliberate: they must not require a session, and
 * they must ALSO not be served on the brand domain — that list publishes what
 * it contains. Two different questions with a shared core, not one question.
 *
 * `isPublicPath` and not `Set.has`: it matches sub-paths, so `/contact/thanks`
 * is ungated for the same reason `/contact` is. The old Set gated it.
 */
function isUngated(pathname: string): boolean {
  return isPublicPath(pathname) || pathname === "/login" || pathname === "/register";
}

/**
 * The same predicate, exported for the test that keeps this file from drifting
 * away from `lib/hosts.ts` again. Named `…ForTest` so nothing in the app is
 * tempted to import the guard's internals to decide something else.
 */
export const isUngatedForTest = isUngated;

/**
 * Gates the dashboard when AUTH_ENABLED. Calls /auth/me once per navigation; if
 * auth is on and the session is missing, redirects to /login. When auth is off
 * (dev / public demo) it's transparent. Ungated routes are never checked.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useI18n();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isUngated(pathname)) {
      setReady(true);
      return;
    }
    let mounted = true;
    setReady(false);
    authApi
      .me()
      .then((me) => {
        if (!mounted) return;
        if (me.auth_enabled && !me.authenticated) router.replace("/login");
        else setReady(true);
      })
      .catch(() => mounted && setReady(true)); // never hard-lock on a transient error
    return () => {
      mounted = false;
    };
  }, [pathname, router]);

  if (isUngated(pathname)) return <>{children}</>;
  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500 text-sm gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("auth.checking")}
      </div>
    );
  }
  return <>{children}</>;
}

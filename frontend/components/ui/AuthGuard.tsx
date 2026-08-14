"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// Public routes that must NEVER be gated (else an unauthenticated visitor is
// bounced straight back to /login). /register is public so prospective clients
// can self-register a read-only demo account. /contact is the landing-page
// capture form — the whole point is that a stranger who followed a link from a
// video reaches it, and bouncing them to a login screen would make the form
// worse than not having one.
// "/" is the public marketing landing — the whole point is that a stranger can
// read it. Staff reach the dashboard at /login, which still lands on /leads.
const PUBLIC_PATHS = new Set(["/", "/login", "/register", "/contact"]);

/**
 * Gates the dashboard when AUTH_ENABLED. Calls /auth/me once per navigation; if
 * auth is on and the session is missing, redirects to /login. When auth is off
 * (dev / public demo) it's transparent. PUBLIC_PATHS are never gated.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useI18n();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (PUBLIC_PATHS.has(pathname)) {
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

  if (PUBLIC_PATHS.has(pathname)) return <>{children}</>;
  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500 text-sm gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("auth.checking")}
      </div>
    );
  }
  return <>{children}</>;
}

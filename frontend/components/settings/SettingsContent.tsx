"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { SettingsForm } from "@/components/settings/SettingsForm";
import { TeamPanel } from "@/components/settings/TeamPanel";
import { RegistrationsPanel } from "@/components/settings/RegistrationsPanel";

/**
 * Settings is admin-only. The Nav hides the link for members, but a member could
 * still navigate to /settings directly — so guard client-side: non-admins are
 * sent to /leads. When auth is disabled (dev/demo without login) everyone is
 * admin, so it's transparent. The data APIs (settings + team) also enforce this
 * server-side with require_admin.
 */
export function SettingsContent() {
  const router = useRouter();
  const { t } = useI18n();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let mounted = true;
    authApi
      .me()
      .then((m) => {
        if (!mounted) return;
        if (m.auth_enabled && m.role !== "admin") router.replace("/leads");
        else setReady(true);
      })
      .catch(() => mounted && setReady(true)); // never hard-lock on a transient error
    return () => {
      mounted = false;
    };
  }, [router]);

  if (!ready) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm">
        <Loader2 className="w-4 h-4 animate-spin" /> {t("auth.checking")}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <TeamPanel />
      <RegistrationsPanel />
      <SettingsForm />
    </div>
  );
}

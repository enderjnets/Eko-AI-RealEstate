"use client";

import { useI18n } from "@/lib/i18n";

export function PageHeader({ titleKey, subtitleKey }: { titleKey: string; subtitleKey: string }) {
  const { t } = useI18n();
  return (
    <header className="mb-6">
      <h1 className="text-2xl font-bold text-white mb-1">{t(titleKey)}</h1>
      <p className="text-sm text-gray-500">{t(subtitleKey)}</p>
    </header>
  );
}

"use client";

import { Nav } from "@/components/ui/Nav";
import { useI18n } from "@/lib/i18n";
import { usePlatformOperator } from "@/lib/useViewer";
import { PageHeader } from "@/components/ui/PageHeader";
import { DiscoveryPanel } from "@/components/discovery/DiscoveryPanel";
import { FileImport } from "@/components/discovery/FileImport";

export default function DiscoveryPage() {
  const isOperator = usePlatformOperator();
  const { t } = useI18n();
  return (
    <>
      <Nav />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="discovery.title" subtitleKey="discovery.subtitle" />
        {/* Discovery spends providers billed to the operator and shared by every
            agency, so the backend gates it. Rendering the panels for a tenant
            only earned them a 403 on the first click. */}
        {isOperator ? (
          <>
            <DiscoveryPanel />
            <FileImport />
          </>
        ) : (
          <p className="text-sm text-gray-400">{t("discovery.operatorOnly")}</p>
        )}
      </main>
    </>
  );
}

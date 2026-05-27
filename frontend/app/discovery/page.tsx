import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { DiscoveryPanel } from "@/components/discovery/DiscoveryPanel";
import { FileImport } from "@/components/discovery/FileImport";

export const dynamic = "force-dynamic";

export default function DiscoveryPage() {
  return (
    <>
      <Nav />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="discovery.title" subtitleKey="discovery.subtitle" />
        <DiscoveryPanel />
        <FileImport />
      </main>
    </>
  );
}

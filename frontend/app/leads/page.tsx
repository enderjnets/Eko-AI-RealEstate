import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { HotLeadsPanel } from "@/components/leads/HotLeadsPanel";
import { LeadsExplorer } from "@/components/leads/LeadsExplorer";

export const dynamic = "force-dynamic";

export default function LeadsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="leads.title" subtitleKey="leads.subtitle" />

        <HotLeadsPanel />

        <LeadsExplorer />
      </main>
    </>
  );
}

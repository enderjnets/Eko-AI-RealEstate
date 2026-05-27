import { Suspense } from "react";
import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { AddLeadButton } from "@/components/leads/AddLeadButton";
import { FilterBar } from "@/components/leads/FilterBar";
import { HotLeadsPanel } from "@/components/leads/HotLeadsPanel";
import { LeadsTable } from "@/components/leads/LeadsTable";

export const dynamic = "force-dynamic";

export default function LeadsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="leads.title" subtitleKey="leads.subtitle" />

        <HotLeadsPanel />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Suspense fallback={null}>
            <FilterBar />
          </Suspense>
          <AddLeadButton />
        </div>

        <Suspense fallback={null}>
          <LeadsTable />
        </Suspense>
      </main>
    </>
  );
}

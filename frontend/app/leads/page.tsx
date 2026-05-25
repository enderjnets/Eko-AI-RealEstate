import { Suspense } from "react";
import { Nav } from "@/components/ui/Nav";
import { FilterBar } from "@/components/leads/FilterBar";
import { LeadsTable } from "@/components/leads/LeadsTable";

export const dynamic = "force-dynamic";

export default function LeadsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-white mb-1">Leads</h1>
          <p className="text-sm text-gray-500">
            Conversaciones de WhatsApp con clasificación automática. Click en una para ver el
            historial y tomar control manual si hace falta.
          </p>
        </header>

        <Suspense fallback={null}>
          <FilterBar />
        </Suspense>

        <Suspense fallback={<div className="text-gray-500 text-sm">Cargando…</div>}>
          <LeadsTable />
        </Suspense>
      </main>
    </>
  );
}

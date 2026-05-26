import { Nav } from "@/components/ui/Nav";
import { PropertiesGrid } from "@/components/properties/PropertiesGrid";

export const dynamic = "force-dynamic";

export default function PropertiesPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-white mb-1">Propiedades</h1>
          <p className="text-sm text-gray-500">
            Listings importados del feed MLS/IDX (RESO). El agente los empareja con los
            leads según zona, presupuesto e intención.
          </p>
        </header>
        <PropertiesGrid />
      </main>
    </>
  );
}

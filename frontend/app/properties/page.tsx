import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { PropertiesGrid } from "@/components/properties/PropertiesGrid";

export const dynamic = "force-dynamic";

export default function PropertiesPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="properties.title" subtitleKey="properties.subtitle" />
        <PropertiesGrid />
      </main>
    </>
  );
}

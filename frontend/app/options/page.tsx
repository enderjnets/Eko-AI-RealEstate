import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { RequestsList } from "@/components/options/RequestsList";

export const dynamic = "force-dynamic";

export default function OptionsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="options.title" subtitleKey="options.subtitle" />
        <RequestsList />
      </main>
    </>
  );
}

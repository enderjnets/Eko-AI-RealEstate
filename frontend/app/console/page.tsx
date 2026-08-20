import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { ConsoleView } from "@/components/console/ConsoleView";
import { ContentQueue } from "@/components/console/ContentQueue";

export const dynamic = "force-dynamic";

export default function ConsolePage() {
  return (
    <>
      <Nav />
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="console.title" subtitleKey="console.subtitle" />
        <ConsoleView />
        <ContentQueue />
      </main>
    </>
  );
}

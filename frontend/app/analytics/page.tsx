import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { AnalyticsView } from "@/components/analytics/AnalyticsView";

export const dynamic = "force-dynamic";

export default function AnalyticsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="analytics.title" subtitleKey="analytics.subtitle" />
        <AnalyticsView />
      </main>
    </>
  );
}

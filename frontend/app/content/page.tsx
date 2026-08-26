import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { ContentQueue } from "@/components/content/ContentQueue";

export const dynamic = "force-dynamic";

export default function ContentPage() {
  return (
    <>
      <Nav />
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="content.title" subtitleKey="content.subtitle" />
        <ContentQueue />
      </main>
    </>
  );
}

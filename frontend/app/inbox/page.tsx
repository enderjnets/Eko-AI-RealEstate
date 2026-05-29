import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { InboxList } from "@/components/inbox/InboxList";

export const dynamic = "force-dynamic";

export default function InboxPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="inbox.title" subtitleKey="inbox.subtitle" />
        <InboxList />
      </main>
    </>
  );
}

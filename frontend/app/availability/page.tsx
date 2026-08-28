import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { MyAvailability } from "@/components/availability/MyAvailability";

export const dynamic = "force-dynamic";

export default function AvailabilityPage() {
  return (
    <>
      <Nav />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="availability.title" subtitleKey="availability.subtitle" />
        <MyAvailability />
      </main>
    </>
  );
}

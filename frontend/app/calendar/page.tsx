import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { CalendarView } from "@/components/calendar/CalendarView";

export const dynamic = "force-dynamic";

export default function CalendarPage() {
  return (
    <>
      <Nav />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="calendar.title" subtitleKey="calendar.subtitle" />
        <CalendarView />
      </main>
    </>
  );
}

import { Nav } from "@/components/ui/Nav";
import { PageHeader } from "@/components/ui/PageHeader";
import { SettingsContent } from "@/components/settings/SettingsContent";

export const dynamic = "force-dynamic";

export default function SettingsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PageHeader titleKey="settings.title" subtitleKey="settings.subtitle" />
        <SettingsContent />
      </main>
    </>
  );
}

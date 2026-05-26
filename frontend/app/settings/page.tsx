import { Nav } from "@/components/ui/Nav";
import { SettingsForm } from "@/components/settings/SettingsForm";

export const dynamic = "force-dynamic";

export default function SettingsPage() {
  return (
    <>
      <Nav />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-white mb-1">Configuración</h1>
          <p className="text-sm text-gray-500">
            Personalizá cómo se presenta tu agente IA: nombre de la agencia, personalidad,
            saludo, idiomas y horario. Los cambios aplican de inmediato a las respuestas.
          </p>
        </header>
        <SettingsForm />
      </main>
    </>
  );
}

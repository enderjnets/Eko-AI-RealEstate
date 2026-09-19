import { Nav } from "@/components/ui/Nav";
import { OptionsPicker } from "@/components/options/OptionsPicker";

export const dynamic = "force-dynamic";

export default function OptionsRequestPage({ params }: { params: { id: string } }) {
  return (
    <>
      <Nav />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <OptionsPicker id={Number(params.id)} />
      </main>
    </>
  );
}

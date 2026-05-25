import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Nav } from "@/components/ui/Nav";
import { LeadDetail } from "@/components/leads/LeadDetail";

export const dynamic = "force-dynamic";

export default function LeadDetailPage({ params }: { params: { id: string } }) {
  const leadId = parseInt(params.id, 10);
  if (Number.isNaN(leadId)) {
    return (
      <>
        <Nav />
        <main className="max-w-3xl mx-auto px-4 py-12 text-center">
          <p className="text-gray-400">ID de lead inválido.</p>
          <Link href="/leads" className="text-eko-violet text-sm mt-2 inline-block">
            ← Volver a leads
          </Link>
        </main>
      </>
    );
  }
  return (
    <>
      <Nav />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Link
          href="/leads"
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-white mb-4"
        >
          <ArrowLeft className="w-3 h-3" />
          Volver a leads
        </Link>
        <LeadDetail leadId={leadId} />
      </main>
    </>
  );
}

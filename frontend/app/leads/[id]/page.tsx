"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Nav } from "@/components/ui/Nav";
import { LeadDetail } from "@/components/leads/LeadDetail";
import { useI18n } from "@/lib/i18n";

export default function LeadDetailPage({ params }: { params: { id: string } }) {
  const { t } = useI18n();
  const leadId = parseInt(params.id, 10);

  const backLink = (
    <Link
      href="/leads"
      className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-white mb-4"
    >
      <ArrowLeft className="w-3 h-3" />
      {t("common.back_to_leads")}
    </Link>
  );

  if (Number.isNaN(leadId)) {
    return (
      <>
        <Nav />
        <main className="max-w-3xl mx-auto px-4 py-12 text-center">
          <p className="text-gray-400">{t("common.invalid_lead")}</p>
          <Link href="/leads" className="text-eko-violet text-sm mt-2 inline-block">
            ← {t("common.back_to_leads")}
          </Link>
        </main>
      </>
    );
  }
  return (
    <>
      <Nav />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {backLink}
        <LeadDetail leadId={leadId} />
      </main>
    </>
  );
}

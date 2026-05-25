import Link from "next/link";
import { Building2, Shield, MessageCircle, CalendarCheck } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-6 py-16">
      <div className="max-w-3xl text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-eko-violet/10 border border-eko-violet/30 text-eko-violet text-xs font-medium mb-6">
          <Shield className="w-3.5 h-3.5" />
          100% on-prem · zero cloud data
        </div>

        <h1 className="text-5xl sm:text-6xl font-bold mb-4 leading-[1.1]">
          Eko AI <span className="text-eko-violet">Inmobiliario</span>
        </h1>

        <p className="text-lg text-gray-400 mb-10 max-w-xl mx-auto">
          The AI agent that handles your WhatsApp 24/7, captures every lead, schedules visits, and follows up — all from your own office hardware. No cloud, no leaks.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-12">
          <Feature icon={MessageCircle} title="WhatsApp 24/7" body="Auto-responds to inbound messages with a local LLM. Never misses a lead." />
          <Feature icon={CalendarCheck} title="Visit booking" body="Cal.com / Google Calendar slots offered in chat. Bookings sync back." />
          <Feature icon={Building2} title="Listings ingest" body="Idealista & Fotocasa scraped daily. Nothing leaves your office." />
        </div>

        <p className="text-sm text-gray-500">
          MVP in active development.{" "}
          <Link href="https://github.com/enderjnets/Eko-AI-RealEstate" className="text-eko-violet hover:underline">
            See the roadmap →
          </Link>
        </p>
      </div>
    </main>
  );
}

function Feature({ icon: Icon, title, body }: { icon: typeof Building2; title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 text-left">
      <Icon className="w-5 h-5 text-eko-violet mb-2" />
      <h3 className="font-semibold text-white mb-1">{title}</h3>
      <p className="text-xs text-gray-500 leading-relaxed">{body}</p>
    </div>
  );
}

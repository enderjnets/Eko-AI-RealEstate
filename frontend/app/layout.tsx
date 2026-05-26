import type { Metadata } from "next";
import "./globals.css";
import { LanguageProvider } from "@/lib/i18n";
import { AuthGuard } from "@/components/ui/AuthGuard";

export const metadata: Metadata = {
  title: "Eko AI Realtors — Dashboard",
  description: "The AI agent for real-estate offices. Multichannel 24/7 (WhatsApp + Email + SMS) + lead capture + visit booking + listings matching.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-display">
        <LanguageProvider>
          <AuthGuard>{children}</AuthGuard>
        </LanguageProvider>
      </body>
    </html>
  );
}

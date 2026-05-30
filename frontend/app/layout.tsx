import type { Metadata, Viewport } from "next";
import "./globals.css";
import { LanguageProvider } from "@/lib/i18n";
import { AuthGuard } from "@/components/ui/AuthGuard";

export const metadata: Metadata = {
  title: "Eko AI Realtors — Dashboard",
  description: "The AI agent for real-estate offices. Multichannel 24/7 (WhatsApp + Email + SMS) + lead capture + visit booking + listings matching.",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Eko AI Realtors",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0B0B0F",
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

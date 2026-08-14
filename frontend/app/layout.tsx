import type { Metadata, Viewport } from "next";
import { Instrument_Sans, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { LanguageProvider } from "@/lib/i18n";
import { AuthGuard } from "@/components/ui/AuthGuard";

// Self-hosted at build time by next/font — no runtime request to Google, which
// keeps the public landing free of third-party calls. Only the CSS variables
// are declared app-wide; nothing here changes the dashboard's typeface.
const lnSans = Instrument_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-ln-sans",
});

const lnSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  display: "swap",
  variable: "--font-ln-serif",
});

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
      <body className={`font-display ${lnSans.variable} ${lnSerif.variable}`}>
        <LanguageProvider>
          <AuthGuard>{children}</AuthGuard>
        </LanguageProvider>
      </body>
    </html>
  );
}

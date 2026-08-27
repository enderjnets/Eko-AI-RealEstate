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
  /**
   * Default for the whole app: do not index. The public pages that SHOULD be
   * indexed override this in their own `metadata` (`app/page.tsx`,
   * `app/contact/page.tsx`), which is the safe direction — a panel screen added
   * next month is out of the index until someone deliberately puts it in,
   * rather than in it until someone remembers to take it out.
   *
   * This is not belt-and-braces with `middleware.ts`, it covers a different
   * failure: the middleware only redirects once the hostnames are configured,
   * and today they are not, so `inmo-demo.ekoaiautomation.com/leads` is a
   * crawlable login screen. Measured on production, not assumed.
   *
   * And it is deliberately NOT a robots.txt: Cloudflare prepends its own
   * `Allow: /` and Google honours the least restrictive rule — that has
   * already happened on this infrastructure.
   */
  robots: { index: false, follow: false },
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

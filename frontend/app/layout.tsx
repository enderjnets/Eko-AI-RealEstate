import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Eko AI Realtors — Dashboard",
  description: "The on-prem AI agent for real-estate offices. WhatsApp 24/7 + lead capture + visit booking. Runs 100% on your hardware.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="font-display">{children}</body>
    </html>
  );
}

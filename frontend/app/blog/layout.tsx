import type { ReactNode } from "react";
import { requireJournalAccess } from "@/lib/journal/requireAccess";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function JournalLayout({ children }: { children: ReactNode }) {
  requireJournalAccess();
  return <>
    <aside className="bg-jr-noir px-5 py-3 text-center font-ln-sans text-xs text-jr-cream" role="note">
      Private preview — pending image permissions. Not for distribution.
    </aside>
    {children}
  </>;
}

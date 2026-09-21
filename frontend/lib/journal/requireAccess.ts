import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { journalAuthorized } from "./access";

// The page itself enforces access even if middleware is skipped by an internal request.
export function requireJournalAccess(): void {
  if (!journalAuthorized(headers().get("authorization"))) notFound();
}

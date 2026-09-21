import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { journalAuthorized, journalChallenge, JOURNAL_PRIVATE_HEADERS } from "@/lib/journal/access";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, { params }: { params: { asset: string[] } }) {
  if (!journalAuthorized(request.headers.get("authorization"))) return journalChallenge();
  const relative = params.asset.join("/");
  if (!/^(?:img\/[a-z]+-[0-3]\.jpg|denver-skyline\.jpg|ev-logo-(?:light|cream)\.png)$/.test(relative)) {
    return new Response("Not found", { status: 404, headers: JOURNAL_PRIVATE_HEADERS });
  }
  try {
    const bytes = await readFile(join(process.cwd(), "private", "journal", relative));
    return new Response(bytes, { headers: {
      ...JOURNAL_PRIVATE_HEADERS,
      "Content-Type": relative.endsWith(".jpg") ? "image/jpeg" : "image/png",
      "X-Content-Type-Options": "nosniff",
    } });
  } catch {
    return new Response("Not found", { status: 404, headers: JOURNAL_PRIVATE_HEADERS });
  }
}

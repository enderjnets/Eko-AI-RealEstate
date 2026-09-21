export const JOURNAL_PRIVATE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "CDN-Cache-Control": "no-store",
  "Cloudflare-CDN-Cache-Control": "no-store",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
  "Vary": "Authorization",
};

export function journalAuthorized(authorization: string | null): boolean {
  const password = process.env.JOURNAL_PREVIEW_PASSWORD;
  if (!password || password.length < 20 || !authorization) return false;
  const match = /^Basic ([A-Za-z0-9+/]+={0,2})$/i.exec(authorization);
  if (!match) return false;
  try {
    const supplied = atob(match[1]);
    const expected = `journal:${password}`;
    let difference = supplied.length ^ expected.length;
    for (let i = 0; i < expected.length; i++) {
      difference |= (supplied.charCodeAt(i) || 0) ^ expected.charCodeAt(i);
    }
    return difference === 0;
  } catch {
    return false;
  }
}

export function journalChallenge(): Response {
  return new Response("Private Journal preview. Please sign in with the review credentials.", {
    status: 401,
    headers: {
      ...JOURNAL_PRIVATE_HEADERS,
      "Content-Type": "text/plain; charset=utf-8",
      "WWW-Authenticate": 'Basic realm="DHS Journal Preview", charset="UTF-8"',
    },
  });
}

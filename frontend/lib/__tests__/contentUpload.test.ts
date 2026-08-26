import { afterEach, describe, expect, it, vi } from "vitest";
import { contentApi } from "../api";

/**
 * The upload is a raw body on a query-string URL, and every part of that is
 * load-bearing in a way a type signature cannot hold:
 *
 * - The route reads `request.stream()`. Sending a FormData instead — the shape
 *   the other upload in this app uses — would arrive as multipart bytes and be
 *   written to disk as the clip, producing a corrupt file and a 201.
 * - The filename carries the suffix the server validates against, and clips
 *   from a phone are called things like "IMG_0421 (1).mov". Unencoded, the
 *   space and parenthesis break the query string.
 * - Progress comes from `xhr.upload.onprogress`, which is the only reason this
 *   is XHR at all. If a refactor swaps it for fetch the callback silently never
 *   fires and a 300 MB upload looks frozen.
 *
 * No jsdom in this repo, so XMLHttpRequest is stubbed and inspected — the same
 * source-of-truth approach as landingConfigWiring.test.ts.
 */

type Sent = { method: string; url: string; body: unknown; timeout: number };
type Ending = {
  fireError?: boolean;
  fireTimeout?: boolean;
  progress?: { lengthComputable: boolean; loaded: number; total: number }[];
};

/**
 * `statusText` is "" on purpose: that is what HTTP/2 gives, and pretending
 * otherwise is what hid an unreadable error message from the first version of
 * these tests.
 */
function stubXhr(status: number, responseText: string, ending: Ending = {}) {
  const sent: Sent[] = [];
  const progressHandlers: ((e: unknown) => void)[] = [];

  class FakeXhr {
    status = status;
    statusText = "";
    responseText = responseText;
    timeout = 0;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    upload = {
      set onprogress(fn: (e: unknown) => void) {
        progressHandlers.push(fn);
      },
    };
    private method = "";
    private url = "";
    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    send(body: unknown) {
      sent.push({ method: this.method, url: this.url, body, timeout: this.timeout });
      const events = ending.progress ?? [{ lengthComputable: true, loaded: 5, total: 10 }];
      events.forEach((e) => progressHandlers.forEach((fn) => fn(e)));
      if (ending.fireTimeout) return void this.ontimeout?.();
      if (ending.fireError) return void this.onerror?.();
      this.onload?.();
    }
  }

  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  return sent;
}

afterEach(() => vi.unstubAllGlobals());

const clip = () =>
  ({ name: "IMG_0421 (1).mov", size: 12, type: "video/quicktime" }) as File;

describe("contentApi.upload", () => {
  it("sends the file as the raw body, not as form data", async () => {
    const file = clip();
    const sent = stubXhr(201, JSON.stringify({ id: 7, status: "draft" }));

    await contentApi.upload(file, "en");

    expect(sent).toHaveLength(1);
    expect(sent[0].method).toBe("POST");
    expect(sent[0].body).toBe(file);
    expect(sent[0].body).not.toBeInstanceOf(FormData);
  });

  it("percent-encodes the filename so a phone's name survives the query string", async () => {
    const sent = stubXhr(201, JSON.stringify({ id: 7 }));

    await contentApi.upload(clip(), "es");

    const url = sent[0].url;
    expect(url).toContain("/api/v1/content/upload?");
    expect(url).toContain("filename=IMG_0421%20(1).mov");
    expect(url).toContain("language=es");
    // The unencoded space would end the URL at the parser.
    expect(url).not.toContain("IMG_0421 (1)");
  });

  it("reports progress, which is the only reason this is not fetch", async () => {
    stubXhr(201, JSON.stringify({ id: 7 }));
    const seen: number[] = [];

    await contentApi.upload(clip(), "en", (p) => seen.push(p));

    expect(seen).toEqual([50]);
  });

  it("keeps the server's own reason, because 415 and 413 have different fixes", async () => {
    stubXhr(415, JSON.stringify({ detail: "Expected a video file (.m4v, .mov, .mp4, .webm)" }));

    await expect(contentApi.upload(clip(), "en")).rejects.toThrow(
      /Expected a video file/,
    );
  });

  it("keeps the raw body when the rejection is not JSON, because statusText is empty on HTTP/2", async () => {
    // The likeliest rejection of all — a proxy refusing the size — arrives as
    // an HTML page with no `detail`. The first version of this fell back to
    // `xhr.statusText`, which HTTP/2 defines as the empty string, so the user
    // read "API 413:" and nothing after it. Asserted with the whole message,
    // not a /413/ match, which is what let that through.
    stubXhr(413, "<html>Request Entity Too Large</html>");

    await expect(contentApi.upload(clip(), "en")).rejects.toThrow(
      "API 413: <html>Request Entity Too Large</html>",
    );
  });

  it("renders a FastAPI validation array instead of an empty sentence", async () => {
    stubXhr(
      422,
      JSON.stringify({
        detail: [{ loc: ["query", "filename"], msg: "String should have at least 1 character" }],
      }),
    );

    await expect(contentApi.upload(clip(), "en")).rejects.toThrow(
      /filename: String should have at least 1 character/,
    );
  });

  it("gives up instead of hanging forever on a half-open connection", async () => {
    // No timeout meant the promise never settled, the caller's `finally` never
    // ran, and the progress bar stuck at whatever percent it reached with the
    // button disabled and no way out but reloading the page.
    const sent = stubXhr(0, "", { fireTimeout: true });

    await expect(contentApi.upload(clip(), "en")).rejects.toThrow("upload:timeout");
    expect(sent[0].timeout).toBeGreaterThan(0);
  });

  it("says a dropped connection in a key the UI can translate", async () => {
    stubXhr(0, "", { fireError: true });

    await expect(contentApi.upload(clip(), "en")).rejects.toThrow("upload:network");
  });

  it("never reports more than 100 percent, or NaN for an empty file", async () => {
    stubXhr(201, JSON.stringify({ id: 7 }), {
      progress: [
        { lengthComputable: true, loaded: 0, total: 0 },
        { lengthComputable: true, loaded: 12, total: 10 },
      ],
    });
    const seen: number[] = [];

    await contentApi.upload(clip(), "en", (p) => seen.push(p));

    expect(seen.every((p) => Number.isFinite(p) && p <= 100)).toBe(true);
  });
});

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
    // A proxy rejecting a request arrives as an HTML page with no `detail`.
    // The first version of this fell back to `xhr.statusText`, which HTTP/2
    // defines as the empty string, so the user read "API 502:" and nothing
    // after it. Asserted with the whole message, not a /502/ match, which is
    // what let that through.
    //
    // Uses 502, not 413: a 413 now has a dedicated path that turns it into the
    // translated "that clip is too large" sentence rather than showing the
    // page's markup to a realtor. That path is covered below; this one guards
    // every OTHER status, where the raw body is still the best we have.
    stubXhr(502, "<html>Bad Gateway</html>");

    await expect(contentApi.upload(clip(), "en")).rejects.toThrow(
      "API 502: <html>Bad Gateway</html>",
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

describe("contentApi.upload size guard", () => {
  const bigClip = (mb: number) =>
    ({
      name: "4K walkthrough.mov",
      size: Math.round(mb * 1024 * 1024),
      type: "video/quicktime",
    }) as File;

  it("refuses an oversized clip WITHOUT opening a request", async () => {
    // The assertion that matters is `sent` being empty, not that it rejects.
    // Rejecting after the bytes are on the wire would still pass a "throws"
    // test while costing the person minutes of mobile data and their
    // allowance — and the error they would get back is a proxy's HTML page,
    // not a sentence. Saving the upload IS the feature; the message is second.
    const sent = stubXhr(201, JSON.stringify({ id: 7 }));

    await expect(
      contentApi.upload(bigClip(200), "en", undefined, 95),
    ).rejects.toThrow(/^upload:tooLarge:/);

    expect(sent).toHaveLength(0);
  });

  it("carries both numbers, because one of them is useless alone", async () => {
    stubXhr(201, JSON.stringify({ id: 7 }));

    await expect(
      contentApi.upload(bigClip(143.7), "en", undefined, 95),
    ).rejects.toThrow("upload:tooLarge:143.7:95");
  });

  it("lets a clip at the limit through", async () => {
    const sent = stubXhr(201, JSON.stringify({ id: 7, status: "draft" }));

    // Exactly at the cap is allowed: the server's own test is `> limit`, and a
    // client that refused what the server accepts would be a second, stricter
    // limit nobody wrote down.
    await contentApi.upload(bigClip(95), "en", undefined, 95);

    expect(sent).toHaveLength(1);
  });

  it("uploads anyway when the limit could not be learned", async () => {
    const sent = stubXhr(201, JSON.stringify({ id: 7, status: "draft" }));

    // `contentApi.status()` swallows its own failure by design, so the caller
    // may have no number. Refusing to send because an unrelated GET failed
    // would break uploading every time the network hiccuped. The server is the
    // gate and always was; this check only saves the trip when it can.
    await contentApi.upload(bigClip(500), "en", undefined, undefined);

    expect(sent).toHaveLength(1);
  });
});

describe("contentApi.upload server-side 413", () => {
  const clipOf = (mb: number) =>
    ({ name: "walkthrough.mov", size: Math.round(mb * 1024 * 1024), type: "video/quicktime" }) as File;

  it("turns the server's 413 into the same failure the pre-flight check raises", async () => {
    // The pre-flight guard cannot run when the limit was never learned, and a
    // clip can also clear the tunnel but not our own middleware. Both arrive
    // here. Before this, the user saw the raw token `API 413: body_too_large`
    // — English, internal, in a bilingual product — while a sentence written
    // for this exact event went unused.
    stubXhr(413, JSON.stringify({ detail: "body_too_large", limit_mb: 95 }));

    await expect(
      contentApi.upload(clipOf(120), "es", undefined, undefined),
    ).rejects.toThrow("upload:tooLarge:120.0:95");
  });

  it("still says something when the 413 is a proxy's HTML page", async () => {
    // No JSON to read the limit from and no limit passed in: the message drops
    // to the variant that does not claim a number, rather than rendering
    // "the limit is  MB".
    stubXhr(413, "<html><body>413 Request Entity Too Large</body></html>");

    await expect(
      contentApi.upload(clipOf(120), "en", undefined, undefined),
    ).rejects.toThrow("upload:tooLarge:120.0:");
  });

  it("rounds the size up so the message cannot contradict itself", async () => {
    // One byte over a 95 MB cap. `toFixed(1)` rounded to nearest and produced
    // "95.0", so the refusal read "That clip is 95 MB and the limit is 95 MB"
    // and asked the person to trim a file that already looked small enough.
    const oneByteOver = { name: "x.mov", size: 95 * 1024 * 1024 + 1 } as File;
    stubXhr(201, JSON.stringify({ id: 1 }));

    await expect(
      contentApi.upload(oneByteOver, "en", undefined, 95),
    ).rejects.toThrow("upload:tooLarge:95.1:95");
  });
});

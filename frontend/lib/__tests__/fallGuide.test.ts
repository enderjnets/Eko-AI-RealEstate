import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { BANDS_FOR_TEST } from "../fallGuide";

/**
 * The fall guide's three silent failures.
 *
 * None of them throws, logs, or turns a page red. Each one produces a page that
 * still renders and is still wrong:
 *
 * 1. **A photo whose file is not there.** `<img>` shows a broken icon and Next
 *    says nothing; the build succeeds, the deploy succeeds, and the defect is
 *    visible only to visitors. This is the same shape as the `/fall` bug that
 *    shipped a spinner to Google — everything green, nothing working.
 * 2. **A credit missing a field.** CC BY and CC BY-SA both require the author
 *    and the licence, and this page is advertising for a licensed brokerage.
 *    A dropped name is a licence breach that looks exactly like a design
 *    choice, so no human review catches it.
 * 3. **A ladder rung pointing at a band that no longer exists.** The ladder's
 *    hrefs and the sections' ids are one mechanism written twice. Rename a band
 *    and the link simply stops scrolling — no console error, no 404.
 *
 * Deliberately asserting on the DATA rather than on rendered markup: the page
 * is a server component with client children, and the repo has decided against
 * jsdom more than once. Everything above is decidable from the table.
 */

const PUBLIC_DIR = resolve(__dirname, "../../public");
const PAGE = resolve(__dirname, "../../app/fall/page.tsx");
const DATA = resolve(__dirname, "../fallGuide.ts");

const SPOTS = BANDS_FOR_TEST.flatMap((band) => band.spots);
const PHOTOS = SPOTS.flatMap((spot) => (spot.photo ? [spot.photo] : []));

describe("the fall guide's photographs", () => {
  it("has at least one, or the whole exercise did nothing", () => {
    expect(PHOTOS.length).toBeGreaterThan(0);
  });

  it("every photo file is actually on disk", () => {
    for (const photo of PHOTOS) {
      // Not a URL: these are served from `public/`, and a leading slash is the
      // only form Next resolves there.
      expect(photo.src.startsWith("/")).toBe(true);
      expect(
        existsSync(resolve(PUBLIC_DIR, photo.src.slice(1))),
        `missing file for ${photo.src}`,
      ).toBe(true);
    }
  });

  it("every photo carries the credit its licence requires", () => {
    for (const photo of PHOTOS) {
      expect(photo.author.trim(), `no author for ${photo.src}`).not.toBe("");
      expect(photo.license.trim(), `no licence for ${photo.src}`).not.toBe("");
      // The deed and the original file page: attribution that a reader can
      // follow, which is what "reasonable manner for the medium" means here.
      expect(photo.licenseUrl).toMatch(/^https:\/\/creativecommons\.org\//);
      expect(photo.sourceUrl).toMatch(/^https:\/\/commons\.wikimedia\.org\//);
    }
  });

  it("frames with a CSS value, never a Tailwind class this file is invisible to", () => {
    // The bug this exists for shipped and was caught by eye, not by a test:
    // `position` held `[object-position:50%_58%]`, a Tailwind arbitrary class.
    // `tailwind.config.ts` scans `app/` and `components/` — not `lib/` — so
    // when this table moved out of the page the class stopped being generated.
    // No error, no warning; the photo just re-centred and the comment above it
    // became false. A raw CSS value applied inline cannot be dropped by a
    // scanner that never looks here.
    for (const photo of PHOTOS) {
      if (photo.position === undefined) continue;
      expect(photo.position, `${photo.src} frames with a class, not a value`).not.toMatch(
        /[[\]]/,
      );
      expect(photo.position).toMatch(/^[-\w %.]+$/);
    }
  });

  it("every photo describes what is in it, for a reader who cannot see it", () => {
    for (const photo of PHOTOS) {
      expect(photo.alt.trim().length, `thin alt text for ${photo.src}`).toBeGreaterThan(20);
    }
  });

  it("the licence file names every photo we ship", () => {
    // The file beside the images is where provenance lives. A photo added
    // without an entry there is a photo nobody can trace back.
    const licence = readFileSync(resolve(PUBLIC_DIR, "landing/fall/LICENCIA.txt"), "utf8");
    for (const photo of PHOTOS) {
      const file = photo.src.split("/").pop() as string;
      expect(licence, `${file} is not in LICENCIA.txt`).toContain(file);
    }
  });
});

describe("the elevation ladder and the bands it points at", () => {
  it("every band has an id, and the ids are unique", () => {
    const ids = BANDS_FOR_TEST.map((band) => band.id);
    for (const id of ids) expect(id).toMatch(/^band-\d+$/);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("the rungs take their href from the band table, not from hand-typed ids", () => {
    const source = readFileSync(PAGE, "utf8");
    // This first line is what keeps the second from being a test that cannot
    // fail. Today the ladder builds every href from the table, so there are no
    // literal `#…` hrefs at all and the loop below has nothing to check —
    // green, and blind. Pinning the expression means the day somebody replaces
    // it with hand-typed anchors, THIS goes red and the loop starts working.
    expect(source).toContain("href={`#${band.id}`}");

    const literals = [...source.matchAll(/href="#([a-z0-9-]+)"/g)].map((m) => m[1]);
    const ids = new Set(BANDS_FOR_TEST.map((band) => band.id));
    for (const href of literals) {
      expect(ids.has(href), `#${href} is not a band on this page`).toBe(true);
    }
  });

  it("the bands run downhill, because that is the whole idea", () => {
    // Aspens turn from the top down. A band list that starts in Denver is not
    // a reordering, it is the opposite claim.
    const first = BANDS_FOR_TEST[0].elevation;
    const last = BANDS_FOR_TEST[BANDS_FOR_TEST.length - 1].elevation;
    expect(first).toMatch(/9,500/);
    expect(last).toMatch(/5,280/);
  });
});

describe("the guide still says who is advertising", () => {
  it("names no brokerage of its own — the regulated lines come from config", () => {
    // Colorado requires advertising to identify the brokerage, and
    // `lib/landing.ts` is the only place allowed to know which one it is. A
    // literal here would survive an install that has not configured one.
    // Both files: the markup AND the table it renders. Splitting the content
    // out of the page is exactly the move that would let a literal land in the
    // half nobody is checking.
    for (const file of [PAGE, DATA]) {
      expect(readFileSync(file, "utf8")).not.toMatch(/Engel/i);
    }
    expect(readFileSync(PAGE, "utf8")).toContain("LANDING.brokerage");
  });
});

/**
 * The tab icon: three files in `public/` and the tags that point at them.
 *
 * Until 0.143.4 neither domain had one — `/favicon.ico` answered 404 and the
 * page carried no `<link rel="icon">`. The mark is Denver Home Story's own
 * logo (mountains and sun), redrawn as vector: cropped tighter for the tab so
 * the sun survives 16 px, and whole for the iPhone home screen.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND = join(__dirname, "..", "..");
const PUBLIC = join(FRONTEND, "public");
const layout = readFileSync(join(FRONTEND, "app", "layout.tsx"), "utf8");

/** Width and height of every image in an .ico (0 in the directory means 256). */
function icoSizes(buf: Buffer): number[][] {
  expect(buf.readUInt16LE(0)).toBe(0);
  expect(buf.readUInt16LE(2)).toBe(1);
  const count = buf.readUInt16LE(4);
  return Array.from({ length: count }, (_, i) => {
    const entry = 6 + i * 16;
    return [buf[entry] || 256, buf[entry + 1] || 256];
  });
}

describe("favicon", () => {
  it("ships an .ico with the three sizes a browser picks from", () => {
    const sizes = icoSizes(readFileSync(join(PUBLIC, "favicon.ico")));
    expect(sizes).toEqual(expect.arrayContaining([[16, 16], [32, 32], [48, 48]]));
    expect(sizes).toHaveLength(3);
  });

  it("ships a vector icon that draws with no font", () => {
    const svg = readFileSync(join(PUBLIC, "icon.svg"), "utf8");
    expect(svg).toMatch(/^<svg [^>]*viewBox="0 0 32 32"/);
    // A tab renders the file in isolation: text would fall back to whatever
    // font the browser has, and a script or link would not run at all.
    expect(svg).not.toMatch(/<(text|script|image|style)\b|href=/);
  });

  it("ships a 180 px opaque square for the iPhone home screen", () => {
    const png = readFileSync(join(PUBLIC, "apple-touch-icon.png"));
    expect(png.subarray(1, 4).toString("ascii")).toBe("PNG");
    expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([180, 180]);
    // Colour type 2 = RGB with no alpha: iOS paints transparency black.
    expect(png[25]).toBe(2);
  });

  it("is declared in the root layout, so both hostnames get the tags", () => {
    const icons = layout.slice(layout.indexOf("icons:"), layout.indexOf("robots:"));
    expect(icons).toContain('"/favicon.ico"');
    expect(icons).toContain('"/icon.svg"');
    expect(icons).toContain('"/apple-touch-icon.png"');
  });
});

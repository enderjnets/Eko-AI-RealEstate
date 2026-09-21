import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
const root = ".next/static";
const forbidden = ["1221 Richmond Hill Road", "highest price per square foot of anything", "Photographs courtesy of Whitman", "richmond-0.jpg"];
async function check(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) await check(path);
    else if (entry.name.endsWith(".js")) {
      const text = await readFile(path, "utf8");
      if (forbidden.some(value => text.includes(value))) throw new Error(`Private Journal data in public bundle: ${path}`);
    }
  }
}
await check(root);
console.log("Private Journal data absent from public JavaScript bundles.");

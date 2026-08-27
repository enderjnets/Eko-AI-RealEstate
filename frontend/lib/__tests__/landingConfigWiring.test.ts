import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A NEXT_PUBLIC_* variable has to be declared in four places to survive the
 * trip from an operator's .env to the rendered page: documented in
 * .env.example, forwarded by docker-compose as a build arg, and declared in
 * the Dockerfile as both ARG and ENV. Miss any one of them and Next inlines an
 * empty string at build time — the page shows blanks while the .env file looks
 * perfectly filled in, and nothing anywhere reports an error.
 *
 * This install has already paid for that lesson once, with eighteen settings
 * that compose never passed. This test is the fix that does not wear off.
 */

const REPO = join(__dirname, "..", "..", "..");
const read = (p: string) => readFileSync(join(REPO, p), "utf8");

const envExample = read(".env.example");
const dockerfile = read("frontend/Dockerfile");
const compose = read("docker-compose.yml");

/**
 * Swept by SHAPE, not from a list of files.
 *
 * This used to read three named files — `lib/landing.ts`, `ConsultForm.tsx`
 * and `Turnstile.tsx`. That is a list somebody has to remember to extend, and
 * the first time it mattered it did not get extended: `lib/hosts.ts` arrived
 * with two new NEXT_PUBLIC_ variables and this guard stayed green while
 * neither was declared anywhere in the build. The whole point of the test is
 * to catch a variable that never reaches the container, and it was blind to
 * any variable outside three paths.
 *
 * So it now walks the frontend source and finds every `process.env.NEXT_PUBLIC_*`
 * there is. A new file is covered the moment it is written, by nobody.
 */
const SRC_DIRS = ["frontend/app", "frontend/components", "frontend/lib"];
const SRC_EXT = /\.(ts|tsx)$/;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(join(REPO, dir), { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    // Tests name variables in assertions without using them at runtime; sweeping
    // them would demand build wiring for a string that only ever appears here.
    if (entry.isDirectory()) {
      if (entry.name !== "__tests__" && entry.name !== "node_modules") out.push(...walk(rel));
    } else if (SRC_EXT.test(entry.name)) {
      out.push(rel);
    }
  }
  return out;
}

const used = [
  ...new Set(
    walk(SRC_DIRS[0])
      .concat(walk(SRC_DIRS[1]), walk(SRC_DIRS[2]))
      .flatMap((f) => read(f).match(/process\.env\.NEXT_PUBLIC_[A-Z_]+/g) ?? [])
      .map((m) => m.replace("process.env.", "")),
  ),
].sort();

describe("landing config wiring", () => {
  it("reads at least one landing variable — otherwise this test proves nothing", () => {
    expect(used.length).toBeGreaterThan(0);
  });

  it.each(used)("%s is documented in .env.example", (name) => {
    expect(envExample).toMatch(new RegExp(`^${name}=`, "m"));
  });

  it.each(used)("%s is declared ARG in the frontend Dockerfile", (name) => {
    expect(dockerfile).toMatch(new RegExp(`^ARG ${name}$`, "m"));
  });

  it.each(used)("%s is exported ENV in the frontend Dockerfile", (name) => {
    // ARG alone is not enough: without the matching ENV the value exists in
    // the build stage but never reaches `next build`.
    expect(dockerfile).toMatch(new RegExp(`^ENV ${name}=\\$${name}$`, "m"));
  });

  it.each(used)("%s is passed by docker-compose as a build arg", (name) => {
    expect(compose).toMatch(new RegExp(`^\\s+${name}: \\$\\{${name}:-\\}$`, "m"));
  });

  it("documents no landing variable the code does not actually read", () => {
    const documented = [
      ...new Set(envExample.match(/^NEXT_PUBLIC_LANDING_[A-Z_]+(?==)/gm) ?? []),
    ];
    expect(documented.filter((n) => !used.includes(n))).toEqual([]);
  });

  it("covers the two shared keys the consult form depends on", () => {
    // Guard on the guard: if the globs above ever stop reaching ConsultForm or
    // Turnstile, every assertion still passes over a shrunken list and the
    // test goes quietly useless.
    expect(used).toContain("NEXT_PUBLIC_CAPTURE_FORM_KEY");
    expect(used).toContain("NEXT_PUBLIC_TURNSTILE_SITE_KEY");
  });
});

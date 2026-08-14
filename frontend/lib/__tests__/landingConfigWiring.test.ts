import { readFileSync } from "node:fs";
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

const source = read("frontend/lib/landing.ts");
const envExample = read(".env.example");
const dockerfile = read("frontend/Dockerfile");
const compose = read("docker-compose.yml");

const used = [
  ...new Set(source.match(/process\.env\.NEXT_PUBLIC_LANDING_[A-Z_]+/g) ?? []),
].map((m) => m.replace("process.env.", ""));

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

  it("documents nothing the code does not actually read", () => {
    const documented = [
      ...new Set(envExample.match(/^NEXT_PUBLIC_LANDING_[A-Z_]+(?==)/gm) ?? []),
    ];
    expect(documented.filter((n) => !used.includes(n))).toEqual([]);
  });
});

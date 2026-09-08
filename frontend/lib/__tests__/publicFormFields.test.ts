import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * The two public forms ask for a last name, both halves are required, and
 * neither can send more than the server's single `name` field accepts.
 *
 * Asserted by reading the source, not by rendering: vitest here has no DOM by
 * choice (`vitest.config.ts` — "deliberately NOT adding jsdom or
 * @testing-library"), which is the same reason `track.test.ts` and
 * `landingConfigWiring.test.ts` read files as text. Comments are stripped
 * first, exactly as `track.test.ts` does: without that, a sentence in a
 * docblock mentioning `required` would satisfy assertions the markup does not.
 *
 * Two files and not one, because they are two separate forms that must not
 * drift: `ConsultForm` serves `/`, `/fall` and `/calculator`; `/contact` has
 * its own. A change made to one and forgotten in the other is the failure this
 * catches.
 */
const read = (p: string) =>
  readFileSync(join(process.cwd(), p), "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

const FORMS = [
  {
    file: "components/landing/ConsultForm.tsx",
    firstId: "ln-name",
    lastId: "ln-lastname",
    firstState: "f.name",
    lastState: "f.lastName",
  },
  {
    file: "app/contact/page.tsx",
    firstId: "name",
    lastId: "lastName",
    firstState: "f.name",
    lastState: "f.lastName",
  },
] as const;

describe("the public forms ask for a full name", () => {
  it("reads both files — otherwise every assertion below proves nothing", () => {
    for (const { file } of FORMS) expect(read(file).length).toBeGreaterThan(1000);
  });

  for (const { file, firstId, lastId, firstState, lastState } of FORMS) {
    /**
     * One field element, found by its `id` and not by "a field whose text
     * happens to contain this string". The first draft filtered with
     * `f.includes(firstId)`, and with `firstId = "name"` on /contact that
     * matched by luck: `autoComplete="given-name"` contains `name`. It would
     * have started failing for a reason unrelated to the thing under test.
     */
    const field = (src: string, id: string) => {
      const all = src.match(/<(?:Landing)?Field\b[\s\S]*?\/>/g) ?? [];
      const found = all.filter((f) => new RegExp(`id="${id}"`).test(f));
      expect(found).toHaveLength(1);
      return found[0];
    };

    it(`${file} has a last-name field next to the first`, () => {
      const src = read(file);
      // Asserted PER FIELD, not per file. Checking only that both tokens
      // appear somewhere passes with the two swapped — and swapped is a real
      // failure: the phone puts the surname in the first box and the given
      // name in the second, and nothing on screen says so.
      expect(field(src, firstId)).toContain('autoComplete="given-name"');
      expect(field(src, lastId)).toContain('autoComplete="family-name"');
    });

    it(`${file} marks both halves required and caps their length`, () => {
      const src = read(file);
      // "Added the field, forgot the attribute" is the failure that looks like
      // nothing until a lead arrives with half a name.
      for (const id of [firstId, lastId]) {
        const f = field(src, id);
        expect(f).toMatch(/\brequired\b/);
        expect(f).toContain("maxLength={NAME_FIELD_MAX}");
      }
    });

    it(`${file} keeps iOS from rewriting the name it was given`, () => {
      const src = read(file);
      // `type="text"` is the only input type iOS autocorrects; a surname it
      // does not recognise gets replaced silently, and the agent calls someone
      // whose name does not match their ID. The flag is per field, so it is
      // asserted per field.
      for (const id of [firstId, lastId]) {
        expect(field(src, id)).toMatch(/\b(name|isName)\b/);
      }
    });

    it(`${file} wires each box to its OWN piece of state`, () => {
      // The bug every assertion above misses: point the last-name input at
      // `f.name` and it mirrors the first box, the surname is never captured,
      // and `id`, `required`, `maxLength` and `autoComplete` are all still
      // exactly right. Measured — the suite stayed green with it.
      const first = field(read(file), firstId);
      const last = field(read(file), lastId);
      expect(first).toContain(`value={${firstState}}`);
      expect(last).toContain(`value={${lastState}}`);
      expect(first).toContain(`onChange={set("${firstState.slice(2)}")}`);
      expect(last).toContain(`onChange={set("${lastState.slice(2)}")}`);
    });

    it(`${file} joins the two halves through lib/leadName, with both of them`, () => {
      const src = read(file);
      expect(src).toMatch(/from "@\/lib\/leadName"/);
      // Both arguments named, not just the call. `fullName(f.name, f.name)`
      // passes a looser check and drops the surname on the floor.
      expect(src).toContain(`name: fullName(${firstState}, ${lastState})`);
      // The shape it replaced. If it comes back, only one half of the name
      // ever reaches the agent.
      expect(src).not.toMatch(/name: f\.name\.trim\(\)/);
    });
  }
});

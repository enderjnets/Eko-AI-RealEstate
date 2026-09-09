import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Every field the Settings form lets you EDIT must also be a field it SAVES.
 *
 * `booking_contact_email` had an input from the day it was added and was never
 * in the PUT payload. The failure is silent in the worst way: `handleSave`
 * finishes, "Saved ✓" appears, and then `setData(updated)` overwrites local
 * state with the server's — so the address the user typed disappears from the
 * box while the page says it saved. Nothing errors, nothing logs. It shipped
 * for months, and without that address Cal.com cannot book a lead who only
 * gave a phone number, which is most of them.
 *
 * A test for that one field would have been a test for yesterday's bug. This
 * asserts the shape instead: the set of keys passed to `set(...)` and the set
 * of keys in the `settingsApi.update({...})` payload must be equal. Add a
 * field and forget to save it — or save a field nobody can edit — and this
 * turns red naming the field.
 *
 * Regex over the source rather than a rendered component on purpose: this repo
 * has no jsdom or @testing-library, and the guard is about wiring, which is a
 * property of the file. Same approach as landingConfigWiring.test.ts.
 */

const REPO = join(__dirname, "..", "..");
const source = readFileSync(
  join(REPO, "components", "settings", "SettingsForm.tsx"),
  "utf8",
);

/** Fields the form mutates: every `set("<field>", …)` call site. */
function editableFields(): Set<string> {
  const matches = [...source.matchAll(/\bset\(\s*"([a-z_]+)"/g)];
  return new Set(matches.map((m) => m[1]));
}

/** Fields the form persists: the object literal inside `settingsApi.update`. */
function savedFields(): Set<string> {
  // Anchored to handleSave: the first `settingsApi.update` in this file is the
  // one-off timezone auto-detect, which saves a single field by design.
  const saveFn = source.indexOf("async function handleSave");
  expect(saveFn, "handleSave not found — this test is anchored to it").toBeGreaterThan(-1);
  const start = source.indexOf("settingsApi.update({", saveFn);
  expect(start, "settingsApi.update({ … }) not found in handleSave").toBeGreaterThan(-1);
  const end = source.indexOf("});", start);
  expect(end, "unterminated settingsApi.update call").toBeGreaterThan(start);
  const body = source.slice(start, end);
  return new Set([...body.matchAll(/^\s{8}([a-z_]+):/gm)].map((m) => m[1]));
}

describe("the video languages are their own list", () => {
  it("offers only the languages the writer has a prompt for", () => {
    // The chat list can offer four because the model answers in whatever it
    // is asked. A video language without a prompt is a draft that never
    // comes, and the API refuses it — so the form must not offer one.
    const start = source.indexOf("const CONTENT_LANGS");
    expect(start, "CONTENT_LANGS not found").toBeGreaterThan(-1);
    const body = source.slice(start, source.indexOf("];", start));
    const codes = [...body.matchAll(/code: "([a-z]+)"/g)].map((m) => m[1]).sort();
    expect(codes).toEqual(["en", "es"]);
  });

  it("toggles content_languages, never the chat list", () => {
    // Wired to the wrong field, the section would look right and silently
    // change which languages the chat agent answers in.
    const fn = source.indexOf("function toggleContentLang");
    expect(fn, "toggleContentLang not found").toBeGreaterThan(-1);
    const body = source.slice(fn, source.indexOf("\n  }\n", fn));
    expect(body).toContain('set("content_languages"');
    expect(body).not.toContain("data.languages");
    expect(source).toContain("CONTENT_LANGS.map(");
  });
});

describe("the Settings form saves everything it lets you edit", () => {
  it("reads a plausible number of fields — otherwise this test proves nothing", () => {
    // Guards against a regex that silently stops matching after a refactor:
    // two empty sets are "equal" and would pass while checking nothing.
    expect(editableFields().size).toBeGreaterThan(5);
    expect(savedFields().size).toBeGreaterThan(5);
  });

  it("has no editable field that is silently discarded on save", () => {
    const edited = editableFields();
    const saved = savedFields();
    const notSaved = [...edited].filter((f) => !saved.has(f)).sort();
    const notEditable = [...saved].filter((f) => !edited.has(f)).sort();
    expect({ editedButNeverSaved: notSaved, savedButNeverEdited: notEditable }).toEqual({
      editedButNeverSaved: [],
      savedButNeverEdited: [],
    });
  });
});

import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

/**
 * The one thing vitest needs from tsconfig: the `@/` alias.
 *
 * Every frontend test until now was pure or read source files as strings with
 * `readFileSync`, so nothing ever imported app code and the alias never came
 * up. `middleware.ts` is the first module under test that imports `@/lib/hosts`,
 * and without this vitest fails to resolve it — which reads like a missing file
 * rather than a missing alias.
 *
 * Deliberately NOT adding jsdom or @testing-library along with it. Those turn
 * "run the tests" into a different kind of suite and the repo has decided
 * against them more than once; resolving an import path does not.
 */
export default defineConfig({
  resolve: {
    alias: { "@": resolve(__dirname, ".") },
  },
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { CURRENT_VERSION, CHANGELOG } from "@/lib/version";

/**
 * El numero de version es UNO, y esta guarda vive tambien aqui.
 *
 * Ya existe `backend/tests/test_version_is_one_number.py` y hace exactamente
 * esta comprobacion. No es una duplicacion por descuido: es que **estuvo en
 * rojo nueve commits seguidos sin que nadie lo notara**, del 20-sep-2026, y el
 * motivo es estructural.
 *
 * Una entrega de solo frontend se verifica corriendo la suite del frontend.
 * Yo la corri cinco veces esa noche, verde las cinco, mientras `APP_VERSION`
 * se quedaba en 0.140.0 y `CURRENT_VERSION` subia a 0.141.0, 0.142.0, .1, .2
 * y .4. La guarda estaba en el lado que nadie ejecuta cuando no toca ese lado.
 *
 * Lo que cuesta: `/api/v1/health` es contra lo que se verifica un despliegue, y
 * pasa a decir un numero que no es el desplegado. Esa noche me hizo concluir
 * que health «es del backend y no sirve para un despliegue de frontend» —
 * media verdad que tapaba esto.
 *
 * Se lee del fichero, no se importa: `config.py` es Python.
 */

const ROOT = resolve(__dirname, "..", "..", "..");

describe("la version es un solo numero", () => {
  it("el backend y el panel dicen lo mismo", () => {
    const cfg = readFileSync(resolve(ROOT, "backend/app/config.py"), "utf8");
    const m = cfg.match(/APP_VERSION[^=]*=\s*"([^"]+)"/);
    expect(m, "no encuentro APP_VERSION en backend/app/config.py").not.toBeNull();
    expect(
      m![1],
      "APP_VERSION y CURRENT_VERSION no coinciden: /api/v1/health informaria " +
        "un numero distinto del que ensena el panel",
    ).toBe(CURRENT_VERSION);
  });

  it("la version actual tiene entrada en CHANGELOG.md", () => {
    const md = readFileSync(resolve(ROOT, "CHANGELOG.md"), "utf8");
    const headings = [...md.matchAll(/^## \[([^\]]+)\]/gm)].map((x) => x[1]);
    expect(headings, `${CURRENT_VERSION} no tiene entrada`).toContain(CURRENT_VERSION);
  });

  it("y tambien en el historial que lee el panel", () => {
    // `version.ts` lleva su propio CHANGELOG para el modal de versiones. Si se
    // bumpea la constante y se olvida la entrada, el panel ensena una version
    // que su propio historial no conoce.
    expect(CHANGELOG.map((e) => e.version)).toContain(CURRENT_VERSION);
  });
});

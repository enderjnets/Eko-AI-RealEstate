import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { AS_OF, ENTRIES, INDEX, PAGE, PASSED, SLUG, STRIP } from "@/lib/journal/twelveHouses";
import { ENTRY_HREF, INDEXED, LINKED } from "@/lib/journal/publication";

/**
 * The Journal: los datos, los derechos y la puerta de publicacion.
 *
 * Con la forma de `fallGuide.test.ts`, y por los mismos motivos, mas uno que
 * solo tiene esta pieza. Los tres fallos silenciosos que vigila:
 *
 * **1. Un dato que enganaria.** Las cifras describen la casa de otro. La ficha
 * 05 es 644 pies cuadrados sobre 744 acres, lo que da $40.373 por pie: el
 * numero es correcto y la afirmacion es falsa. El diseno lo omite a proposito y
 * aqui se comprueba que sigue omitido, porque «se cayo un campo» y «se quito
 * aposta» se parecen mucho en un diff.
 *
 * **2. Un literal de correduria.** `lib/landing.ts` es la unica pieza
 * autorizada a saber cual es la nuestra. Un literal sobrevive a una instalacion
 * que no ha configurado ninguna, y entonces la pagina afirma algo que nadie ha
 * comprobado. Se comprueban las dos paginas Y el modulo de datos: partir el
 * contenido fuera de la pagina es justo el movimiento que deja un literal en la
 * mitad que nadie mira.
 *
 * **3. Cuarenta y ocho fotos ajenas en un repositorio publico.** No estan, y
 * este fichero es lo que lo mantiene asi: `git ls-files` tiene que devolver
 * cero. Una regla de `.gitignore` se borra sin querer; un test en rojo no.
 */

const ROOT = resolve(__dirname, "../..");
const read = (p: string) => readFileSync(resolve(ROOT, p), "utf8");

const INDEX_PAGE = "app/blog/page.tsx";
const ARTICLE_PAGE = "app/blog/twelve-houses-worth-the-detour/page.tsx";
const DATA = "lib/journal/twelveHouses.ts";
const RIGHTS = "lib/journal/DERECHOS.md";

describe("las doce fichas", () => {
  it("son doce, numeradas del 1 al 12 sin huecos", () => {
    expect(ENTRIES).toHaveLength(12);
    expect(ENTRIES.map((e) => e.n)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(new Set(ENTRIES.map((e) => e.slug)).size).toBe(12);
  });

  it("la tira tiene un panel por ficha y apunta a su ancla", () => {
    expect(STRIP).toHaveLength(12);
    expect(STRIP.map((p) => p.n)).toEqual(ENTRIES.map((e) => e.n));
    for (const panel of STRIP) {
      expect(panel.name.length, `panel ${panel.n} sin nombre`).toBeGreaterThan(2);
      expect(panel.where, `panel ${panel.n} sin ciudad y precio`).toMatch(/\S+\s+·\s+\$/);
    }
  });

  it("cada ficha trae cuatro fotografias, y sus nombres son los de su slug", () => {
    for (const e of ENTRIES) {
      expect(e.photos, `ficha ${e.n}`).toHaveLength(4);
      e.photos.forEach((photo, i) => {
        expect(photo, `ficha ${e.n}, foto ${i}`).toBe(`${e.slug}-${i}.jpg`);
      });
    }
  });

  it("cada fotografia lleva un alt que describe algo", () => {
    // 20 caracteres es el mismo suelo que usa `fallGuide.test.ts`: por debajo
    // de eso lo que hay es una etiqueta, no una descripcion.
    for (const e of ENTRIES) {
      expect(e.alts, `ficha ${e.n}`).toHaveLength(4);
      for (const alt of e.alts) {
        expect(alt.length, `alt corto en la ficha ${e.n}: ${alt}`).toBeGreaterThan(20);
      }
    }
  });

  it("cada ficha tiene titular, direccion, cuerpo y nota", () => {
    for (const e of ENTRIES) {
      expect(e.headline.length, `ficha ${e.n}`).toBeGreaterThan(20);
      expect(e.address.length, `ficha ${e.n}`).toBeGreaterThan(10);
      expect(e.body.length, `ficha ${e.n}`).toBeGreaterThan(80);
      expect(e.note.map((s) => s.t).join("").length, `ficha ${e.n}`).toBeGreaterThan(30);
      expect(e.noteLabel, `ficha ${e.n}`).toBe("Worth knowing");
    }
  });

  it("once fichas traen los ocho datos; la 05 trae seis, y no por accidente", () => {
    for (const e of ENTRIES) {
      if (e.n === 5) continue;
      expect(e.facts.length, `ficha ${e.n}`).toBe(8);
    }

    const five = ENTRIES[4];
    const labels = five.facts.map((f) => f.label);
    expect(five.facts).toHaveLength(6);
    // Las dos que faltan son exactamente estas. 644 pies cuadrados sobre 744
    // acres dan un precio por pie que describe una cabana, no la propiedad.
    expect(labels).not.toContain("Living area");
    expect(labels).not.toContain("Per sq ft");
    // Y la nota tiene que seguir diciendo por que, o la omision parece un fallo.
    expect(five.note.map((s) => s.t).join("")).toMatch(/price per square foot/i);
  });

  it("ningun dato sale con el hueco del origen escrito dentro", () => {
    // `listings.json` trae `style: "MISSING"` en la ficha 05. Si alguna vez se
    // usa ese campo, esto lo caza antes de que se imprima tal cual.
    const all = JSON.stringify(ENTRIES);
    expect(all).not.toMatch(/MISSING/);
    expect(all).not.toMatch(/undefined|\bnull\b|NaN/);
  });

  it("hay seis descartadas, cada una con su motivo", () => {
    expect(PASSED).toHaveLength(6);
    for (const row of PASSED) {
      expect(row.price).toMatch(/^\$[\d,]+$/);
      expect(row.city.length).toBeGreaterThan(2);
      expect(row.street.length).toBeGreaterThan(5);
      expect(row.reason.map((s) => s.t).join("").length).toBeGreaterThan(40);
    }
  });

  it("las cuatro cifras de la barra son numeros, y la ultima es doce", () => {
    expect(PAGE.stats).toHaveLength(4);
    for (const s of PAGE.stats) expect(Number.isInteger(s.value)).toBe(true);
    expect(PAGE.stats[PAGE.stats.length - 1].value).toBe(ENTRIES.length);
  });

  it("la fecha del corte es una fecha de verdad", () => {
    expect(AS_OF).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(Number.isNaN(Date.parse(AS_OF))).toBe(false);
  });
});

describe("los derechos de las fotografias", () => {
  it("cada ficha acredita a su correduria y enlaza a su registro", () => {
    // Es la letra `b` de la Regla 6.10.F.1: difundir el anuncio de otro obliga
    // a revelar su correduria de forma visible.
    for (const e of ENTRIES) {
      expect(e.brokerage.length, `ficha ${e.n} sin correduria`).toBeGreaterThan(4);
      // El pie esta compuesto con guion largo donde el registro del MLS trae
      // uno corto —«Sotheby's International Realty — Hyman Mall»—, asi que se
      // comparan normalizados. Lo que importa es que la correduria este
      // nombrada, no como se tipografio el guion.
      const dash = (x: string) => x.replace(/[\u2010-\u2015]/g, "-");
      expect(dash(e.caption), `ficha ${e.n}: el pie no nombra a ${e.brokerage}`).toContain(
        dash(e.brokerage),
      );
      expect(e.listingUrl, `ficha ${e.n}`).toMatch(/^https:\/\//);
      expect(e.mls, `ficha ${e.n}`).toMatch(/^\d+$/);
    }
  });

  it("el aviso de derechos sigue en la pagina", () => {
    expect(PAGE.rights).toMatch(/may not be reproduced/i);
    expect(read(ARTICLE_PAGE)).toContain("PAGE.rights");
  });

  it("existe el rastro en papel, con las doce filas", () => {
    const doc = read(RIGHTS);
    for (const e of ENTRIES) {
      expect(doc, `${RIGHTS} no menciona el MLS ${e.mls}`).toContain(e.mls);
    }
  });

  it("ninguna fotografia del Journal esta versionada", () => {
    // La decision de Ender del 20-sep-2026: fuera del repositorio hasta que
    // haya permiso escrito. El repositorio es publico y el historial de git no
    // se deshace, asi que esto se vigila y no se recuerda.
    const tracked = execFileSync(
      "git",
      ["ls-files", "frontend/public/blog/img"],
      { cwd: resolve(ROOT, ".."), encoding: "utf8" },
    ).trim();
    expect(tracked, `hay fotos versionadas:\n${tracked}`).toBe("");
  });
});

describe("las dos puertas de publicacion", () => {
  it("son dos constantes y no una: enlazar no es indexar", () => {
    // El diseno original tenia UNA puerta, y eso obligaba a elegir entre no
    // ensenar la seccion a nadie o entregarsela al rastreador. Son decisiones
    // con costes distintos: el enlace de la portada se apaga en un despliegue;
    // lo que Google ya cacheo, no. Si alguien las vuelve a fundir en una, este
    // test se pone rojo.
    const src = read("lib/journal/publication.ts");
    expect(src).toMatch(/export const LINKED/);
    expect(src).toMatch(/export const INDEXED/);
    expect(read("app/sitemap.ts")).toContain("JOURNAL_INDEXED");
    expect(read("components/landing/Landing.tsx")).toContain("JOURNAL_LINKED");
  });

  it("el INDICE no se abre mientras quede un permiso pendiente", () => {
    const pending = ENTRIES.filter((e) => e.permission !== "granted");
    if (INDEXED) {
      expect(
        pending.map((e) => `${e.n} ${e.brokerage}`),
        "INDEXED esta en true con permisos sin conceder: ver lib/journal/DERECHOS.md",
      ).toEqual([]);
    } else {
      // Con la puerta del indice cerrada las dos paginas tienen que quedarse
      // fuera de los indices. Es la mitad que se olvida: quitar el enlace y
      // dejar el `robots: index` deja la pagina igual de encontrable.
      for (const page of [INDEX_PAGE, ARTICLE_PAGE]) {
        expect(read(page), `${page} no ata robots a la puerta del indice`).toContain(
          "robots: { index: INDEXED, follow: INDEXED }",
        );
      }
    }
  });

  it("el sitemap no invita a rastrear lo que la pagina marca como no indexable", () => {
    // Listar la ruta y decirle al rastreador que no la indexe son ordenes
    // opuestas, y el sitemap es la que ademas le pide que venga. Va con
    // INDEXED, nunca con LINKED.
    const src = read("app/sitemap.ts");
    expect(src).toContain("JOURNAL_INDEXED");
    expect(src).not.toContain("JOURNAL_LINKED");
    expect(src).toMatch(/PUBLIC_PATHS\.filter/);
  });

  it("la portada enlaza The Journal en los tres sitios, tras la misma condicion", () => {
    const src = read("components/landing/Landing.tsx");
    // Dos son JSX (`href={JOURNAL_HREF}`) y el tercero es la entrada del menu
    // movil, que es un objeto (`href: JOURNAL_HREF`). Contar solo la primera
    // forma deja el menu del telefono fuera de la comprobacion — y el movil es
    // justo donde se pidio poder llegar.
    const links = src.match(/href[=:] ?\{?JOURNAL_HREF\}?/g) ?? [];
    expect(links.length, "la portada deberia enlazar el Journal en tres sitios").toBe(3);
    // Ninguno puede haberse quedado apuntando al indice a mano.
    expect(src, "queda un /blog literal en la portada").not.toMatch(/href[=:] ?"\/blog"/);
    // Los tres van tras la misma condicion, y esa condicion es LINKED.
    expect((src.match(/JOURNAL_LINKED/g) ?? []).length).toBeGreaterThanOrEqual(4);
    expect(src, "la portada no debe leer la puerta del indice").not.toContain(
      "JOURNAL_INDEXED",
    );
  });

  it("el boton de la portada lleva al articulo, y el indice no queda huerfano", () => {
    // El diseno manda el boton al indice (README §2). Va al articulo por
    // decision de Ender: con UNA sola pieza, el indice es un clic que no
    // ensena nada. Cuando haya una segunda, esto vuelve al indice.
    expect(ENTRY_HREF).toBe(`/blog/${SLUG}`);
    // Y el indice se sigue pudiendo alcanzar: la cabecera y el pie del propio
    // Journal, y la miga de pan del articulo. Sin esto, /blog existiria sin
    // que nadie pudiera llegar.
    expect(read("components/journal/JournalChrome.tsx")).toContain('const JOURNAL_HREF = "/blog";');
    expect(read(ARTICLE_PAGE), "el articulo no vuelve al indice").toContain('href="/blog"');
  });

  it("con el enlace abierto, la seccion tiene que ser alcanzable de verdad", () => {
    // Un enlace en la portada que apunta a una ruta que el host devuelve con un
    // 308 al panel es peor que no tener enlace: se ve, se toca y no lleva a
    // ningun sitio. `PUBLIC_PATHS` es lista blanca.
    if (!LINKED) return;
    expect(read("lib/hosts.ts"), "/blog no esta en PUBLIC_PATHS").toMatch(
      /"\/blog"/,
    );
  });
});

describe("las fotos se copian, no se reprocesan", () => {
  const script = () => read("scripts/journal-photos.sh");

  it("las 48 ajenas se copian tal cual", () => {
    // Las reducia a 1600px la principal y 800px las otras tres, «porque eso
    // separa 30 MB de 3». Medido donde importa: la principal se pinta a 1129
    // CSS px, que en retina son 2258 reales. Con 1600 le faltaban 658 y se
    // veia — doce de las quince que carga el articulo salian blandas, y Ender
    // lo leyo como que la pagina no era la suya.
    expect(script()).toMatch(/cp "\$f" "\$DEST\/img\/\$base"/);
  });

  it("solo el skyline se recodifica, y solo porque va versionado", () => {
    // Es del cliente, con derechos limpios, y vive en un repositorio publico:
    // 2240px le sobran para lo que se pinta, y son 707 KB en vez de 2,0 MB.
    // Ahi el limite que manda es el del repositorio, no el de la vista.
    const src = script();
    const resizes = src.match(/resampleWidth/g) ?? [];
    expect(resizes.length, "solo deberia quedar UN redimensionado").toBe(1);
    const i = src.indexOf("resampleWidth");
    const zona = src.slice(Math.max(0, i - 700), i);
    expect(zona, "el unico redimensionado tiene que ser el del skyline").toContain(
      "denver-skyline.jpg",
    );
  });

  it("y sigue sin versionarse ninguna foto ajena", () => {
    // La guarda de siempre, repetida aqui a proposito: subir la resolucion es
    // justo el cambio que tienta a «meterlas ya en el repo».
    const tracked = execFileSync("git", ["ls-files", "frontend/public/blog/img"], {
      cwd: resolve(ROOT, ".."),
      encoding: "utf8",
    }).trim();
    expect(tracked, `hay fotos versionadas:\n${tracked}`).toBe("");
  });
});

describe("la copia es la del diseno, no la mia", () => {
  // Como se cuelan estas: el generador extrae lo que sabe extraer, y lo que
  // no extrajo alguien lo escribe a mano en la pagina. No falla nada, no lo
  // ve un diff y la pagina se ve bien — simplemente ya no dice lo que el
  // cliente escribio. Las dos que se colaron aqui salieron de comparar el
  // texto RENDERIZADO contra el prototipo servido, no leyendo el codigo.

  it("el titular de «what lands here» viaja con su parrafo", () => {
    // Faltaba entero. Un h2 solo tambien se ve bien, y por eso nadie lo noto.
    expect(INDEX.nextDek.length).toBeGreaterThan(60);
    expect(read(INDEX_PAGE)).toContain("INDEX.nextDek");
  });

  it("la frase que lleva al formulario esta DENTRO de esa copia", () => {
    // El enlace etiquetado se trocea de esta frase. Si el diseno la cambia y
    // la frase desaparece, `track.test.ts` seguiria verde —el `href` literal
    // sigue en el fuente— y el enlace se renderizaria VACIO. Este es el test
    // que lo ve.
    expect(INDEX.nextDek).toContain("tell us on the call");
    expect(read(INDEX_PAGE)).toContain('const CALL_PHRASE = "tell us on the call";');
  });

  it("las dos paginas usan LA MISMA frase bajo «fifteen minutes»", () => {
    // El diseno tiene una sola. Yo habia escrito dos distintas, una por
    // pagina, sin anotarlo: reescribir la copia del cliente en silencio.
    expect(PAGE.talkDek.length).toBeGreaterThan(80);
    for (const page of [INDEX_PAGE, ARTICLE_PAGE]) {
      expect(read(page), `${page} no usa PAGE.talkDek`).toContain("PAGE.talkDek");
    }
  });

  it("no queda ninguna linea inventada por mi colgada de un #consult", () => {
    // Las dos que hubo. La del indice ya no existe; la del articulo se queda
    // —es la unica via etiquetada al formulario que tiene esa pagina— y esta
    // declarada aqui para que no vuelva a pasar por copia del diseno.
    expect(read(INDEX_PAGE)).not.toContain("Rather ask us something directly");
    expect(read(ARTICLE_PAGE)).toContain("Looking at one of these? Tell us which");
  });
});

describe("la pagina dice quien anuncia", () => {
  it("no nombra ninguna correduria propia: las lineas reguladas salen de config", () => {
    // Misma guarda que `/fall`. Aqui cuenta el doble: el prototipo traia el
    // nombre escrito en la cabecera y el logo en el pie.
    for (const file of [INDEX_PAGE, ARTICLE_PAGE, DATA, "components/journal/JournalChrome.tsx"]) {
      expect(read(file), `${file} nombra una correduria a mano`).not.toMatch(/Engel/i);
    }
    expect(read("components/journal/JournalChrome.tsx")).toContain("LANDING.brokerage");
  });

  it("las dos paginas montan el formulario compartido, no una copia", () => {
    for (const file of [INDEX_PAGE, ARTICLE_PAGE]) {
      const src = read(file);
      expect(src, `${file}`).toContain("<ConsultForm");
      expect(src, `${file}`).toContain('id="consult"');
      expect(src, `${file}`).toContain('href="#consult"');
      // Un <form> propio aqui seria un segundo registro de consentimiento.
      expect(src, `${file} escribe su propio formulario`).not.toMatch(/<form\b/);
    }
  });

  it("el articulo ancla las doce fichas donde la tira las busca", () => {
    const src = read(ARTICLE_PAGE);
    expect(src).toContain("id={`n${entry.n}`}");
    expect(read("components/journal/Strip.tsx")).toContain("href={`#n${panel.n}`}");
  });
});

describe("los ficheros que la pagina pide", () => {
  it("el skyline esta en su sitio", () => {
    expect(existsSync(resolve(ROOT, "public/blog/denver-skyline.jpg"))).toBe(true);
  });

  it("las 48 fotografias estan, o el guion dice como traerlas", () => {
    // No se afirma que existan: por decision, viven fuera del repositorio y en
    // un portatil recien clonado NO estan. Lo que si tiene que existir siempre
    // es el guion que las trae, y el aviso de por que.
    const script = "scripts/journal-photos.sh";
    expect(existsSync(resolve(ROOT, script))).toBe(true);
    expect(read(script)).toMatch(/strictly prohibited/);

    // O estan las 48, o no esta ninguna. Un conjunto a medias significa que el
    // guion se quedo a medias, y eso si es un fallo. La asercion corre SIEMPRE:
    // una que solo se evalua dentro de un `if` sale verde con el defecto y sin el.
    const missing = ENTRIES.flatMap((e) => e.photos).filter(
      (p) => !existsSync(resolve(ROOT, "public/blog/img", p)),
    );
    expect(
      [0, 48],
      `faltan ${missing.length} de 48 fotos: corre frontend/${script}`,
    ).toContain(missing.length);
  });

  it("todo lo que se toca en el armazon llega al suelo tactil de 44 px", () => {
    // Medido a 390 px el 20-sep: «Home» y «Journal» de la cabecera daban **17
    // px de alto** —la altura de la letra— mientras el wordmark y la pildora ya
    // daban 44. En un telefono eso es un enlace que se falla al tocarlo, y es
    // el sitio donde se pulsa con el pulgar. El handoff lo pide explicitamente:
    // «Touch targets are ≥44px».
    const src = read("components/journal/JournalChrome.tsx");
    const anclas = src.match(/<a\b[\s\S]*?>/g) ?? [];
    expect(anclas.length, "el armazon deberia tener sus enlaces").toBeGreaterThanOrEqual(4);
    for (const a of anclas) {
      expect(a, `un enlace del armazon sin suelo tactil: ${a.slice(0, 60)}`).toMatch(
        /min-h-\[44px\]|FOOT_LINK/,
      );
    }
    // Y la constante del pie tiene que seguir llevandolo dentro.
    expect(src).toMatch(/const FOOT_LINK = "[^"]*min-h-\[44px\]/);
  });

  it("el generador del contenido esta en el repo y el modulo lo nombra", () => {
    // El modulo de datos dice de si mismo que es generado. Si el generador no
    // viaja con el, esa frase es falsa el dia que alguien tenga que cambiar una
    // coma: se editaria a mano el fichero que dice que no se edita a mano.
    // No se ejecuta aqui — necesita el paquete de diseno, que no esta en el
    // repositorio porque lleva dentro las 48 fotografias ajenas.
    expect(existsSync(resolve(ROOT, "scripts/journal-content.py"))).toBe(true);
    expect(read(DATA)).toContain("scripts/journal-content.py");
    expect(read("scripts/journal-content.py")).toContain("JOURNAL_HANDOFF");
  });

  it("el slug de la ruta y el del modulo son el mismo", () => {
    expect(SLUG).toBe("twelve-houses-worth-the-detour");
    expect(existsSync(resolve(ROOT, "app/blog", SLUG, "page.tsx"))).toBe(true);
  });
});

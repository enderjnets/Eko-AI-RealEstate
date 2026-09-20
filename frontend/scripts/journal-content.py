#!/usr/bin/env python3
"""Genera lib/journal/twelveHouses.ts desde el prototipo y listings.json.

Uso, desde `frontend/scripts`:

    python3 journal-content.py ../lib/journal/twelveHouses.ts

y despues `git diff` dice exactamente que ha cambiado.

El texto NO se transcribe. Sale del HTML, se comprueba que vuelve a aparecer en
el origen, y se emite ya en TypeScript. Si el prototipo cambia, se vuelve a
correr esto y el diff dice exactamente que cambio.
"""
import html
import json
import os
import re
import sys

# El paquete de diseno NO vive en el repositorio: lleva dentro las 48
# fotografias ajenas. Se busca donde estaba el 20-sep-2026, o donde diga la
# variable de entorno JOURNAL_HANDOFF.
BASE = os.environ.get(
    "JOURNAL_HANDOFF",
    os.path.expanduser("~/Downloads/design_handoff_denver_journal"),
)
ART = f"{BASE}/Blog-Twelve-Houses-v2.dc.html"
IDX = f"{BASE}/Blog.dc.html"
DATA = f"{BASE}/data/listings.json"


def text(f):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", f))).strip()


def rich(fragment):
    parts = []
    for chunk in re.split(r"(<em>.*?</em>)", fragment, flags=re.S):
        if not chunk:
            continue
        em = chunk.startswith("<em>")
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", chunk)))
        if t.strip():
            parts.append({"t": t, "em": True} if em else {"t": t})
    if parts:
        parts[0]["t"] = parts[0]["t"].lstrip()
        parts[-1]["t"] = parts[-1]["t"].rstrip()
    return parts


def flat(segs):
    return "".join(s["t"] for s in segs)


def ts(value, indent=0):
    """Serializa a TypeScript. Las cadenas van con comillas dobles y escapadas."""
    pad = "  " * indent
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = ",\n".join(f"{pad}  {ts(v, indent + 1)}" for v in value)
        return "[\n" + inner + f",\n{pad}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = ",\n".join(
            f"{pad}  {k}: {ts(v, indent + 1)}" for k, v in value.items()
        )
        return "{\n" + inner + f",\n{pad}}}"
    raise TypeError(type(value))


def main():
    if not os.path.isdir(BASE):
        print(
            "no encuentro el paquete de diseno en " + BASE,
            file=sys.stderr,
        )
        print(
            "Pasalo con JOURNAL_HANDOFF=/ruta/al/paquete. No esta en el "
            "repositorio a proposito: lleva dentro las 48 fotografias ajenas.",
            file=sys.stderr,
        )
        return 1
    src = open(ART, encoding="utf-8").read()
    idx = open(IDX, encoding="utf-8").read()
    listings = {x["slug"]: x for x in json.load(open(DATA))}
    stripped = " ".join(text(src).split())

    # ---------- las doce fichas ----------
    starts = [m.start() for m in re.finditer(r'<article id="n\d+"', src)]
    assert len(starts) == 12, len(starts)
    bounds = list(zip(starts, starts[1:] + [src.find("</section>", starts[-1])]))

    entries = []
    for n, (a, b) in enumerate(bounds, start=1):
        seg = src[a:b]
        head = re.findall(r"<span[^>]*>(.*?)</span>", seg[: seg.find("<h3")], re.S)
        photos = re.findall(r'src="blog/img/([^"]+)"', seg)
        alts = [html.unescape(x) for x in re.findall(r'alt="([^"]*)"', seg)]
        slug = photos[0].rsplit("-", 1)[0]
        rec = listings[slug]

        dl = re.search(r"<dl[^>]*>(.*?)</dl>", seg, re.S).group(1)
        facts = [
            {"label": text(dt), "value": text(dd)}
            for dt, dd in re.findall(
                r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", dl, re.S
            )
        ]
        note_p = re.search(
            r"<p[^>]*>(<span[^>]*>Worth knowing</span>.*?)</p>", seg, re.S
        ).group(1)
        body_zone = seg[seg.find("</figure>") : seg.find("<dl")]

        entries.append(
            {
                "n": n,
                "slug": slug,
                "indexLabel": text(head[0]),
                "eyebrow": text(head[1]),
                "headline": text(re.search(r"<h3[^>]*>(.*?)</h3>", seg, re.S).group(1)),
                "address": text(re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)[0]),
                "photos": photos,
                "alts": alts,
                "caption": text(
                    re.search(r"<figcaption[^>]*>(.*?)</figcaption>", seg, re.S).group(1)
                ),
                "body": text(re.search(r"<p[^>]*>(.*?)</p>", body_zone, re.S).group(1)),
                "facts": facts,
                "noteLabel": text(
                    re.search(r"<span[^>]*>(.*?)</span>", note_p, re.S).group(1)
                ),
                "note": rich(
                    re.sub(r"<span[^>]*>.*?</span>", "", note_p, count=1, flags=re.S)
                ),
                "listingUrl": html.unescape(re.search(r'<a href="([^"]+)"', seg).group(1)),
                "brokerage": rec["broker"],
                "mls": rec["mls"],
                # El permiso escrito de la Regla 6.10.F.1.a. Nadie lo tiene aun.
                "permission": "pending",
            }
        )

    # ---------- la tira ----------
    # Los paneles son `data-sel`/`data-target` y todo dentro son <span>, no <div>.
    panels = []
    for m in re.finditer(
        r'data-sel="(\d+)" data-target="n(\d+)".*?'
        r"<span[^>]*>(\d{2})</span>.*?"
        r'data-lab="1"[^>]*>\s*<span[^>]*>([^<]+)</span>\s*<span[^>]*>([^<]+)</span>',
        src,
        re.S,
    ):
        panels.append(
            {
                "n": int(m.group(2)),
                "label": m.group(3),
                "name": text(m.group(4)),
                "where": text(m.group(5)),
            }
        )

    # ---------- descartadas ----------
    marks = [
        m.start()
        for m in re.finditer(
            r'<div data-reveal="1" style="display:grid;grid-template-columns:'
            r'repeat\(auto-fit,minmax\(220px,1fr\)\)',
            src,
        )
    ]
    end = src.find("</section>", marks[-1])
    passed = []
    for row in [src[a:b] for a, b in zip(marks, marks[1:] + [end])]:
        divs = re.findall(r"<div[^>]*>([^<]+)</div>", row)
        para = re.search(r"<p[^>]*>(.*?)</p>", row, re.S)
        if len(divs) >= 3 and para:
            passed.append(
                {
                    "price": text(divs[0]),
                    "city": text(divs[1]),
                    "street": text(divs[2]),
                    "reason": rich(para.group(1)),
                }
            )

    # ---------- prosa de la pagina ----------
    def heading(tag, lead_start):
        for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", src, re.S):
            inner = m.group(1)
            if text(inner).startswith(lead_start):
                acc = re.search(
                    r"<span[^>]*font-style:italic[^>]*>(.*?)</span>", inner, re.S
                )
                return {
                    "lead": text(
                        re.sub(
                            r"<span[^>]*font-style:italic.*?</span>", "", inner, flags=re.S
                        )
                    ),
                    "accent": text(acc.group(1)) if acc else "",
                }
        raise LookupError(lead_start)

    # `data-strip` aparece antes, dentro del <style>; hay que buscar el ATRIBUTO
    # y ademas empezar a contar despues del header.
    _hdr = src.find("</header>")
    hero_zone = src[_hdr : src.find("data-strip=", _hdr)]
    hero_bits = [
        html.unescape(t).strip()
        for t in re.findall(r">([^<>]{2,400})<", hero_zone)
        if html.unescape(t).strip()
    ]

    stats = [
        {"label": text(lb), "value": int(v)}
        for lb, v in re.findall(
            r"<div[^>]*>([^<]+)</div>\s*<div[^>]*data-count=\"(\d+)\"", src
        )
    ]

    meth_zone = src[src.find("How we") : src.find('id="n1"')]
    # El cuarto parrafo largo de esta zona no es metodologia: es el dek de la
    # seccion "The twelve" que viene justo despues.
    _long = [
        text(p)
        for p in re.findall(r"<p[^>]*>(.*?)</p>", meth_zone, re.S)
        if len(text(p)) > 80
    ]
    meth, twelve_dek = _long[:3], _long[3]
    skyline_caption = text(
        re.search(r"<figcaption[^>]*>(.*?)</figcaption>", meth_zone, re.S).group(1)
    )

    rights = next(
        text(p)
        for p in re.findall(r"<p[^>]*>(.*?)</p>", src, re.S)
        if "may not be reproduced" in text(p)
    )

    page = {
        "breadcrumb": hero_bits[1],
        "h1": heading("h1", "Twelve houses"),
        "dek": hero_bits[4],
        "byline": hero_bits[5],
        "date": hero_bits[6],
        "readTime": hero_bits[7],
        "markets": hero_bits[8],
        "stripCaption": "Hover a panel to leaf through its photographs · tap on a phone",
        "stats": stats,
        "method": {
            "heading": heading("h2", "How we"),
            "skylineCaption": skyline_caption,
            "paragraphs": meth,
        },
        "twelveHeading": heading("h2", "The twelve"),
        "twelveDek": twelve_dek,
        "passedHeading": heading("h2", "What we"),
        "passedDek": text(
            re.search(
                r"Six that looked promising[^<]*", src
            ).group(0)
        ),
        "rights": rights,
        "talkHeading": heading("h2", "Fifteen minutes"),
    }

    # ---------- indice ----------
    # El corte empieza en el <div> que envuelve la fila, no en la palabra:
    # arrancar en ">Latest<" se la come y desplaza todos los indices uno.
    _lat = idx.find(">Latest<")
    _card = idx[idx.rfind('<div data-reveal="1"', 0, _lat) : idx.find("</section>", _lat)]
    _card_spans = [text(x) for x in re.findall(r"<span[^>]*>([^<]+)</span>", _card)]
    index = {
        "latestLabel": _card_spans[0],
        "latestCount": _card_spans[1],
        "cardCategory": _card_spans[2],
        "cardDate": _card_spans[3],
        "cardReadTime": _card_spans[4],
        "articleTitle": _card_spans[5],
        "cardCta": _card_spans[-1],
        "cardPhoto": re.search(r'src="blog/img/([^"]+)"', _card).group(1),
        "cardAlt": html.unescape(re.search(r'alt="([^"]*)"', _card).group(1)),
        "cardDek": text(re.search(r"<p[^>]*>(.*?)</p>", _card, re.S).group(1)),
        "h1": (lambda m: {
            "lead": text(re.sub(r"<span[^>]*font-style:italic.*?</span>", "", m, flags=re.S)),
            "accent": text(re.search(r"<span[^>]*font-style:italic[^>]*>(.*?)</span>", m, re.S).group(1)),
        })(re.search(r"<h1[^>]*>(.*?)</h1>", idx, re.S).group(1)),
        "dek": text(re.findall(r"<p[^>]*>(.*?)</p>", idx, re.S)[0]),
        # Solo las tres columnas de "what lands here next". La cuarta pareja
        # h3+p del prototipo es el mensaje de exito de SU formulario, y aqui el
        # formulario es `ConsultForm`, que trae el suyo.
        "next": [
            {"title": text(t), "body": text(b)}
            for t, b in re.findall(
                r"<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>", idx, re.S
            )
        ][:3],
    }

    # ---------- comprobaciones ----------
    problems = []
    if len(panels) != 12:
        problems.append(f"paneles de la tira: {len(panels)}")
    if len(passed) != 6:
        problems.append(f"descartadas: {len(passed)}")
    if len(stats) != 4:
        problems.append(f"estadisticas: {len(stats)}")
    if len(meth) != 3:
        problems.append(f"parrafos de metodologia: {len(meth)}")
    if len(index["next"]) != 3:
        problems.append(f"columnas del indice: {len(index['next'])}")
    for e in entries:
        if len(e["photos"]) != 4:
            problems.append(f"n{e['n']}: {len(e['photos'])} fotos")
        for f in ("headline", "address", "caption", "body"):
            if " ".join(e[f].split()) not in stripped:
                problems.append(f"n{e['n']}.{f} no reencontrado")
        if " ".join(flat(e["note"]).split()) not in stripped:
            problems.append(f"n{e['n']}.note no reencontrado")
    if problems:
        print("FALLOS:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1

    # ---------- emitir ----------
    header = '''/**
 * "Twelve houses worth the detour" — el contenido del primer articulo.
 *
 * NO SE EDITA A MANO. Lo emite `frontend/scripts/journal-content.py` desde el
 * paquete de diseno; para cambiar algo se corre el generador y se lee el diff.
 * Son doce fichas, doce cuerpos de texto y noventa y seis cifras, y una errata
 * en cualquiera de ellas es una afirmacion falsa sobre la casa de otro. El
 * generador comprueba que cada cadena vuelve a aparecer en el HTML de origen
 * antes de emitir nada.
 *
 * Vive en `lib/` y no en la pagina porque un modulo de pagina de Next solo
 * puede exportar los nombres del framework. Ojo con la consecuencia que ya
 * mordio en `fallGuide.ts`: **Tailwind no escanea `lib/`**, asi que aqui no
 * puede haber ni una clase de Tailwind. Todo valor visual va crudo.
 *
 * Ninguna de estas casas es nuestra. Cada ficha acredita a la correduria que la
 * tiene y enlaza al registro completo, que es lo que exige la Regla 6.10.F.1.b
 * de Colorado; el permiso escrito de la letra `a` se lleva en `permission`.
 */

/** Un tramo de texto. `em` marca la italica; no hay HTML crudo en los datos. */
export interface Segment {
  readonly t: string;
  readonly em?: boolean;
}

/** Un par de la rejilla de datos. La ficha 05 trae seis, no ocho, a proposito. */
export interface Fact {
  readonly label: string;
  readonly value: string;
}

export type PermissionState = "pending" | "granted";

export interface Entry {
  readonly n: number;
  readonly slug: string;
  readonly indexLabel: string;
  readonly eyebrow: string;
  readonly headline: string;
  readonly address: string;
  /** Los cuatro ficheros: principal primero, luego las tres miniaturas. */
  readonly photos: readonly string[];
  readonly alts: readonly string[];
  readonly caption: string;
  readonly body: string;
  readonly facts: readonly Fact[];
  readonly noteLabel: string;
  readonly note: readonly Segment[];
  readonly listingUrl: string;
  readonly brokerage: string;
  readonly mls: string;
  /**
   * Permiso escrito de la correduria (Regla 6.10.F.1.a). Mientras alguna siga
   * en "pending" el articulo no sale a publico: lo vigila `journal.test.ts`.
   */
  readonly permission: PermissionState;
}

export interface Panel {
  readonly n: number;
  readonly label: string;
  readonly name: string;
  readonly where: string;
}

export interface Passed {
  readonly price: string;
  readonly city: string;
  readonly street: string;
  readonly reason: readonly Segment[];
}

/** Titular con el acento en italica al final, que es la voz de la pagina. */
export interface Heading {
  readonly lead: string;
  readonly accent: string;
}

/**
 * La fecha del corte. Las cifras son una foto del registro de ese dia y la
 * Regla 6.10.F.1.c exige que el anuncio sea exacto: una ficha ya vendida lo
 * vuelve enganoso. Se comprueba antes de publicar, no se supone.
 */
export const AS_OF = "2026-09-20";

export const SLUG = "twelve-houses-worth-the-detour";
'''

    body = "\n".join(
        [
            header,
            "export const PAGE = " + ts(page) + " as const;",
            "",
            "export const STRIP: readonly Panel[] = " + ts(panels) + ";",
            "",
            "export const ENTRIES: readonly Entry[] = " + ts(entries) + ";",
            "",
            "export const PASSED: readonly Passed[] = " + ts(passed) + ";",
            "",
            "export const INDEX = " + ts(index) + " as const;",
            "",
            "/** Copias para los tests; ver la nota de `fallGuide.ts` sobre esto. */",
            "export const ENTRIES_FOR_TEST = ENTRIES;",
            "",
        ]
    )
    open(sys.argv[1], "w", encoding="utf-8").write(body)
    print(f"escrito {sys.argv[1]}")
    print(f"  fichas {len(entries)} · paneles {len(panels)} · descartadas {len(passed)}")
    print(f"  pares dl {[len(e['facts']) for e in entries]}")
    print(f"  estadisticas {[(s['label'], s['value']) for s in stats]}")
    print(f"  permisos pendientes: {sum(1 for e in entries if e['permission'] == 'pending')}/12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

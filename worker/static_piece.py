"""The other shape of short: clips, one line of text, piano, no voice.

Lane B builds a narrated video — synthetic voice, karaoke captions, a picture
per sentence. Measured on @denverhomestory that shape reached a median of six
plays. The one piece that did not was built by hand in this shape: four clips,
**one static line held for the whole video**, no narrator, and piano. It took
485 plays, sixty per cent of the account's entire reach.

So this is not a variation on `produce.py`, and it deliberately does not go
through the render worker: the worker's job queue would add a voice and
captions, which is precisely the format being avoided. The finished file is
uploaded with `kind=generated` and no `scenes`, so neither lane claims it.

Three rules carried over from the renderer, because they were each paid for:

* **The length is declared, never derived.** No `-shortest`: it answers "which
  track is shorter", so any arithmetic slip upstream silently drops the tail.
  `-t` sets it, `apad` fills the audio, and then it is MEASURED.
* **`textfile=`, never `text=`.** drawtext's option parser and the filtergraph
  parser have separate escaping, and a brokerage really is called things like
  "Smith & Jones, Realty, Inc.".
* **The brokerage line comes from the caller**, which reads it from the
  organisation. Never a literal in this file.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from worker.assemble import OUT_H, OUT_W, escape_path

#: The winning piece was 12.65 s over four clips. Not a coincidence worth
#: rounding away: a still line of text has to be readable at a glance and the
#: viewer has to reach the end, so the whole thing is shorter than the time it
#: takes to lose interest.
DEFAULT_SECONDS = 12.8

#: When the brand block appears. Late enough that the promise is read first,
#: early enough that half the video carries the address.
BRAND_FROM_SECONDS = 6.0

#: The winning piece drew its words as a light serif straight onto the
#: landscape — no slab of colour behind them. A box is the safe choice when you
#: cannot see the footage; here the footage is chosen with the words in mind, and
#: the box was reading as a caption pasted over a stock photo. Legibility comes
#: from a shadow instead, which costs nothing and hides in the grain.
_TEXT_SIZE = 58
_CTA_SIZE = 42
_DOMAIN_SIZE = 40
_BROKERAGE_SIZE = 28
_BOX_PAD = 22
_LINE_SPACING = 18

#: Where the held text starts, as a fraction of frame height. Not centred: the
#: ask sits below it, and a block centred on its own would push the pair low.
_TEXT_TOP = 0.44
#: Between the last line of the promise and the ask.
_CTA_GAP = 40
#: Drawn under every word on the landscape, since there is no box to sit on.
#: A shadow alone was not enough: measured on F1, the last shot is a snowfield
#: and white-on-white swallowed the first line. The thin dark outline is what
#: rescues it — invisible against a dark slope, and the only thing holding the
#: words up against snow or a bright sky.
_SHADOW = (
    ":shadowcolor=black@0.7:shadowx=2:shadowy=2"
    ":borderw=2:bordercolor=black@0.45"
)

#: La marca, arriba a la derecha. Los MISMOS numeros que `assemble.py` usa en
#: la cinta narrada, y a proposito: dos formatos con el logo a distinto tamano
#: en el mismo perfil se leen como dos cuentas. `verify.brand_is_present` mide
#: con estos valores por defecto, asi que cambiarlos aqui sin cambiarlos alli
#: haria que la comprobacion buscase donde no esta.
_MARK_WIDTH = 190
_MARK_MARGIN = 44


class Rejected(Exception):
    """The file was built and is not what was asked for."""


@dataclass(frozen=True)
class Piece:
    clips: list[Path]
    #: Held for the entire video. One or two short lines; ffmpeg draws the
    #: newlines as written.
    text: str
    #: `denverhomestory.com/fall`, drawn under the brand line from
    #: `BRAND_FROM_SECONDS`. **May be empty**, and empty is the better choice
    #: when `text` already carries the ask.
    #:
    #: Showing the address is not the same as asking for anything. The first
    #: cut of these pieces displayed the URL and nothing else, and a viewer
    #: reading a headline about elevation has no reason to read a line of small
    #: type at the bottom as an offer. When the ask lives in the held text —
    #: "Free guide → denverhomestory.com/fall" — repeating the address below it
    #: is noise, and two places to look is worse than one.
    domain: str
    #: The organisation's own line. Colorado requires advertising to identify
    #: the brokerage.
    brokerage_line: str
    #: The ask, drawn smaller directly under the promise. Separate from `text`
    #: because it is a different size, not a different sentence: one voice says
    #: what this is, a quieter one says what to do about it. Empty when the
    #: piece carries no ask of its own.
    #:
    #: It goes after `brokerage_line` because it has a default and that one does
    #: not — a dataclass refuses the other order, and the refusal is right: the
    #: identification is never optional.
    cta: str = ""
    seconds: float = DEFAULT_SECONDS


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _centred_lines(
    *,
    workdir: Path,
    name: str,
    text: str,
    size: int,
    below: int,
    font_clause: str,
    source: str,
) -> tuple[str, str, int]:
    """One overlay per line, each centred against its own width.

    Handed a multi-line textfile, drawtext centres the *block* and ranges the
    lines left inside it, so a short line above a long one reads as indented.
    `x=(w-text_w)/2` is per-overlay, so the only way to centre every line is to
    give every line an overlay.

    Returns the filtergraph fragment, the label the next filter should read
    from, and how tall the block is in pixels — the caller needs that last one
    because the filtergraph cannot ask one drawtext how tall another was.
    """
    fragment = ""
    last = source
    step = size + _LINE_SPACING
    lines = text.split("\n")
    for index, line in enumerate(lines):
        line_file = _write(workdir / f"{name}{index}.txt", line)
        label = f"{name}{index}"
        fragment += (
            f"[{last}]drawtext=textfile='{escape_path(str(line_file))}'"
            f"{font_clause}:fontcolor=white:fontsize={size}{_SHADOW}"
            f":x=(w-text_w)/2:y=h*{_TEXT_TOP}+{below + index * step}[{label}];"
        )
        last = label
    return fragment, last, len(lines) * step


def build_command(
    piece: Piece,
    workdir: Path,
    output: Path,
    *,
    font: str | None,
    music: Path | None,
    mark: Path | None = None,
) -> list[str]:
    """The whole render as one ffmpeg invocation, pure enough for a test.

    Each clip is scaled to fit and padded with a blurred copy of itself, never
    cropped: whoever framed the shot decided what it is about, and a crop is a
    machine overruling them.
    """
    if not piece.clips:
        raise ValueError("a piece with no clips is not a video")
    if piece.seconds <= 0:
        raise ValueError("a piece has to last some time")

    each = piece.seconds / len(piece.clips)
    font_clause = f":fontfile='{escape_path(font)}'" if font else ""

    inputs: list[str] = []
    graph = ""
    for index, clip in enumerate(piece.clips):
        inputs += ["-i", str(clip)]
        # `trim` + `setpts` rather than `-t` per input: the length of every
        # segment is decided here, in one place, so the concatenated total is
        # arithmetic and not the sum of whatever the clips happened to be.
        graph += (
            f"[{index}:v]trim=duration={each:.3f},setpts=PTS-STARTPTS,"
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            f"fps=30,setsar=1[fit{index}];"
            f"[{index}:v]trim=duration={each:.3f},setpts=PTS-STARTPTS,"
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=28:2,fps=30,setsar=1[bg{index}];"
            f"[bg{index}][fit{index}]overlay=(W-w)/2:(H-h)/2[seg{index}];"
        )
    graph += "".join(f"[seg{i}]" for i in range(len(piece.clips)))
    graph += f"concat=n={len(piece.clips)}:v=1:a=0[joined];"

    domain_file = _write(workdir / "domain.txt", piece.domain)
    brokerage_file = _write(workdir / "brokerage.txt", piece.brokerage_line)

    # The promise, held for the whole video: a light serif straight on the
    # landscape, no slab behind it.
    #
    # ONE DRAWTEXT PER LINE, on purpose. Handed a multi-line textfile, drawtext
    # centres the *block* and ranges the lines left inside it, so a short line
    # above a long one reads as indented rather than centred. Each line gets its
    # own `x=(w-text_w)/2` instead, which is the only way to centre every one of
    # them — and it means the filtergraph, not the copywriter, is responsible for
    # the shape.
    #
    # Vertical position is a fraction of the height rather than centred on the
    # block, because the ask is drawn underneath: a block centred on itself would
    # push the pair below the middle of the frame.
    lines = piece.text.split("\n")
    fragment, last_title, tall = _centred_lines(
        workdir=workdir, name="line", text=piece.text, size=_TEXT_SIZE,
        below=0, font_clause=font_clause, source="joined",
    )
    graph += fragment

    # The ask, smaller, under the last line of the promise. ffmpeg cannot read
    # one drawtext's height from another, so the offset is arithmetic here: the
    # promise is as tall as its own line count, which Python can count and the
    # filtergraph cannot.
    #
    # It goes through the same helper because the "send this to whoever you'd
    # go with" pieces put two lines in the ask, and a two-line ask drawn as one
    # overlay would range left inside its own block — the very fault the promise
    # was just fixed for.
    if piece.cta:
        fragment, last_title, _ = _centred_lines(
            workdir=workdir, name="cta", text=piece.cta, size=_CTA_SIZE,
            below=tall + _CTA_GAP, font_clause=font_clause, source=last_title,
        )
        graph += fragment

    # The identification, from BRAND_FROM_SECONDS to the end. Colorado requires
    # advertising to identify the brokerage; it does not require it to compete
    # with the ask. When `domain` is empty the address is already in the held
    # text and only the legal line is drawn here.
    last = last_title
    if piece.domain:
        graph += (
            f"[{last}]drawtext=textfile='{escape_path(str(domain_file))}'"
            f"{font_clause}:fontcolor=white:fontsize={_DOMAIN_SIZE}"
            f":box=1:boxcolor=black@0.55:boxborderw=18"
            f":x=(w-text_w)/2:y=h*0.82"
            f":enable='gte(t,{BRAND_FROM_SECONDS:.2f})'[domained];"
        )
        last = "domained"
        brokerage_y = f"h*0.82+{_DOMAIN_SIZE + _BOX_PAD + 22}"
    else:
        brokerage_y = "h*0.86"
    graph += (
        f"[{last}]drawtext=textfile='{escape_path(str(brokerage_file))}'"
        f"{font_clause}:fontcolor=white:fontsize={_BROKERAGE_SIZE}"
        f":borderw=4:bordercolor=black@0.9"
        f":x=(w-text_w)/2:y={brokerage_y}"
        f":enable='gte(t,{BRAND_FROM_SECONDS:.2f})'[out]"
    )

    # La marca va la ULTIMA, encima de todo: si fuese antes del texto, una
    # linea larga podria cruzarla.
    if mark is not None:
        mark_index = len(piece.clips)
        inputs += ["-i", str(mark)]
        graph += (
            f";[{mark_index}:v]scale={_MARK_WIDTH}:-1[markscaled]"
            f";[out][markscaled]overlay=W-w-{_MARK_MARGIN}:{_MARK_MARGIN}[marked]"
        )

    argv = ["ffmpeg", "-y", "-v", "error", *inputs]
    maps = ["-map", "[marked]" if mark is not None else "[out]"]
    if music is not None:
        argv += ["-i", str(music)]
        # DESPUES de la marca, que ya ocupa `len(clips)` cuando la hay. Con
        # `len(clips)` a secas los dos apuntaban al mismo indice y el audio
        # salia del PNG del logo.
        music_index = len(piece.clips) + (1 if mark is not None else 0)
        # `apad` and an explicit `-t`, the same rule as the narrated lane: the
        # audio is stretched to the video's declared length, never the other
        # way round. A bed shorter than the piece would otherwise end it early.
        graph += (
            f";[{music_index}:a]volume=0.5,apad,"
            f"atrim=duration={piece.seconds:.3f},asetpts=PTS-STARTPTS[audio]"
        )
        maps += ["-map", "[audio]", "-c:a", "aac", "-b:a", "128k"]

    argv += [
        "-filter_complex",
        graph,
        *maps,
        "-t",
        f"{piece.seconds:.3f}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output),
    ]
    return argv


def _duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return float(out.stdout.strip())


def render(
    piece: Piece,
    workdir: Path,
    output: Path,
    *,
    font: str | None = None,
    music: Path | None = None,
    mark: Path | None = None,
    tolerance: float = 0.25,
) -> Path:
    """Build it, then measure it.

    The paragraph about `-t` in the module docstring is an intention. This is
    the part that makes it a fact: a video that came out a second short is a
    video missing its end card, and it must fail here rather than be published.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    argv = build_command(piece, workdir, output, font=font, music=music, mark=mark)
    done = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        raise Rejected(f"ffmpeg refused this piece: {done.stderr.strip()[:400]}")

    made = _duration(output)
    if abs(made - piece.seconds) > tolerance:
        raise Rejected(
            f"asked for {piece.seconds:.2f}s and got {made:.2f}s — the length "
            f"was derived from the inputs somewhere instead of declared"
        )
    # El mismo guardia que la cinta narrada: mirar los PIXELES, no el comando.
    # Un overlay puede quedarse fuera del encuadre, taparse o escalar a nada, y
    # el comando se ve idéntico. Sin Pillow no se puede medir, y entonces se
    # dice — un aviso silenciado es peor que no tener comprobación.
    if mark is not None:
        from worker import verify
        verify.brand_is_present(
            output, mark, workdir, mark_width=_MARK_WIDTH, margin=_MARK_MARGIN
        )
    return output

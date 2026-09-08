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

_TEXT_SIZE = 52
_DOMAIN_SIZE = 40
_BROKERAGE_SIZE = 28
_BOX_PAD = 22


class Rejected(Exception):
    """The file was built and is not what was asked for."""


@dataclass(frozen=True)
class Piece:
    clips: list[Path]
    #: Held for the entire video. One or two short lines; ffmpeg draws the
    #: newlines as written.
    text: str
    #: `denverhomestory.com/fall` — where the caption also points. One call to
    #: action, in both places, so they cannot compete.
    domain: str
    #: The organisation's own line. Colorado requires advertising to identify
    #: the brokerage.
    brokerage_line: str
    seconds: float = DEFAULT_SECONDS


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def build_command(
    piece: Piece,
    workdir: Path,
    output: Path,
    *,
    font: str | None,
    music: Path | None,
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

    text_file = _write(workdir / "line.txt", piece.text)
    domain_file = _write(workdir / "domain.txt", piece.domain)
    brokerage_file = _write(workdir / "brokerage.txt", piece.brokerage_line)

    # The promise, held for the whole video. Centred and boxed because it sits
    # over landscape that changes four times underneath it.
    graph += (
        f"[joined]drawtext=textfile='{escape_path(str(text_file))}'"
        f"{font_clause}:fontcolor=white:fontsize={_TEXT_SIZE}"
        f":line_spacing=14:box=1:boxcolor=black@0.35:boxborderw={_BOX_PAD}"
        f":x=(w-text_w)/2:y=(h-text_h)/2[titled];"
    )

    # The identification, from BRAND_FROM_SECONDS to the end. The domain leads
    # and the brokerage follows: these videos exist to send people to the site,
    # so the line that says where to go cannot be the least legible thing in
    # the frame.
    graph += (
        f"[titled]drawtext=textfile='{escape_path(str(domain_file))}'"
        f"{font_clause}:fontcolor=white:fontsize={_DOMAIN_SIZE}"
        f":box=1:boxcolor=black@0.55:boxborderw=18"
        f":x=(w-text_w)/2:y=h*0.82"
        f":enable='gte(t,{BRAND_FROM_SECONDS:.2f})'[domained];"
        f"[domained]drawtext=textfile='{escape_path(str(brokerage_file))}'"
        f"{font_clause}:fontcolor=white:fontsize={_BROKERAGE_SIZE}"
        f":borderw=4:bordercolor=black@0.9"
        f":x=(w-text_w)/2:y=h*0.82+{_DOMAIN_SIZE + _BOX_PAD + 22}"
        f":enable='gte(t,{BRAND_FROM_SECONDS:.2f})'[out]"
    )

    argv = ["ffmpeg", "-y", "-v", "error", *inputs]
    maps = ["-map", "[out]"]
    if music is not None:
        argv += ["-i", str(music)]
        music_index = len(piece.clips)
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
    tolerance: float = 0.25,
) -> Path:
    """Build it, then measure it.

    The paragraph about `-t` in the module docstring is an intention. This is
    the part that makes it a fact: a video that came out a second short is a
    video missing its end card, and it must fail here rather than be published.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    argv = build_command(piece, workdir, output, font=font, music=music)
    done = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        raise Rejected(f"ffmpeg refused this piece: {done.stderr.strip()[:400]}")

    made = _duration(output)
    if abs(made - piece.seconds) > tolerance:
        raise Rejected(
            f"asked for {piece.seconds:.2f}s and got {made:.2f}s — the length "
            f"was derived from the inputs somewhere instead of declared"
        )
    return output

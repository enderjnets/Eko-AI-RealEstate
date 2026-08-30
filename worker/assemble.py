"""One ffmpeg command: a clip in, a publishable vertical video out.

Same shape as the renderer in the backend, and deliberately so — scale to fit
and pad with a blurred copy of the frame, never crop. The agent framed that
shot; a machine that crops it is a machine deciding what the video is about.
On top of that, three things a published piece must carry:

* **The captions**, timed to the voice (`subtitles.py`).
* **The brand mark**, top right, where it survives every platform's overlays.
* **The brokerage line and the domain**, burned into the last seconds. Colorado
  requires advertising to identify the brokerage, and burned pixels survive a
  re-encode, a crop and a muted playback — a caption does not. The domain rather
  than a handle because the domain is identical on all three platforms and
  nobody can take it.

The command is built by a pure function so a test can hold it — including the
text inside it — without running ffmpeg, and one test actually runs it.

**`textfile=`, never `text=`.** drawtext's option parser and the filtergraph
parser both have their own escaping, and a brokerage really is called things
like "Smith & Jones, Realty, Inc." Every round of escaping fixed the characters
somebody thought of. Reading the bytes from a file removes the language.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
END_CARD_SECONDS = 3.0
_FONT_SIZE_BROKERAGE = 48
_FONT_SIZE_DOMAIN = 40
_MARK_WIDTH = 190
_MARK_MARGIN = 44


def escape_path(path: str) -> str:
    """Escape a path used as a filter OPTION value.

    Our own temp paths contain none of these characters, which is exactly why
    this is here: "the path is safe" is the assumption that stops being true
    the first time a directory has a space or a colon in it.
    """
    return path.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def build_command(
    source: Path,
    destination: Path,
    *,
    duration: float,
    has_audio: bool,
    brokerage_file: Path,
    domain_file: Path,
    font: str | None,
    mark: Path | None = None,
    subtitles: Path | None = None,
    music: Path | None = None,
) -> list[str]:
    """The whole render, as argv."""
    font_clause = f":fontfile='{escape_path(str(font))}'" if font else ""
    start = max(0.0, duration - END_CARD_SECONDS)

    # Blurred fill behind, scaled video in front. `force_original_aspect_ratio`
    # on the foreground is what makes this a pad and not a crop.
    graph = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},gblur=sigma=20[bgb];"
        f"[fg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[base]"
    )
    last = "base"

    if subtitles is not None:
        graph += f";[{last}]ass='{escape_path(str(subtitles))}'[subbed]"
        last = "subbed"

    inputs: list[str] = ["-i", str(source)]
    if mark is not None:
        inputs += ["-i", str(mark)]
        graph += (
            f";[1:v]scale={_MARK_WIDTH}:-1[markscaled]"
            f";[{last}][markscaled]overlay="
            f"W-w-{_MARK_MARGIN}:{_MARK_MARGIN}[marked]"
        )
        last = "marked"

    # The identification, on screen for the last seconds.
    graph += (
        f";[{last}]drawtext=textfile='{escape_path(str(brokerage_file))}'"
        f"{font_clause}:fontcolor=white:fontsize={_FONT_SIZE_BROKERAGE}"
        f":box=1:boxcolor=black@0.55:boxborderw=26"
        f":x=(w-text_w)/2:y=h*0.60"
        f":enable='gte(t,{start:.2f})'[brokered]"
        f";[brokered]drawtext=textfile='{escape_path(str(domain_file))}'"
        f"{font_clause}:fontcolor=0xF5E6C8:fontsize={_FONT_SIZE_DOMAIN}"
        f":x=(w-text_w)/2:y=h*0.60+90"
        f":enable='gte(t,{start:.2f})'[out]"
    )

    music_index = None
    if music is not None and has_audio:
        music_index = len(inputs) // 2
        inputs += ["-i", str(music)]

    # ONE filter_complex, video and audio in the same graph. Emitting a second
    # one is not "adding the audio chain": ffmpeg keeps the LAST occurrence of
    # the option, so the video graph is silently dropped and the labels stop
    # meaning what they say. That version returned 0 and produced a six-second
    # video whose audio was two and a half seconds — a different length on
    # every run, because `[0:a]` was also consumed twice and the two consumers
    # raced. Narration cut off mid-sentence, all the way to a person's screen.
    if has_audio and music_index is not None:
        # Music under the voice, not over it: `sidechaincompress` ducks the bed
        # whenever somebody is speaking, where a fixed low volume either buries
        # the voice or is inaudible.
        #
        # `asplit` because a stream may be consumed ONCE. The voice is needed
        # twice — as the sidechain key and as the thing being mixed — and
        # naming `[0:a]` in both places is the race above.
        #
        # The voice goes FIRST into amix with `duration=first`, so the result
        # is as long as the narration: the bed is minutes long and would
        # otherwise pad the video out to its own length.
        graph += (
            f";[0:a]asplit=2[voice][key]"
            f";[{music_index}:a]volume=0.12[bed]"
            f";[bed][key]sidechaincompress=threshold=0.05:ratio=6[ducked]"
            f";[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )

    argv = ["ffmpeg", "-y", "-v", "error", *inputs]
    argv += ["-filter_complex", graph, "-map", "[out]"]

    if has_audio:
        argv += ["-map", "[aout]" if music_index is not None else "0:a"]
        argv += ["-c:a", "aac", "-b:a", "128k"]
    else:
        argv += ["-an"]

    argv += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(destination),
    ]
    return argv


def run(argv: list[str], timeout: int = 1800) -> None:
    """Run it, or raise with ffmpeg's own last words.

    stderr merged into stdout, because that is where ffmpeg writes them. The
    first version read `result.stdout` alone with `-v error` set, so every
    failure reported itself as `ffmpeg failed (1): ` — an empty reason, which
    is what a realtor eventually read on the piece after three attempts.
    """
    result = subprocess.run(
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout
    )
    if result.returncode != 0:
        tail = result.stdout[-600:].decode(errors="replace").strip()
        raise RuntimeError(
            f"ffmpeg failed ({result.returncode}): {tail or 'no output'}"
        )

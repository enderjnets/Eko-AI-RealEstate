"""The unnarrated shape: what it must contain, and how long it must last.

One of these runs ffmpeg for real. That is deliberate — the whole point of the
module is a length that is declared rather than derived, and a test that only
reads the argv would pass with `-shortest` in it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from worker import static_piece
from worker.static_piece import Piece

BROKERAGE = "Natalia & Robbie · Engel & Völkers Aspen"


def _piece(clips: list[Path], **kwargs) -> Piece:
    return Piece(
        clips=clips,
        text="12 places near Denver, sorted by elevation.\nThe ones above 9,500 ft go first.",
        domain="denverhomestory.com/fall",
        brokerage_line=BROKERAGE,
        **kwargs,
    )


def _clip(path: Path, seconds: float, colour: str) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={colour}:s=720x1280:d={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return path


# ── What the command says ────────────────────────────────────────────────


def test_the_length_is_declared_and_never_derived(tmp_path: Path) -> None:
    """`-shortest` answers "which track is shorter", which is a different
    question from "how long is this". It cost the narrated lane four words off
    the end of a script once; it does not get a second chance here."""
    argv = static_piece.build_command(
        _piece([tmp_path / "a.mp4", tmp_path / "b.mp4"]),
        tmp_path,
        tmp_path / "out.mp4",
        font=None,
        music=tmp_path / "bgm.mp3",
    )
    assert "-shortest" not in argv
    assert "-t" in argv
    assert argv[argv.index("-t") + 1] == f"{static_piece.DEFAULT_SECONDS:.3f}"
    # And the bed is padded to the video, not the video trimmed to the bed.
    graph = argv[argv.index("-filter_complex") + 1]
    assert "apad" in graph


def test_the_words_are_read_from_files_not_from_the_command(tmp_path: Path) -> None:
    """A brokerage is called things like "Smith & Jones, Realty, Inc.", and
    `text=` would put that through two escaping layers. The files carry the
    bytes; the command carries only paths."""
    argv = static_piece.build_command(
        _piece([tmp_path / "a.mp4"]), tmp_path, tmp_path / "o.mp4",
        font=None, music=None,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert "textfile=" in graph
    # `drawtext=` ends in the letters "text=", so a naive substring search
    # matches every filter in the graph and proves nothing. The option is what
    # matters, and an option is preceded by `=` or `:`.
    assert "drawtext=text=" not in graph
    assert ":text=" not in graph
    # The strongest form of the same claim: the words themselves are not in
    # the command at all, so no amount of punctuation in them can escape.
    assert BROKERAGE not in graph
    assert (tmp_path / "brokerage.txt").read_text(encoding="utf-8") == BROKERAGE


def test_the_brand_block_waits_and_the_promise_does_not(tmp_path: Path) -> None:
    """The line that makes someone stop is on screen from the first frame; the
    address arrives once they have. Both are in the same video, and the
    difference is `enable`."""
    argv = static_piece.build_command(
        _piece([tmp_path / "a.mp4"]), tmp_path, tmp_path / "o.mp4",
        font=None, music=None,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    held, gated = graph.split("[titled]", 1)
    assert "enable=" not in held.split("[joined]", 1)[1]
    assert graph.count(f"gte(t,{static_piece.BRAND_FROM_SECONDS:.2f})") == 2
    assert "domain.txt" in gated


def test_with_the_ask_in_the_text_the_address_is_not_drawn_twice(
    tmp_path: Path,
) -> None:
    """An empty `domain` means the held text already carries the ask.

    Showing an address is not asking for anything. The first cut of these
    pieces displayed `denverhomestory.com/fall` in small type at the bottom and
    nothing anywhere said what it was for — a viewer reading a headline about
    elevation has no reason to read that as an offer. The fix is to put the ask
    in the line that is on screen the whole time; repeating the address below
    it just gives the eye two places to go.

    The legal line still gets drawn. Colorado requires advertising to identify
    the brokerage, and that requirement does not depend on where the ask is.

    Mutation: draw the domain regardless of whether it is set → red.
    """
    piece = Piece(
        clips=[tmp_path / "a.mp4"],
        text="12 places near Denver, sorted by elevation.\nFree guide -> denverhomestory.com/fall",
        domain="",
        brokerage_line=BROKERAGE,
    )
    argv = static_piece.build_command(
        piece, tmp_path, tmp_path / "o.mp4", font=None, music=None
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert "domain.txt" not in graph
    assert "brokerage.txt" in graph
    # One gated overlay now, not two.
    assert graph.count(f"gte(t,{static_piece.BRAND_FROM_SECONDS:.2f})") == 1


def test_a_piece_with_no_clips_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no clips"):
        static_piece.build_command(
            _piece([]), tmp_path, tmp_path / "o.mp4", font=None, music=None
        )


# ── What the file actually is ────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_the_finished_file_is_the_length_that_was_asked_for(tmp_path: Path) -> None:
    """The clips are deliberately the WRONG length — 2s and 5s against a 4s
    piece. Under `-shortest`, or under any arithmetic that trusts the inputs,
    this comes out at something other than 4.0 and the assertion catches it.
    Equal-length clips would have made the test pass on a coincidence.
    """
    clips = [
        _clip(tmp_path / "one.mp4", 2.0, "red"),
        _clip(tmp_path / "two.mp4", 5.0, "green"),
    ]
    out = tmp_path / "piece.mp4"
    static_piece.render(
        _piece(clips, seconds=4.0), tmp_path / "work", out, font=None, music=None
    )
    assert out.exists() and out.stat().st_size > 0
    assert abs(static_piece._duration(out) - 4.0) <= 0.25


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_video_that_came_out_short_is_rejected_not_delivered(
    tmp_path: Path, monkeypatch
) -> None:
    """The measurement is the point. A render that quietly loses its end card
    is worse than one that fails, because only one of them gets watched.

    Mutation: delete the length check in `render` → this goes green with a
    video a second and a half short.
    """
    clips = [_clip(tmp_path / "one.mp4", 2.0, "blue")]
    monkeypatch.setattr(static_piece, "_duration", lambda _p: 2.5)
    with pytest.raises(static_piece.Rejected, match="declared"):
        static_piece.render(
            _piece(clips, seconds=4.0),
            tmp_path / "work",
            tmp_path / "piece.mp4",
            font=None,
            music=None,
        )

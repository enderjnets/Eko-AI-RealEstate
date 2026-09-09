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
    # By what each drawtext DRAWS, not by the label it writes to. The promise
    # used to be one overlay called `[titled]`; it is now one per line, and a
    # test that reached for that label went red on a change that was purely
    # about centring.
    draws = graph.split("drawtext=")[1:]
    promise = [d for d in draws if "line0.txt" in d or "line1.txt" in d]
    brand = [d for d in draws if "domain.txt" in d or "brokerage.txt" in d]
    assert len(promise) == 2, "one overlay per line of the promise"
    assert all("enable=" not in d for d in promise), "the promise never waits"
    assert len(brand) == 2
    assert all("enable=" in d for d in brand), "the brand block always waits"
    assert graph.count(f"gte(t,{static_piece.BRAND_FROM_SECONDS:.2f})") == 2


def test_every_line_of_the_promise_is_centred_on_its_own(tmp_path: Path) -> None:
    """Handed a multi-line textfile, drawtext centres the block and ranges the
    lines left inside it — so a short line above a long one reads as indented.

    Measured on F1: "12 places near Denver," sat visibly left of "The ones above
    9,500 ft go first." underneath it. The fix is one overlay per line, each
    with its own `x=(w-text_w)/2`, which is the only expression that can centre
    a line against its own width.

    Mutation: write the lines to a single textfile and draw them once → red,
    because there is then one overlay for two lines.
    """
    piece = _piece([tmp_path / "a.mp4"])
    argv = static_piece.build_command(
        piece, tmp_path, tmp_path / "o.mp4", font=None, music=None
    )
    graph = argv[argv.index("-filter_complex") + 1]
    lines = piece.text.split("\n")
    assert len(lines) == 2
    for index in range(len(lines)):
        assert (tmp_path / f"line{index}.txt").read_text(encoding="utf-8") == lines[index]
    # By the exact filename. Matching on `"line" in d` also matched the tmp_path
    # of this very test — pytest names the directory after the function — and
    # counted the brand overlays as lines of the promise.
    names = [f"line{index}.txt" for index in range(len(lines))]
    drawn = [
        d for d in graph.split("drawtext=")[1:]
        if any(name in d for name in names)
    ]
    assert len(drawn) == len(lines)
    assert all("x=(w-text_w)/2" in d for d in drawn)
    # No slab behind the words: the shadow carries legibility instead.
    assert all("box=1" not in d for d in drawn)


def test_the_ask_is_drawn_smaller_and_below_the_promise(tmp_path: Path) -> None:
    """The ask is a different size, not a different sentence, so it cannot ride
    in `text`: one voice says what this is, a quieter one says what to do.

    Mutation: draw the cta at `_TEXT_SIZE` → red. Mutation: draw it at the same
    `y` as the first line of the promise → red.
    """
    piece = _piece([tmp_path / "a.mp4"], cta="Comment FALL for the guide")
    argv = static_piece.build_command(
        piece, tmp_path, tmp_path / "o.mp4", font=None, music=None
    )
    graph = argv[argv.index("-filter_complex") + 1]
    ask = [d for d in graph.split("drawtext=")[1:] if "cta0.txt" in d]
    assert len(ask) == 1
    assert f"fontsize={static_piece._CTA_SIZE}" in ask[0]
    assert static_piece._CTA_SIZE < static_piece._TEXT_SIZE
    # Below every line of the promise, not level with the first one.
    offset = len(piece.text.split("\n")) * (
        static_piece._TEXT_SIZE + static_piece._LINE_SPACING
    ) + static_piece._CTA_GAP
    assert f"y=h*{static_piece._TEXT_TOP}+{offset}" in ask[0]
    assert "enable=" not in ask[0], "the ask is on screen as long as the promise"


def test_without_an_ask_nothing_is_drawn_for_it(tmp_path: Path) -> None:
    """`cta` defaults to empty, and empty means no overlay at all — not an
    overlay of nothing, which would still cost a pass and could still shift the
    layout underneath it."""
    argv = static_piece.build_command(
        _piece([tmp_path / "a.mp4"]), tmp_path, tmp_path / "o.mp4",
        font=None, music=None,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert "cta0.txt" not in graph
    assert not (tmp_path / "cta0.txt").exists()


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


def test_a_two_line_ask_is_centred_line_by_line_too(tmp_path: Path) -> None:
    """Six of the eighteen autumn pieces ask for a share, and that ask is two
    lines: what to do, then where it leads.

    Drawn as one overlay it would range left inside its own block — the exact
    fault the promise was fixed for, reappearing in the half of the frame nobody
    was looking at. Both go through the same helper so neither can regress alone.

    Mutation: draw the cta as a single overlay → red.
    """
    piece = _piece(
        [tmp_path / "a.mp4"],
        cta="Send this to whoever you'd go with\ndenverhomestory.com/fall/2",
    )
    argv = static_piece.build_command(
        piece, tmp_path, tmp_path / "o.mp4", font=None, music=None
    )
    graph = argv[argv.index("-filter_complex") + 1]
    ask = [
        d for d in graph.split("drawtext=")[1:]
        if "cta0.txt" in d or "cta1.txt" in d
    ]
    assert len(ask) == 2, "one overlay per line of the ask"
    assert all("x=(w-text_w)/2" in d for d in ask)
    assert (tmp_path / "cta1.txt").read_text(encoding="utf-8") == (
        "denverhomestory.com/fall/2"
    )

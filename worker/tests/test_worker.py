"""The worker's own tests: no network, no panel, one real ffmpeg run.

What is worth holding here is narrow and specific:

* The **hour window** is honoured, because the whole agreement with the other
  projects on that machine rests on it.
* The command **pads and never crops**, because the agent framed the shot.
* The **brand check looks at pixels**, because a render can run happily and
  composite the wrong image — which is exactly what shipped next door.
* Captions are **grouped for a phone**, not dumped word by word.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from worker import assemble, config, subtitles, verify
from worker.main import pick_music, within_hours

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# ── The hour window ──────────────────────────────────────────────────────


def test_the_worker_stays_out_of_hours_it_was_not_given() -> None:
    """The machine is shared. This is the whole agreement."""
    hours = frozenset({15, 16, 17})
    assert within_hours(hours, datetime(2026, 8, 30, 16, 30))
    assert not within_hours(hours, datetime(2026, 8, 30, 8, 0))
    assert not within_hours(hours, datetime(2026, 8, 30, 20, 59))


def test_no_hours_configured_means_any_hour() -> None:
    """An operator debugging by hand should not need today's schedule. The
    service file always sets them."""
    assert within_hours(frozenset(), datetime(2026, 8, 30, 4, 0))


def test_the_hour_list_survives_a_sloppy_env_var() -> None:
    parsed = config._hours(" 13, 15 ,,16, notanhour, 99 ")
    assert parsed == frozenset({13, 15, 16})


def test_a_worker_with_no_panel_refuses_to_start() -> None:
    cfg = config.Config(
        api_base="", token="", name="x", hours=frozenset(),
        workdir=Path("/tmp"), poll_seconds=60,
    )
    assert cfg.configured is not None


# ── The command ──────────────────────────────────────────────────────────


def _command(tmp_path: Path, **kwargs) -> list[str]:
    brokerage = tmp_path / "b.txt"
    brokerage.write_text("Engel & Völkers Aspen")
    domain = tmp_path / "d.txt"
    domain.write_text("denverhomestory.com")
    return assemble.build_command(
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        duration=kwargs.pop("duration", 20.0),
        has_audio=kwargs.pop("has_audio", True),
        brokerage_file=brokerage,
        domain_file=domain,
        font=None,
        **kwargs,
    )


def test_the_video_is_padded_never_cropped(tmp_path: Path) -> None:
    """The agent framed that shot. A machine that crops it is deciding what
    the video is about."""
    graph = " ".join(_command(tmp_path))
    assert "force_original_aspect_ratio=decrease" in graph
    assert "gblur" in graph


def test_the_brokerage_text_is_read_from_a_file_not_inlined(tmp_path: Path) -> None:
    """drawtext's `text=` is two nested escaping languages, and a brokerage is
    really called "Smith & Jones, Realty, Inc."."""
    graph = " ".join(_command(tmp_path))
    assert "textfile=" in graph
    assert "Engel" not in graph


def test_the_identification_is_on_screen_at_the_end(tmp_path: Path) -> None:
    graph = " ".join(_command(tmp_path, duration=30.0))
    # 30s clip, 3s end card.
    assert "gte(t,27.00)" in graph
    assert "denverhomestory.com" not in graph  # it too comes from a file


def test_a_silent_clip_produces_no_audio_track(tmp_path: Path) -> None:
    argv = _command(tmp_path, has_audio=False)
    assert "-an" in argv
    assert "-c:a" not in argv


def test_music_is_ducked_under_the_voice_rather_than_mixed_flat(
    tmp_path: Path,
) -> None:
    music = tmp_path / "bed.mp3"
    music.write_bytes(b"")
    graph = " ".join(_command(tmp_path, music=music))
    assert "sidechaincompress" in graph


def test_music_is_skipped_on_a_silent_clip(tmp_path: Path) -> None:
    """Ducking needs a voice to duck under. Without one the bed would simply
    become the soundtrack at 12% volume, which is nobody's intention."""
    music = tmp_path / "bed.mp3"
    music.write_bytes(b"")
    graph = " ".join(_command(tmp_path, music=music, has_audio=False))
    assert "sidechaincompress" not in graph


# ── Captions ─────────────────────────────────────────────────────────────


def test_words_are_grouped_into_readable_lines() -> None:
    words = [subtitles.Word(i * 0.4, i * 0.4 + 0.3, f"w{i}") for i in range(9)]
    lines = subtitles.group(words, per_line=4)
    assert [len(line.text.split()) for line in lines] == [4, 4, 1]


def test_a_pause_starts_a_new_line() -> None:
    """A caption that runs across a silence is out of sync with the speaker."""
    words = [
        subtitles.Word(0.0, 0.3, "one"),
        subtitles.Word(0.3, 0.6, "two"),
        subtitles.Word(5.0, 5.3, "later"),
    ]
    lines = subtitles.group(words, per_line=4, max_gap=0.8)
    assert [line.text for line in lines] == ["one two", "later"]


def test_captions_sit_above_the_platform_furniture() -> None:
    """TikTok and Reels put their own caption and buttons over the bottom of
    the frame; text placed there is text nobody reads."""
    ass = subtitles.build_ass([subtitles.Word(0.0, 1.0, "hello")])
    assert f",{subtitles._MARGIN_V},1" in ass


def test_braces_in_a_caption_cannot_become_ass_markup() -> None:
    ass = subtitles.build_ass([subtitles.Word(0.0, 1.0, "{\\an8}not an override")])
    assert "{\\an8}" not in ass


def test_no_speech_means_no_subtitle_file(tmp_path: Path) -> None:
    """A clip with no words gets a video without captions, not a broken one."""
    assert subtitles.write_ass([], tmp_path / "c.ass") is None


# ── The real thing ───────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_a_real_render_is_vertical_and_carries_the_mark(tmp_path: Path) -> None:
    """One end-to-end run. Everything above holds the shape of the command;
    this holds the shape of the file that comes out of it."""
    source = tmp_path / "in.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=25:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(source),
        ],
        check=True,
        capture_output=True,
    )

    # A mark with structure in it, so the correlation is measuring recognition
    # rather than agreeing with noise. A flat colour has no variance and
    # cannot be correlated with anything — `verify` says so by name.
    mark = tmp_path / "mark.png"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=190x190:duration=1",
            "-frames:v", "1", str(mark),
        ],
        check=True,
        capture_output=True,
    )

    brokerage = tmp_path / "b.txt"
    brokerage.write_text("Engel & Völkers Aspen", encoding="utf-8")
    domain = tmp_path / "d.txt"
    domain.write_text("denverhomestory.com", encoding="utf-8")
    out = tmp_path / "out.mp4"

    assemble.run(
        assemble.build_command(
            source, out,
            duration=4.0,
            has_audio=True,
            brokerage_file=brokerage,
            domain_file=domain,
            font=None,
            mark=mark,
        )
    )

    probe = verify.check(out, expect_audio=True)
    assert (probe.width, probe.height) == (1080, 1920)
    assert probe.has_audio

    pytest.importorskip("PIL")
    correlation = verify.brand_is_present(out, mark, tmp_path)
    assert correlation >= 0.15


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_a_video_of_the_wrong_size_is_rejected(tmp_path: Path) -> None:
    """The check has to be able to fail, or it is decoration."""
    wrong = tmp_path / "wrong.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x480:rate=25:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(wrong),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(verify.Rejected, match="640x480"):
        verify.check(wrong, expect_audio=False)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_a_video_with_content_but_no_mark_fails_the_brand_check(tmp_path: Path) -> None:
    """The other half of the same instrument: it must say no when the mark is
    absent, or its yes means nothing.

    The frame has real content — a blank one would be caught by a cruder check
    and would not exercise the correlation at all.
    """
    pytest.importorskip("PIL")
    unmarked = tmp_path / "unmarked.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "smptebars=size=1080x1920:rate=25:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(unmarked),
        ],
        check=True,
        capture_output=True,
    )
    mark = tmp_path / "mark.png"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=190x190:duration=1",
            "-frames:v", "1", str(mark),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(verify.Rejected, match="mark"):
        verify.brand_is_present(unmarked, mark, tmp_path)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_a_blank_corner_is_named_as_such(tmp_path: Path) -> None:
    """Distinguished from a low score on purpose: "nothing was drawn there" and
    "something was drawn and it is not ours" send an operator to different
    places."""
    pytest.importorskip("PIL")
    plain = tmp_path / "plain.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:size=1080x1920:rate=25:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(plain),
        ],
        check=True,
        capture_output=True,
    )
    mark = tmp_path / "mark.png"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=190x190:duration=1",
            "-frames:v", "1", str(mark),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(verify.Rejected, match="blank"):
        verify.brand_is_present(plain, mark, tmp_path)


def test_no_music_directory_is_not_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An agency that has not chosen music gets a video without music."""
    monkeypatch.setattr("worker.main.MUSIC_DIR", tmp_path / "nope")
    assert pick_music() is None

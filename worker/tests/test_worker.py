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


def test_the_domain_leads_and_the_brokerage_follows(tmp_path: Path) -> None:
    """The address people are meant to visit is the loudest thing in the frame.

    It was the other way round: the legal line sat in a black box at 48 while
    the domain was cream at 40 with no box, washing out over any bright
    photograph. These videos exist to send traffic to the site.

    The clauses are found by the name of the FILE each one reads, because the
    text itself is deliberately not in the graph — see the test above. The
    sizes are read from the module so this fixes the ordering, not a number.
    """
    graph = " ".join(_command(tmp_path))
    clauses = graph.split("drawtext=")
    domain = next(c for c in clauses if "d.txt" in c)
    brokerage = next(c for c in clauses if "b.txt" in c)

    assert assemble._FONT_SIZE_DOMAIN > assemble._FONT_SIZE_BROKERAGE
    assert f"fontsize={assemble._FONT_SIZE_DOMAIN}" in domain
    assert f"fontsize={assemble._FONT_SIZE_BROKERAGE}" in brokerage
    # One box, on the domain. Two stacked boxes weigh more than the picture.
    assert "box=1" in domain
    assert "box=1" not in brokerage
    # The brokerage keeps its legibility with an outline instead.
    assert "borderw=" in brokerage
    # Both still appear only over the end card, and the chain still ends where
    # the encoder is told to look.
    assert graph.count("enable='gte(t,") == 2
    assert "[out]" in graph


def test_the_brokerage_stays_legible_however_small_it_gets(tmp_path: Path) -> None:
    """Colorado requires advertising to IDENTIFY the brokerage. It does not
    require it to dominate — but below about 32px on a 1080-wide frame that
    stops being identification and becomes a formality nobody can read."""
    assert assemble._FONT_SIZE_BROKERAGE >= 32


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


# Whisper's tokens carry their OWN leading space — " Homes", " $612" — while a
# fragment that continues the previous word carries none, like ",000" or
# "-minute". The grouper reads exactly that to decide where a line may break,
# so a fixture built from bare strings would be testing a shape that never
# arrives.
def _spoken(*texts: str, step: float = 0.4) -> list[subtitles.Word]:
    return [
        subtitles.Word(i * step, i * step + step * 0.75, t)
        for i, t in enumerate(texts)
    ]


def test_words_are_grouped_into_readable_lines() -> None:
    words = _spoken(*[f" w{i}" for i in range(9)])
    lines = subtitles.group(words, per_line=4)
    assert [len(line.text.split()) for line in lines] == [4, 4, 1]


def test_a_pause_starts_a_new_line() -> None:
    """A caption that runs across a silence is out of sync with the speaker."""
    words = [
        subtitles.Word(0.0, 0.3, " one"),
        subtitles.Word(0.3, 0.6, " two"),
        subtitles.Word(5.0, 5.3, " later"),
    ]
    lines = subtitles.group(words, per_line=4, max_gap=0.8)
    assert [line.text for line in lines] == ["one two", "later"]


def test_a_price_is_never_split_across_two_captions() -> None:
    """The bug this shape exists for, held as a test.

    Whisper hands back "$680" and ",000" as separate tokens, and the second
    carries no leading space because it continues the first. Breaking there
    put "not the $680" on one caption and ",000 people were asking" on the
    next — on a channel whose entire subject is the price.
    """
    words = _spoken(" not", " the", " $680", ",000", " people", " were")
    lines = subtitles.group(words, per_line=4)
    assert all("$680,000" in line.text or "$680" not in line.text for line in lines)
    assert any("$680,000" in line.text for line in lines), [line.text for line in lines]


def test_captions_sit_above_the_platform_furniture() -> None:
    """TikTok and Reels put their own caption and buttons over the bottom of
    the frame; text placed there is text nobody reads."""
    ass = subtitles.build_ass([subtitles.Line([subtitles.Word(0.0, 1.0, "hello")])])
    assert f",{subtitles._MARGIN_V},1" in ass


def test_braces_in_a_caption_cannot_become_ass_markup() -> None:
    ass = subtitles.build_ass(
        [subtitles.Line([subtitles.Word(0.0, 1.0, "{\\an8}not an override")])]
    )
    assert "{\\an8}" not in ass


def test_the_captions_are_yellow_and_not_white() -> None:
    """White captions vanish over a bright photograph, which is most of them.

    The style row is checked rather than the look, because the look is checked
    by a person; this holds the value so a later edit cannot quietly return it
    to the default.
    """
    ass = subtitles.build_ass([subtitles.Line(_spoken(" one", " two"))])
    style = next(row for row in ass.splitlines() if row.startswith("Style: Caption"))
    assert subtitles._YELLOW in style
    assert "&H00FFFFFF" not in style


def test_the_spoken_word_is_the_one_that_grows() -> None:
    """The effect, held as a fact: at any instant exactly one word is enlarged,
    and it is the word whose turn it is to be said."""
    words = _spoken(" alpha", " bravo", " charlie")
    ass = subtitles.build_ass([subtitles.Line(words)])
    rows = [r for r in ass.splitlines() if r.startswith("Dialogue:")]
    assert len(rows) == 3, rows
    for index, row in enumerate(rows):
        assert row.count(f"\\fscx{subtitles._HIGHLIGHT}") == 1, row
        # The enlarged run opens immediately before the word of that turn.
        _, _, tail = row.partition(f"\\fscx{subtitles._HIGHLIGHT}")
        assert tail.split("}", 1)[1].startswith(words[index].text.strip()), row


def test_a_caption_does_not_blink_out_between_two_words() -> None:
    """Each word is held until the next one starts. Ending on the word's own
    end leaves a hole for every pause inside a phrase, which reads as a
    stutter rather than as speech."""
    words = [
        subtitles.Word(0.0, 0.3, " one"),
        subtitles.Word(0.7, 1.0, " two"),
    ]
    ass = subtitles.build_ass([subtitles.Line(words)])
    first = next(r for r in ass.splitlines() if r.startswith("Dialogue:"))
    assert "0:00:00.00,0:00:00.70" in first, first


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


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_music_does_not_cut_the_narration_short(tmp_path: Path) -> None:
    """The test that was missing, and the bug it would have caught.

    The earlier command emitted a SECOND `-filter_complex` for the audio.
    ffmpeg keeps the last occurrence, so the video graph was silently dropped
    and `[0:a]` was consumed twice by a chain that then raced with itself:
    returncode 0, a six-second video, and audio of 2.5 / 3.5 / 3.0 seconds on
    successive runs of the same command. Narration cut off mid-sentence, in
    front of a person, with every gate green.

    Asserting on the substring "sidechaincompress" — which is what the only
    music test did — cannot see any of that. This renders the thing and
    measures the file.
    """
    source = tmp_path / "in.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=25:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(source),
        ],
        check=True,
        capture_output=True,
    )
    # A bed far longer than the voice, which is what a real music track is.
    music = tmp_path / "bed.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=200:duration=25", str(music),
        ],
        check=True,
        capture_output=True,
    )

    brokerage = tmp_path / "b.txt"
    brokerage.write_text("Engel & Völkers Aspen", encoding="utf-8")
    domain = tmp_path / "d.txt"
    domain.write_text("denverhomestory.com", encoding="utf-8")
    out = tmp_path / "out.mp4"

    argv = assemble.build_command(
        source, out,
        duration=6.0,
        has_audio=True,
        brokerage_file=brokerage,
        domain_file=domain,
        font=None,
        music=music,
    )
    # One graph. Two is not "adding the audio chain", it is replacing the
    # video one.
    assert argv.count("-filter_complex") == 1
    assemble.run(argv)

    probe = verify.probe(out)
    assert (probe.width, probe.height) == (1080, 1920)
    assert probe.has_audio
    # The audio lasts as long as the video, not a third of it — and the bed
    # does not stretch the video out to its own twenty-five seconds either.
    assert abs(probe.duration - 6.0) < 0.5, f"video is {probe.duration:.2f}s"
    audio = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=duration", "-of", "csv=p=0", str(out),
        ],
        capture_output=True,
        check=True,
    ).stdout.decode().strip()
    assert abs(float(audio) - 6.0) < 0.5, f"narration is {audio}s of a 6s video"


def test_no_music_directory_is_not_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An agency that has not chosen music gets a video without music."""
    monkeypatch.setattr("worker.main.MUSIC_DIR", tmp_path / "nope")
    assert pick_music() is None


# ── The shipped brand asset ──────────────────────────────────────────────


def test_the_brand_mark_ships_and_is_usable() -> None:
    """The asset itself, not a synthetic stand-in.

    Everything above proves the machinery composites *a* mark. This proves the
    one that will actually be on a client's video exists, has a transparent
    ground (a navy rectangle pasted over somebody's living room is not a
    watermark), and carries enough variation to be recognised — a flat image
    cannot be correlated with anything and `verify` says so by name.

    It carries no text on purpose: the emblem only. The wordmark in the source
    logo has a superscript R, and there is no USPTO registration behind it —
    using that symbol without one is a false marking, so the part of the logo
    that claims it never reaches a video.
    """
    from worker.main import MARK

    assert MARK.is_file(), f"the brand mark is missing from {MARK}"
    pytest.importorskip("PIL")
    from PIL import Image

    mark = Image.open(MARK).convert("RGBA")
    assert mark.width >= 380, "too small to scale down to 190px cleanly"

    pixels = list(mark.getdata())
    transparent = sum(1 for p in pixels if p[3] == 0)
    assert transparent > len(pixels) * 0.2, "the mark has no transparent ground"

    grey = [(p[0] + p[1] + p[2]) / 3 for p in pixels if p[3] > 200]
    assert grey, "the mark is entirely transparent"
    mean = sum(grey) / len(grey)
    variance = sum((g - mean) ** 2 for g in grey) / len(grey)
    assert variance > 100, "the mark is a flat colour and cannot be recognised"


def test_a_long_line_is_broken_before_it_runs_off_the_frame() -> None:
    """Four words is not a width.

    "certain features, certain neighborhoods." is four words and, measured on
    the render machine's own font at this size, rendered 1080 px wide inside a
    1080 px frame — a word hanging off each edge. Word count says where a line
    MAY break; the character budget says where it must.
    """
    words = _spoken(" certain", " features", ",", " certain", " neighborhoods", ".")
    lines = subtitles.group(words, per_line=4)
    assert len(lines) > 1, [line.text for line in lines]
    assert all(len(line.text) <= subtitles._MAX_CHARS + 6 for line in lines), [
        line.text for line in lines
    ]
    # And the rule that outranks it survives: a continuation never starts a line.
    assert not any(line.text.startswith((",", ".")) for line in lines)


# ── Room to work ─────────────────────────────────────────────────────────


def test_a_squeezed_machine_does_not_get_a_render(monkeypatch) -> None:
    """15 GB, three projects. On 2026-09-02 a local client asked Ollama for a
    9 GB model and the OOM killer took the neighbouring project's renderer
    three times in eight minutes. A job killed halfway has already paid for its
    narration, and the retry pays again."""
    from worker import main as worker_main

    monkeypatch.setattr(worker_main, "available_memory_gb", lambda: 0.9)
    assert not worker_main.enough_memory(1.5)
    monkeypatch.setattr(worker_main, "available_memory_gb", lambda: 11.8)
    assert worker_main.enough_memory(1.5)
    # And the floor is not so high that a machine which could host us is
    # refused: with the 9 GB model resident there is still room to work.
    monkeypatch.setattr(worker_main, "available_memory_gb", lambda: 3.4)
    assert worker_main.enough_memory(1.5)


def test_a_machine_that_cannot_be_measured_still_renders(monkeypatch) -> None:
    """No /proc/meminfo — a Mac, a container without it. A worker that refuses
    to run when it cannot measure is a worker that never runs."""
    from worker import main as worker_main

    monkeypatch.setattr(worker_main, "available_memory_gb", lambda: None)
    assert worker_main.enough_memory(99.0)

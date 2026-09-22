"""The deterministic DHS layer applied after the visual engine returns."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from worker import finish, verify


def _spec(*, words: int = 60, scenes: int = 8, calculated: bool = False) -> dict:
    prompts = [
        {
            "visual_prompt": f"Denver home exterior angle {i} with no readable text",
            "on_screen_text": f"Denver step {i}",
        }
        for i in range(scenes)
    ]
    return {
        "script": " ".join(["Denver"] * words),
        "brokerage_line": "Engel & Völkers Aspen",
        "scenes": {"narration": " ".join(["Denver"] * words), "scenes": prompts},
        "finish": {
            "opening_text": "Run the Denver numbers",
            "cta_label": "RUN YOUR NUMBERS" if calculated else "EXPLORE DENVER HOME STORY",
            "cta_display": (
                "denverhomestory.com/calculator"
                if calculated
                else "denverhomestory.com"
            ),
            "calculator_url": (
                "https://www.denverhomestory.com/calculator?rent=3500&savings=60000"
                if calculated
                else None
            ),
        },
    }


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        (_spec(words=76), "75 words"),
        (_spec(scenes=6), "7 to 9"),
        (_spec(scenes=10), "7 to 9"),
        (_spec(calculated=True), "placeholder"),
    ],
)
def test_preflight_refuses_an_output_that_cannot_meet_the_contract(
    spec: dict, reason: str,
) -> None:
    if reason == "placeholder":
        spec["finish"]["calculator_url"] = None
        reason = "seeded calculator"
    with pytest.raises(verify.Rejected, match=reason):
        finish.validate(spec)


def test_preflight_refuses_repeated_visual_prompts() -> None:
    spec = _spec()
    spec["scenes"]["scenes"][3]["visual_prompt"] = spec["scenes"]["scenes"][0][
        "visual_prompt"
    ].upper()
    with pytest.raises(verify.Rejected, match="repeat"):
        finish.validate(spec)


def test_ffmpeg_reads_every_piece_of_copy_from_a_file(tmp_path: Path) -> None:
    files = {}
    for name in ("opening", "label", "display", "brokerage"):
        path = tmp_path / f"{name}.txt"
        path.write_text("danger: text='must never enter the filter'", encoding="utf-8")
        files[name] = path
    cmd = finish.build_command(
        tmp_path / "source.mp4",
        tmp_path / "out.mp4",
        duration=24.0,
        background=tmp_path / "card.png",
        opening_file=files["opening"],
        cta_label_file=files["label"],
        cta_display_file=files["display"],
        brokerage_file=files["brokerage"],
        font=None,
        mark=None,
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "danger:" not in graph
    assert "must never" not in graph
    assert graph.count("textfile=") == 4


HAS_MEDIA_TOOLS = all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe"))


def _source(path: Path, seconds: int = 22) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=0x78909c:s=1080x1920:r=8:d={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(not HAS_MEDIA_TOOLS, reason="ffmpeg/ffprobe not on PATH")
def test_real_finish_builds_a_vertical_branded_fallback_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    _source(source)
    monkeypatch.setattr(verify, "reject_readable_digits", lambda *a, **k: [])
    destination = tmp_path / "finished.mp4"

    report = finish.apply(
        source,
        destination,
        spec=_spec(),
        mark=Path(__file__).parents[1] / "assets" / "dhs-mark.png",
        font=None,
    )

    probe = verify.check(
        destination, expect_audio=True, min_seconds=20, max_seconds=35
    )
    assert (probe.width, probe.height) == (1080, 1920)
    assert report.used_calculator is False
    assert report.duration == pytest.approx(probe.duration, abs=0.1)


@pytest.mark.skipif(not HAS_MEDIA_TOOLS, reason="ffmpeg/ffprobe not on PATH")
def test_real_finish_uses_an_authorized_calculator_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    _source(source)
    monkeypatch.setattr(verify, "reject_readable_digits", lambda *a, **k: [])

    def fake_capture(url: str, destination: Path) -> bool:
        assert finish.authorized_calculator_url(url)
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "color=c=0xd4a953:s=1080x1920", "-frames:v", "1", str(destination),
            ],
            check=True,
            capture_output=True,
        )
        return True

    monkeypatch.setattr(finish, "capture_calculator", fake_capture)
    report = finish.apply(
        source,
        tmp_path / "finished.mp4",
        spec=_spec(calculated=True),
        mark=Path(__file__).parents[1] / "assets" / "dhs-mark.png",
        font=None,
    )
    assert report.used_calculator is True


HAS_OCR = HAS_MEDIA_TOOLS and shutil.which("tesseract") is not None


@pytest.mark.skipif(not HAS_OCR, reason="tesseract not on PATH")
def test_ocr_refuses_a_central_address_number(tmp_path: Path) -> None:
    video = tmp_path / "number.mp4"
    font = finish.default_font()
    if font is None:
        pytest.skip("no font available for the OCR fixture")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=white:s=1080x1920:r=4:d=7", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=7", "-vf",
            (
                f"drawtext=fontfile='{font}':text='19239':fontcolor=black:"
                "fontsize=180:x=(w-text_w)/2:y=650"
            ),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(video),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(verify.Rejected, match="19239"):
        verify.reject_readable_digits(video, tmp_path / "ocr", before_seconds=4.0)


@pytest.mark.skipif(not HAS_OCR, reason="tesseract not on PATH")
def test_ocr_ignores_platform_caption_region(tmp_path: Path) -> None:
    video = tmp_path / "caption-number.mp4"
    font = finish.default_font()
    if font is None:
        pytest.skip("no font available for the OCR fixture")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=white:s=1080x1920:r=4:d=7", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=7", "-vf",
            (
                f"drawtext=fontfile='{font}':text='71000':fontcolor=black:"
                "fontsize=150:x=(w-text_w)/2:y=1600"
            ),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(video),
        ],
        check=True,
        capture_output=True,
    )
    assert verify.reject_readable_digits(
        video, tmp_path / "ocr", before_seconds=4.0
    ) == []

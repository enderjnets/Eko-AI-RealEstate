"""Deterministic Denver Home Story finishing after BitTrader returns an MP4."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from worker import verify

MIN_SECONDS = 20.0
MAX_SECONDS = 35.0
END_CARD_SECONDS = 3.0
OPENING_SECONDS = 2.8
MAX_NARRATION_WORDS = 75
MIN_SCENES = 7
MAX_SCENES = 9

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_CHROMIUM_CANDIDATES = (
    "/snap/bin/chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


@dataclass(frozen=True)
class FinishReport:
    duration: float
    used_calculator: bool


def default_font() -> str | None:
    return next((candidate for candidate in _FONT_CANDIDATES if Path(candidate).is_file()), None)


def _normalized_prompt(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def authorized_calculator_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "denverhomestory.com", "www.denverhomestory.com"
    }:
        return False
    if parsed.path.rstrip("/") != "/calculator":
        return False
    query = parse_qs(parsed.query)
    return bool(query.get("rent", [""])[0] and query.get("savings", [""])[0])


def validate(spec: dict) -> None:
    """Refuse jobs whose stored plan cannot produce the approved format."""
    finish = spec.get("finish") if isinstance(spec.get("finish"), dict) else {}
    required = ("opening_text", "cta_label", "cta_display")
    missing = [name for name in required if not str(finish.get(name) or "").strip()]
    if missing:
        raise verify.Rejected("finishing text is missing: " + ", ".join(missing))
    if not str(spec.get("brokerage_line") or "").strip():
        raise verify.Rejected("the organisation has no brokerage line on record")

    plan = spec.get("scenes") if isinstance(spec.get("scenes"), dict) else {}
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    if not MIN_SCENES <= len(scenes) <= MAX_SCENES:
        raise verify.Rejected(
            f"the shot plan has {len(scenes)} scenes; it requires 7 to 9"
        )
    prompts = [
        _normalized_prompt(row.get("visual_prompt"))
        for row in scenes
        if isinstance(row, dict)
    ]
    if len(prompts) != len(scenes) or any(not prompt for prompt in prompts):
        raise verify.Rejected("every scene needs a visual prompt")
    if len(set(prompts)) != len(prompts):
        raise verify.Rejected("the shot plan repeats a visual prompt")

    narration = str(plan.get("narration") or spec.get("script") or "")
    word_count = len(narration.split())
    if word_count > MAX_NARRATION_WORDS:
        raise verify.Rejected(
            f"the finished narration is {word_count} words; the limit is 75 words"
        )
    if finish.get("cta_label") == "RUN YOUR NUMBERS" and not authorized_calculator_url(
        finish.get("calculator_url")
    ):
        raise verify.Rejected("a calculated piece needs a seeded calculator URL")


def escape_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def build_command(
    source: Path,
    destination: Path,
    *,
    duration: float,
    background: Path,
    opening_file: Path,
    cta_label_file: Path,
    cta_display_file: Path,
    brokerage_file: Path,
    font: str | None,
    mark: Path | None,
) -> list[str]:
    """Build ffmpeg argv; all audience-facing copy enters through text files."""
    font_clause = f":fontfile='{escape_path(font)}'" if font else ""
    end_at = max(0.0, duration - END_CARD_SECONDS)
    graph = (
        "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,format=rgba,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x0B1F33@0.78:t=fill[card0];"
        f"[card0]drawtext=textfile='{escape_path(str(cta_label_file))}'"
        f"{font_clause}:fontcolor=0xD4A953:fontsize=42:x=(w-text_w)/2:y=700[card1];"
        f"[card1]drawtext=textfile='{escape_path(str(cta_display_file))}'"
        f"{font_clause}:fontcolor=white:fontsize=66:x=(w-text_w)/2:y=790[card2];"
        f"[card2]drawtext=textfile='{escape_path(str(brokerage_file))}'"
        f"{font_clause}:fontcolor=white:fontsize=32:borderw=2:bordercolor=black@0.8:"
        "x=(w-text_w)/2:y=930[endcard];"
        "[0:v]drawbox=x=70:y=210:w=940:h=300:color=0x0B1F33@0.88:t=fill:"
        f"enable='between(t,0,{OPENING_SECONDS:.1f})'[open0];"
        f"[open0]drawtext=textfile='{escape_path(str(opening_file))}'"
        f"{font_clause}:fontcolor=white:fontsize=68:line_spacing=14:"
        "x=(w-text_w)/2:y=285:"
        f"enable='between(t,0,{OPENING_SECONDS:.1f})'[opened];"
        f"[opened][endcard]overlay=0:0:enable='gte(t,{end_at:.2f})'[carded]"
    )
    inputs = ["-i", str(source), "-loop", "1", "-i", str(background)]
    last = "carded"
    if mark is not None:
        inputs += ["-loop", "1", "-i", str(mark)]
        graph += (
            ";[2:v]scale=190:-1[mark];"
            f"[{last}][mark]overlay=W-w-44:44:eof_action=repeat[out]"
        )
        last = "out"
    return [
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", f"{duration:.3f}",
        "-movflags", "+faststart", str(destination),
    ]


def capture_calculator(url: str, destination: Path) -> bool:
    """Capture only the DHS calculator. Any browser failure selects fallback."""
    if not authorized_calculator_url(url):
        return False
    browser = next(
        (candidate for candidate in _CHROMIUM_CANDIDATES if Path(candidate).is_file()),
        shutil.which("chromium") or shutil.which("chromium-browser"),
    )
    if not browser:
        return False
    try:
        result = subprocess.run(
            [
                str(browser), "--headless", "--disable-gpu", "--no-sandbox",
                "--hide-scrollbars", "--window-size=1080,1920",
                "--virtual-time-budget=8000", f"--screenshot={destination}", url,
            ],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        # The calculator is an enhancement, not a reason to lose an otherwise
        # valid render. Chromium can hang behind Snap even when the executable
        # exists; remove any partial image and let the caller draw the branded
        # fallback card promised by the worker contract.
        destination.unlink(missing_ok=True)
        return False
    return result.returncode == 0 and destination.is_file() and destination.stat().st_size > 0


def _fallback_card(destination: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        raise verify.Rejected("cannot build the DHS fallback card: Pillow is not installed") from None
    Image.new("RGB", (1080, 1920), "#0B1F33").save(destination)


def _write_text(path: Path, value: object) -> None:
    text = str(value or "").strip()
    if not text:
        raise verify.Rejected(f"the final-card text file {path.name} would be empty")
    path.write_text(text, encoding="utf-8")


def apply(
    source: Path,
    destination: Path,
    *,
    spec: dict,
    mark: Path,
    font: str | None = None,
) -> FinishReport:
    """Finish into a new file, verify it, then atomically expose the result."""
    validate(spec)
    if not mark.is_file():
        raise verify.Rejected("the Denver Home Story brand mark is missing")
    source_probe = verify.check(
        source, expect_audio=True, min_seconds=MIN_SECONDS, max_seconds=MAX_SECONDS
    )
    workdir = destination.parent
    verify.reject_readable_digits(
        source,
        workdir / "ocr",
        before_seconds=max(0.0, source_probe.duration - END_CARD_SECONDS),
    )

    finish_spec = spec["finish"]
    background = workdir / "finish-background.png"
    calculator_url = finish_spec.get("calculator_url")
    used_calculator = bool(
        calculator_url and capture_calculator(str(calculator_url), background)
    )
    if not used_calculator:
        _fallback_card(background)

    opening = workdir / "finish-opening.txt"
    label = workdir / "finish-label.txt"
    display = workdir / "finish-display.txt"
    brokerage = workdir / "finish-brokerage.txt"
    wrapped = "\n".join(
        textwrap.wrap(
            str(finish_spec["opening_text"]), width=28, max_lines=2, placeholder="…"
        )
    )
    _write_text(opening, wrapped)
    _write_text(label, finish_spec["cta_label"])
    _write_text(display, finish_spec["cta_display"])
    _write_text(brokerage, spec["brokerage_line"])

    temporary = destination.with_name(destination.stem + ".part.mp4")
    command = build_command(
        source,
        temporary,
        duration=source_probe.duration,
        background=background,
        opening_file=opening,
        cta_label_file=label,
        cta_display_file=display,
        brokerage_file=brokerage,
        font=font or default_font(),
        mark=mark,
    )
    rendered = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=1800,
        check=False,
    )
    if rendered.returncode != 0:
        tail = rendered.stdout[-800:].decode(errors="replace").strip()
        raise RuntimeError(f"DHS finishing ffmpeg failed: {tail or 'no output'}")
    result = verify.check(
        temporary, expect_audio=True, min_seconds=MIN_SECONDS, max_seconds=MAX_SECONDS
    )
    os.replace(temporary, destination)
    return FinishReport(duration=result.duration, used_calculator=used_calculator)
